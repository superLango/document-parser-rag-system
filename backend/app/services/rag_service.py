"""RAG 编排服务模块。

本模块实现 RAG（Retrieval-Augmented Generation）完整编排流程，串联以下阶段：

1. 查询理解：通过 ``query_service`` 分析意图、抽取实体、重写查询
2. 检索：并行执行向量检索（embedding + vector_store）与知识图谱检索（graph_store）
3. 重排：通过 ``reranker_service`` 对候选文档进行 CrossEncoder 二次排序
4. 上下文组装：将重排后的文档片段与图谱实体组装为 LLM 输入上下文
5. 生成：调用 ``llm_service`` 生成最终回答，支持流式输出

各阶段均具备容错能力：
- 查询理解失败 → 使用原始查询继续后续流程
- 向量检索失败 → 返回包含错误信息的响应
- 重排失败 → 降级使用原始向量检索结果
- 图谱检索失败 → 跳过图谱上下文，仅使用文档片段
- LLM 生成失败 → 返回错误信息与已检索上下文

使用示例：
    from app.services.rag_service import rag_service

    # 完整查询
    response = await rag_service.query("304不锈钢的化学成分是什么？")
    # response.answer -> "304不锈钢的化学成分包括..."
    # response.citations -> [Citation(document_id=..., chunk_id=..., ...)]

    # 流式查询（用于 SSE）
    async for chunk in rag_service.query_stream("304不锈钢的化学成分是什么？"):
        print(chunk, end="")
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field

from app.core.config import settings
from app.core.logging import get_logger
from app.services.embedding_service import embedding_service
from app.services.graph_store import graph_store
from app.services.llm_service import llm_service
from app.services.query_service import QueryAnalysis, query_service
from app.services.reranker_service import RerankResult, reranker_service
from app.services.vector_store import vector_store

logger = get_logger(__name__)

# LLM 系统提示词，引导模型基于检索片段回答问题
_SYSTEM_PROMPT = (
    "你是一个文档问答助手。基于以下检索到的文档片段回答问题。"
    "如果无法从文档中找到答案，请说明。"
)


@dataclass
class Citation:
    """检索引用来源。

    封装一条用于支撑回答的检索证据，包含来源文档、分块、内容与分数。

    Attributes:
        document_id: 来源文档 ID。
        chunk_id: 来源分块 ID。
        content: 分块原文。
        score: 检索或重排分数。
        source: 来源类型，``"vector"`` 表示向量检索，``"graph"`` 表示知识图谱。
    """

    document_id: str
    chunk_id: str
    content: str
    score: float
    source: str = "vector"


@dataclass
class RAGResponse:
    """RAG 查询响应。

    Attributes:
        answer: LLM 生成的回答文本。
        intent: 查询意图分类。
        entities: 抽取的实体列表，每项为 ``{"text": str, "type": str}``。
        citations: 检索引用列表。
        query_analysis: 完整的查询分析信息字典。
        retrieval_count: 向量检索返回的候选数量。
        rerank_count: 重排后保留的结果数量。
    """

    answer: str
    intent: str
    entities: list[dict] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)
    query_analysis: dict = field(default_factory=dict)
    retrieval_count: int = 0
    rerank_count: int = 0


class RAGService:
    """RAG 编排服务。

    串联查询理解、检索、重排、上下文组装与 LLM 生成，提供完整的
    RAG 查询能力。所有下游服务均为模块级单例，通过 ``monkeypatch``
    替换其方法即可在测试中隔离。

    各阶段具备独立容错：单个阶段失败不会中断整个流程，而是降级处理
    并在日志中记录告警，保证服务可用性。
    """

    async def query(
        self,
        question: str,
        top_k: int = 5,
        doc_ids: list[str] | None = None,
        use_graph: bool = True,
        use_reranker: bool = True,
    ) -> RAGResponse:
        """处理用户查询，返回完整 RAG 响应。

        完整流程：查询理解 → 并行检索（向量+图谱）→ 重排 → 上下文组装 → LLM 生成。

        Args:
            question: 用户问题文本。
            top_k: 最终返回的文档片段数量。
            doc_ids: 限定检索的文档 ID 列表，``None`` 表示不限制。
            use_graph: 是否启用知识图谱检索。
            use_reranker: 是否启用重排。

        Returns:
            RAGResponse: 包含回答、引用、查询分析等信息的响应对象。
        """
        # 1. 查询理解
        analysis = await self._understand_query(question)

        # 2. 并行检索：向量检索与知识图谱检索
        retrieval_query = analysis.rewritten_query or question
        pool_size = settings.RAG_RERANK_POOL

        vector_results, graph_data = await self._parallel_retrieve(
            retrieval_query, question, analysis, pool_size, doc_ids, use_graph
        )

        # 向量检索失败时直接返回错误响应
        if vector_results is None:
            return self._build_error_response(
                analysis, "向量检索失败，无法获取相关文档"
            )

        retrieval_count = len(vector_results)

        # 空结果处理：仍调用 LLM 生成（模型会说明无法找到答案）
        if not vector_results:
            context = self._build_context([], graph_data, question)
            answer = await self._generate(context)
            return RAGResponse(
                answer=answer,
                intent=analysis.intent,
                entities=self._entities_to_dicts(analysis.entities),
                citations=[],
                query_analysis=analysis.model_dump(),
                retrieval_count=0,
                rerank_count=0,
            )

        # 3. 重排
        final_chunks, rerank_count = await self._rerank(
            retrieval_query, vector_results, top_k, use_reranker
        )

        # 4. 上下文组装
        context = self._build_context(final_chunks, graph_data, question)

        # 5. LLM 生成
        answer = await self._generate(context)

        # 6. 构建引用
        citations = self._build_citations(final_chunks)

        logger.info(
            "RAG 查询完成",
            question=question[:100],
            intent=analysis.intent,
            retrieval_count=retrieval_count,
            rerank_count=rerank_count,
            citation_count=len(citations),
        )

        return RAGResponse(
            answer=answer,
            intent=analysis.intent,
            entities=self._entities_to_dicts(analysis.entities),
            citations=citations,
            query_analysis=analysis.model_dump(),
            retrieval_count=retrieval_count,
            rerank_count=rerank_count,
        )

    async def query_stream(
        self,
        question: str,
        top_k: int = 5,
        doc_ids: list[str] | None = None,
        use_graph: bool = True,
        use_reranker: bool = True,
    ) -> AsyncGenerator[str, None]:
        """处理用户查询，流式返回 LLM 生成内容（用于 SSE）。

        流程与 :meth:`query` 相同，仅在 LLM 生成阶段使用流式输出。
        前置阶段（查询理解、检索、重排、上下文组装）同步完成后，
        再通过 ``llm_service.stream_generate`` 逐块 yield 文本。

        Args:
            question: 用户问题文本。
            top_k: 最终返回的文档片段数量。
            doc_ids: 限定检索的文档 ID 列表。
            use_graph: 是否启用知识图谱检索。
            use_reranker: 是否启用重排。

        Yields:
            str: LLM 生成的文本分片，调用方应累加拼接为完整输出。
        """
        # 1. 查询理解
        analysis = await self._understand_query(question)

        # 2. 并行检索
        retrieval_query = analysis.rewritten_query or question
        pool_size = settings.RAG_RERANK_POOL

        vector_results, graph_data = await self._parallel_retrieve(
            retrieval_query, question, analysis, pool_size, doc_ids, use_graph
        )

        # 向量检索失败时返回错误信息
        if vector_results is None:
            yield "抱歉，向量检索失败，无法获取相关文档。"
            return

        # 3. 重排
        final_chunks, _ = await self._rerank(
            retrieval_query, vector_results, top_k, use_reranker
        )

        # 4. 上下文组装
        context = self._build_context(final_chunks, graph_data, question)

        # 5. 流式生成
        try:
            async for chunk in llm_service.stream_generate(
                prompt=context,
                system_prompt=_SYSTEM_PROMPT,
            ):
                yield chunk
        except Exception as err:
            logger.error("LLM 流式生成失败", error=str(err), exc_info=True)
            yield f"\n[生成失败：{err}]"

    # ---------------------------------------------------------------
    # 内部方法：查询理解
    # ---------------------------------------------------------------
    async def _understand_query(self, question: str) -> QueryAnalysis:
        """查询理解，失败时返回兜底分析结果。

        Args:
            question: 用户原始查询。

        Returns:
            QueryAnalysis: 查询分析结果，失败时 intent=general，
            rewritten_query=原查询。
        """
        try:
            return await query_service.analyze(question)
        except Exception as err:
            logger.warning("查询理解失败，使用原始查询", error=str(err))
            return QueryAnalysis(
                intent="general",
                rewritten_query=question,
                entities=[],
                sub_queries=[],
                confidence=0.0,
            )

    # ---------------------------------------------------------------
    # 内部方法：并行检索
    # ---------------------------------------------------------------
    async def _parallel_retrieve(
        self,
        retrieval_query: str,
        question: str,
        analysis: QueryAnalysis,
        pool_size: int,
        doc_ids: list[str] | None,
        use_graph: bool,
    ) -> tuple[list[dict] | None, dict | None]:
        """并行执行向量检索与知识图谱检索。

        使用 ``asyncio.gather(return_exceptions=True)`` 确保单个检索失败
        不影响另一个。向量检索失败时返回 ``(None, graph_data)``，由调用方
        决定是否中止；图谱检索失败时返回 ``(vector_results, None)``，
        跳过图谱上下文。

        Args:
            retrieval_query: 重写后的检索查询。
            question: 用户原始问题（用于图谱检索回退）。
            analysis: 查询分析结果（用于图谱实体检索）。
            pool_size: 向量检索候选池大小。
            doc_ids: 限定文档 ID 列表。
            use_graph: 是否启用图谱检索。

        Returns:
            tuple: ``(向量检索结果列表或 None, 图谱数据字典或 None)``。
        """
        vector_task = self._vector_search(retrieval_query, pool_size, doc_ids)
        graph_task = (
            self._graph_search(question, analysis) if use_graph else None
        )

        tasks = [vector_task]
        if graph_task is not None:
            tasks.append(graph_task)

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 处理向量检索结果
        vector_result = results[0]
        if isinstance(vector_result, Exception):
            logger.error(
                "向量检索失败", error=str(vector_result), exc_info=True
            )
            vector_results = None
        else:
            vector_results = vector_result

        # 处理图谱检索结果
        graph_data = None
        if graph_task is not None:
            graph_result = results[1]
            if isinstance(graph_result, Exception):
                logger.warning(
                    "知识图谱检索失败，跳过图谱上下文",
                    error=str(graph_result),
                )
                graph_data = None
            else:
                graph_data = graph_result

        return vector_results, graph_data

    # ---------------------------------------------------------------
    # 内部方法：向量检索
    # ---------------------------------------------------------------
    async def _vector_search(
        self,
        query: str,
        pool_size: int,
        doc_ids: list[str] | None,
    ) -> list[dict]:
        """向量检索：嵌入查询 → 混合检索。

        通过 ``embedding_service.embed_query`` 生成 Dense+Sparse 向量，
        再调用 ``vector_store.hybrid_search`` 执行 RRF 融合检索。

        Args:
            query: 检索查询文本（重写后的查询）。
            pool_size: 检索候选池大小（重排前数量）。
            doc_ids: 限定文档 ID 列表，``None`` 不限制。

        Returns:
            list[dict]: 向量检索结果列表（vector_store 原始格式，含
            ``chunk_id``/``text``/``doc_id``/``score``/``metadata`` 等字段）。
        """
        # 嵌入查询，获取 Dense+Sparse 向量
        embed_result = await embedding_service.embed_query(query)
        dense_vec = embed_result["dense_vector"]
        sparse_vec = embed_result["sparse_for_milvus"]

        # 混合检索（Dense + Sparse + RRF 融合）
        results = await vector_store.hybrid_search(
            query_dense=dense_vec,
            query_sparse=sparse_vec,
            top_k=pool_size,
        )

        # 按文档 ID 过滤（vector_store 不支持原生过滤，后置过滤）
        if doc_ids:
            doc_id_set = set(doc_ids)
            results = [r for r in results if r.get("doc_id") in doc_id_set]

        logger.info(
            "向量检索完成",
            query=query[:100],
            pool_size=pool_size,
            retrieved=len(results),
            filtered=len(doc_ids) if doc_ids else 0,
        )
        return results

    # ---------------------------------------------------------------
    # 内部方法：知识图谱检索
    # ---------------------------------------------------------------
    async def _graph_search(
        self,
        question: str,
        analysis: QueryAnalysis,
    ) -> dict | None:
        """知识图谱检索：搜索实体并获取关系子图。

        使用查询分析提取的实体文本搜索图谱节点，并获取首个实体的
        1 跳子图关系。任一步骤失败均返回 ``None``，跳过图谱上下文。

        Args:
            question: 用户原始问题（无实体时作为搜索回退词）。
            analysis: 查询分析结果（提供抽取的实体列表）。

        Returns:
            dict | None: ``{"entities": [...], "relations": [...]}`` 或 ``None``。
        """
        try:
            # 使用查询分析提取的实体文本作为搜索词，无实体时回退到原始问题
            search_terms = [e.text for e in analysis.entities if e.text]
            if not search_terms:
                search_terms = [question]

            # 对前 3 个搜索词进行节点搜索
            all_nodes: list[dict] = []
            seen_ids: set = set()
            for term in search_terms[:3]:
                nodes = await graph_store.search_nodes(name=term, limit=5)
                for node in nodes:
                    node_id = node.get("id")
                    if node_id not in seen_ids:
                        seen_ids.add(node_id)
                        all_nodes.append(node)

            if not all_nodes:
                return {"entities": [], "relations": []}

            # 获取首个实体的 1 跳子图，提取关系
            relations: list[dict] = []
            try:
                subgraph = await graph_store.get_subgraph(
                    all_nodes[0]["name"], max_hops=1
                )
                relations = subgraph.get("edges", [])
            except Exception as err:
                logger.warning(
                    "获取子图关系失败，仅使用实体信息", error=str(err)
                )

            return {"entities": all_nodes, "relations": relations}
        except Exception as err:
            logger.warning(
                "知识图谱检索失败，跳过图谱上下文", error=str(err)
            )
            return None

    # ---------------------------------------------------------------
    # 内部方法：重排
    # ---------------------------------------------------------------
    async def _rerank(
        self,
        query: str,
        vector_results: list[dict],
        top_k: int,
        use_reranker: bool,
    ) -> tuple[list[dict], int]:
        """对向量检索结果进行重排。

        ``use_reranker=False`` 时直接截取前 ``top_k`` 条原始结果。
        重排失败时降级使用原始结果。

        Args:
            query: 重写后的检索查询（作为 CrossEncoder 输入）。
            vector_results: 向量检索结果列表（vector_store 格式）。
            top_k: 最终返回数量。
            use_reranker: 是否启用重排。

        Returns:
            tuple: ``(最终文档列表, 重排后数量)``。文档列表中每项为
            统一内部格式（含 ``chunk_id``/``document_id``/``content``/
            ``score``/``metadata``）。
        """
        # 将 vector_store 格式转换为统一内部格式（text→content, doc_id→document_id）
        chunks = [self._convert_vector_result(r) for r in vector_results]

        if not use_reranker:
            final = chunks[:top_k]
            return final, len(final)

        try:
            rerank_results = await reranker_service.rerank(
                query=query,
                documents=chunks,
                top_k=top_k,
            )
            final = [self._convert_rerank_result(r) for r in rerank_results]
            logger.info(
                "重排完成",
                input_count=len(chunks),
                output_count=len(final),
            )
            return final, len(final)
        except Exception as err:
            logger.warning("重排失败，使用原始检索结果", error=str(err))
            final = chunks[:top_k]
            return final, len(final)

    # ---------------------------------------------------------------
    # 内部方法：上下文组装
    # ---------------------------------------------------------------
    def _build_context(
        self,
        chunks: list[dict],
        graph_data: dict | None,
        question: str,
    ) -> str:
        """组装 LLM 输入上下文。

        格式::

            === 检索到的文档片段 ===
            [1] 来源: 文档 xxx, 片段 yyy
            内容: <chunk_content>

            [2] 来源: 文档 xxx, 片段 yyy
            内容: <chunk_content>

            === 知识图谱信息 ===
            实体: 304不锈钢 (类型: 材料)
            关系: 304不锈钢 --执行标准--> GB/T 1220-2007

            问题: {question}

        Args:
            chunks: 文档片段列表（内部格式，含 content/document_id/chunk_id）。
            graph_data: 图谱数据 ``{"entities": [...], "relations": [...]}``，
                ``None`` 时跳过图谱部分。
            question: 用户原始问题。

        Returns:
            str: 组装好的上下文字符串，按 ``RAG_MAX_CONTEXT_LENGTH`` 截断。
        """
        lines: list[str] = ["=== 检索到的文档片段 ==="]

        # 文档片段部分
        for idx, chunk in enumerate(chunks, start=1):
            content = chunk.get("content", "")
            doc_id = chunk.get("document_id", "")
            chunk_id = chunk.get("chunk_id", "")
            lines.append(f"[{idx}] 来源: 文档 {doc_id}, 片段 {chunk_id}")
            lines.append(f"内容: {content}")
            lines.append("")

        # 知识图谱部分
        if graph_data:
            entities = graph_data.get("entities", [])
            relations = graph_data.get("relations", [])
            if entities or relations:
                lines.append("=== 知识图谱信息 ===")
                for node in entities:
                    name = node.get("name", "")
                    labels = node.get("labels", [])
                    label_str = "、".join(labels) if labels else "未知"
                    lines.append(f"实体: {name} (类型: {label_str})")
                for edge in relations:
                    source = edge.get("source", "")
                    target = edge.get("target", "")
                    rel_type = edge.get("type", "")
                    lines.append(f"关系: {source} --{rel_type}--> {target}")
                lines.append("")

        # 问题部分
        lines.append(f"问题: {question}")

        context = "\n".join(lines)

        # 按 RAG_MAX_CONTEXT_LENGTH 截断，防止超出模型上下文窗口
        max_len = settings.RAG_MAX_CONTEXT_LENGTH
        original_len = len(context)
        if original_len > max_len:
            context = context[:max_len] + "\n...(上下文已截断)"
            logger.warning(
                "上下文超出最大长度，已截断",
                original_length=original_len,
                max_length=max_len,
            )

        return context

    # ---------------------------------------------------------------
    # 内部方法：LLM 生成
    # ---------------------------------------------------------------
    async def _generate(self, context: str) -> str:
        """调用 LLM 生成回答。

        生成失败时返回包含错误信息的兜底回答，不抛出异常。

        Args:
            context: 组装好的上下文字符串。

        Returns:
            str: LLM 生成的回答文本。
        """
        try:
            answer = await llm_service.generate(
                prompt=context,
                system_prompt=_SYSTEM_PROMPT,
            )
            return answer
        except Exception as err:
            logger.error("LLM 生成失败", error=str(err), exc_info=True)
            return f"抱歉，生成回答时发生错误：{err}"

    # ---------------------------------------------------------------
    # 内部方法：格式转换与辅助
    # ---------------------------------------------------------------
    @staticmethod
    def _convert_vector_result(result: dict) -> dict:
        """将 vector_store 检索结果转换为统一内部格式。

        vector_store 返回 ``text``/``doc_id``，内部统一使用
        ``content``/``document_id`` 以对齐 reranker 输入格式。

        Args:
            result: vector_store 返回的检索结果字典。

        Returns:
            dict: 统一内部格式，含 chunk_id/document_id/content/score/metadata。
        """
        return {
            "chunk_id": result.get("chunk_id", ""),
            "document_id": result.get("doc_id", ""),
            "content": result.get("text", ""),
            "score": float(result.get("score", 0.0)),
            "metadata": result.get("metadata", {}) or {},
        }

    @staticmethod
    def _convert_rerank_result(result: RerankResult) -> dict:
        """将 RerankResult 转换为统一内部格式。

        Args:
            result: reranker_service 返回的 RerankResult 对象。

        Returns:
            dict: 统一内部格式，score 使用 rerank_score。
        """
        return {
            "chunk_id": result.chunk_id,
            "document_id": result.document_id,
            "content": result.content,
            "score": result.rerank_score,
            "metadata": result.metadata,
        }

    @staticmethod
    def _build_citations(chunks: list[dict]) -> list[Citation]:
        """从文档片段列表构建引用列表。

        Args:
            chunks: 内部格式的文档片段列表。

        Returns:
            list[Citation]: 引用列表，每项 source="vector"。
        """
        return [
            Citation(
                document_id=chunk.get("document_id", ""),
                chunk_id=chunk.get("chunk_id", ""),
                content=chunk.get("content", ""),
                score=float(chunk.get("score", 0.0)),
                source="vector",
            )
            for chunk in chunks
        ]

    @staticmethod
    def _entities_to_dicts(entities: list) -> list[dict]:
        """将 QueryEntity 列表转换为字典列表。

        Args:
            entities: QueryEntity 对象列表。

        Returns:
            list[dict]: 每项为 ``{"text": str, "type": str}``。
        """
        return [{"text": e.text, "type": e.type} for e in entities]

    def _build_error_response(
        self,
        analysis: QueryAnalysis,
        message: str,
    ) -> RAGResponse:
        """构建错误响应。

        Args:
            analysis: 查询分析结果。
            message: 错误消息。

        Returns:
            RAGResponse: 包含错误消息的响应对象。
        """
        return RAGResponse(
            answer=message,
            intent=analysis.intent,
            entities=self._entities_to_dicts(analysis.entities),
            citations=[],
            query_analysis=analysis.model_dump(),
            retrieval_count=0,
            rerank_count=0,
        )


# 模块级单例，供整个应用直接导入使用
rag_service = RAGService()
