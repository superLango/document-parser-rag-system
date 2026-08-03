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
    from app.services.rag.rag_service import rag_service

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
import re
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.services.vector.bm25_retriever import bm25_retriever
from app.services.cache_service import rag_cache_service
from app.services.embedding.embedding_service import embedding_service
from app.services.graph.graph_store import graph_store
from app.services.llm.llm_service import llm_service
from app.services.rag.query_service import QueryAnalysis, query_service
from app.services.vector.chunk_vector_store import vector_store

# TODO: reranker目录已删除，重排功能待重构
# from app.services.reranker.reranker_service import RerankResult, reranker_service
reranker_service = None

logger = get_logger(__name__)

# LlamaIndex 索引管理器：懒导入，避免依赖未安装时影响主流程
_index_manager: Any = None


def _get_index_manager() -> Any:
    """懒加载 LlamaIndex 索引管理器单例。

    采用延迟导入，避免 llama-index-core 未安装时影响整个 rag_service 模块加载。
    首次调用时创建 IndexManager 实例并缓存。

    Returns:
        IndexManager 实例，导入失败时返回 None。
    """
    global _index_manager
    if _index_manager is not None:
        return _index_manager
    try:
        from app.services.index_manager import index_manager as _im
        _index_manager = _im
        return _index_manager
    except Exception as err:
        logger.warning(
            "LlamaIndex 索引管理器不可用，降级到 Milvus 管道",
            error=str(err),
        )
        return None

# LLM 系统提示词，引导模型基于检索片段回答问题（含引用溯源要求）
_SYSTEM_PROMPT = (
    "你是一个文档问答助手。请严格基于以下检索到的文档片段回答问题。\n"
    "要求：\n"
    "1. 仅基于提供的文档片段回答，不得编造信息\n"
    "2. 在回答中标注信息来源，格式为[片段N]，N 对应上下文中的片段编号\n"
    "3. 如无法从文档中找到答案，明确说明\"根据现有文档无法回答\"\n"
    "4. 对于数值类信息，必须给出具体数值和单位（如 205 N/mm²），禁止只输出"
    "字段名、单位或列标题作为答案\n"
    "5. 回答末尾附上来源标注，格式为\"来源：[片段N, 片段M]\"\n"
    "6. **优先参考表格分块**（标记为【表格N】的片段）：当查询涉及具体数值、"
    "牌号、化学成分、力学性能、热处理制度等数据时，必须从表格分块中查找准确"
    "数值，不要被前言或标准修订说明中的描述性数值误导\n"
    "7. **区分牌号**：回答特定牌号（如12Cr18Ni9）的数值时，必须确认表格中"
    "对应行的数据，不要混淆不同牌号的数值\n"
    "8. **表格数据提取流程**（必须严格执行）：\n"
    "   a. 在问题中识别目标牌号（如12Cr18Ni9）和目标属性（如Rp0.2、旧牌号、"
    "热处理制度）\n"
    "   b. 逐行扫描表格内容，查找\"新牌号\"列或\"旧牌号\"列中与目标牌号完全"
    "匹配的数据行\n"
    "   c. 根据目标属性定位对应列（即使列标题有OCR识别误差，如Rp.2b/Rp.2应"
    "理解为Rp0.2），提取该行该列的具体数值\n"
    "   d. 将提取到的数值作为答案，禁止用列标题、单位、字段名替代数值\n"
    "9. **牌号对照表列含义**（关键，避免混淆）：\n"
    "   - \"统一数字代号\"列：以S开头的代码（如S30210、S31608），是国标数字"
    "标识，不是牌号\n"
    "   - \"新牌号\"列：以0x/1x/2x开头的牌号（如12Cr18Ni9、06Cr17Ni12Mo2），"
    "是现行牌号\n"
    "   - \"旧牌号\"列：以0Cr/1Cr/2Cr开头的牌号（如0Cr17Ni12Mo2、1Cr18Ni9），"
    "是已废止牌号\n"
    "   当问题询问\"旧牌号\"时，必须从\"旧牌号\"列提取，不得返回\"统一数字"
    "代号\"或\"新牌号\"\n"
    "10. **热处理制度查询**：当查询涉及\"热处理\"\"退火\"\"淬火\"\"回火\""
    "\"固溶\"等工艺时，优先参考列标题含\"退火/℃\"\"淬火/℃\"\"回火/℃\""
    "\"钢棒的热处理制度\"\"试样的热处理制度\"的表格分块，提取具体温度和"
    "冷却方式\n"
    "11. **答案完整性检查**：在输出答案前，自检答案是否包含问题所问的具体"
    "数值或具体牌号。若答案只包含字段名、单位、列标题或\"参见附录X\"等模糊"
    "表述，说明提取失败，必须重新扫描表格行提取具体数据"
)

# 按意图的答案结构化模板，拼接到系统提示词末尾引导输出格式
_INTENT_ANSWER_TEMPLATES: dict[str, str] = {
    "general": (
        "\n回答格式要求：直接给出答案，附上数值和单位，并标注来源片段。"
    ),
    "document_search": (
        "\n回答格式要求：直接给出答案，附上数值和单位，并标注来源片段。"
    ),
    "summarization": (
        "\n回答格式要求：按主题分点总结，每点2-3句话，每点标注来源片段。"
    ),
    "comparison": (
        "\n回答格式要求：使用表格对比差异，列出相同点和不同点，并标注来源片段。"
    ),
    "knowledge_graph": (
        "\n回答格式要求：描述实体关系，标注来源片段。"
    ),
}


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
        kb_id: uuid.UUID | None = None,
    ) -> RAGResponse:
        """处理用户查询，返回完整 RAG 响应（含多级缓存）。

        知识库隔离：``kb_id`` 非 None 时，检索限定在该 KB 专属向量 Collection
        与图谱 space，缓存键带 KB 前缀，避免跨 KB 数据泄漏。``None`` 时走全局
        命名空间（向后兼容旧 ``/qa`` 端点）。

        缓存策略：
        1. L1 精确匹配（内存）→ 直接返回，跳过全部下游阶段
        2. L2 语义匹配（Valkey）→ 直接返回，跳过全部下游阶段
        3. 全部未命中 → 执行完整 RAG 链路，异步回写缓存

        完整流程：查询理解 → [LlamaIndex 索引路由] → 并行检索（向量+图谱）
        → 重排 → 上下文组装 → LLM 生成。

        LlamaIndex 索引路由：对于 summarization 和 comparison 意图，优先尝试
        LlamaIndex 的 SummaryIndex/TreeIndex；若索引不可用或查询失败，降级到
        现有 Milvus 混合检索管道，保证向后兼容。

        Args:
            question: 用户问题文本。
            top_k: 最终返回的文档片段数量。
            doc_ids: 限定检索的文档 ID 列表，``None`` 表示不限制。
            use_graph: 是否启用知识图谱检索。
            use_reranker: 是否启用重排。

        Returns:
            RAGResponse: 包含回答、引用、查询分析等信息的响应对象。
        """
        # 1. 多级缓存检查（L1 精确 + L2 语义）
        cached = await rag_cache_service.get_response(question, top_k, doc_ids, kb_id)
        if cached is not None:
            logger.info(
                "缓存命中，跳过完整 RAG 链路",
                question_preview=question[:50],
                cache_level=cached.get("_cache_level", "unknown"),
            )
            return self._dict_to_response(cached)

        # 2. 缓存未命中：执行完整 RAG 链路
        response = await self._execute_query(
            question, top_k, doc_ids, use_graph, use_reranker, kb_id
        )

        # 3. 异步回写缓存（仅缓存有效回答，不缓存错误响应）
        if response.answer and not response.answer.startswith("抱歉"):
            try:
                await rag_cache_service.set_response(
                    question,
                    self._response_to_dict(response),
                    top_k,
                    doc_ids,
                    kb_id,
                )
            except Exception as err:
                logger.debug("缓存回写失败", error=str(err))

        return response

    async def _execute_query(
        self,
        question: str,
        top_k: int = 5,
        doc_ids: list[str] | None = None,
        use_graph: bool = True,
        use_reranker: bool = True,
        kb_id: uuid.UUID | None = None,
    ) -> RAGResponse:
        """执行完整 RAG 链路（不含缓存）。

        内部方法，由 :meth:`query` 在缓存未命中时调用。包含完整的
        查询理解 → LlamaIndex 路由 → 并行检索 → 重排 → 生成流程。

        知识库隔离：``kb_id`` 非 None 时跳过全局 LlamaIndex 索引路由
        （该索引为全局构建，未按 KB 隔离），并向下传递给检索层。

        Args:
            question: 用户问题文本。
            top_k: 最终返回的文档片段数量。
            doc_ids: 限定检索的文档 ID 列表，``None`` 表示不限制。
            use_graph: 是否启用知识图谱检索。
            use_reranker: 是否启用重排。
            kb_id: 知识库 ID。``None`` 走全局命名空间（向后兼容）。

        Returns:
            RAGResponse: 包含回答、引用、查询分析等信息的响应对象。
        """
        # 1. 查询理解与查询嵌入并行执行（P1.3 LLM 调用并行化）
        # 意图分析（含 LLM 调用）与查询嵌入（bge-m3）相互独立，并行执行
        # 可节省 ~15s 的串行等待时间。嵌入结果在 Milvus 路径复用。
        analysis_task = asyncio.create_task(self._understand_query(question))
        embed_task = asyncio.create_task(embedding_service.embed_query(question))
        analysis, precomputed_embed = await asyncio.gather(
            analysis_task, embed_task, return_exceptions=True
        )
        # 意图分析失败时降级为兜底分析（_understand_query 内部已处理，
        # 但 gather 的 return_exceptions 仍可能包裹异常，需兜底）
        if isinstance(analysis, Exception):
            logger.warning("意图分析异常，使用兜底", error=str(analysis))
            analysis = QueryAnalysis(
                intent="general", rewritten_query=question,
                entities=[], sub_queries=[], confidence=0.0,
            )
        # 嵌入失败时置 None，_vector_search 会现场重新嵌入
        if isinstance(precomputed_embed, Exception):
            logger.warning("预计算嵌入失败，将现场嵌入", error=str(precomputed_embed))
            precomputed_embed = None

        # 1.5 LlamaIndex 索引路由：对 summarization/comparison 意图优先使用 LlamaIndex
        # 知识库隔离：LlamaIndex 索引为全局构建（未按 KB 隔离），KB 查询时跳过
        # 该路由，避免跨 KB 数据泄漏，降级到 Milvus KB 专属 Collection 检索。
        if kb_id is None and analysis.intent in ("summarization", "comparison"):
            li_result = await self._try_llamaindex_query(
                question, analysis.intent, top_k, analysis.sub_queries
            )
            if li_result is not None:
                # LlamaIndex 成功处理，直接返回结果
                return RAGResponse(
                    answer=li_result.answer,
                    intent=analysis.intent,
                    entities=self._entities_to_dicts(analysis.entities),
                    citations=[
                        Citation(
                            document_id=c.get("document_id", ""),
                            chunk_id=c.get("chunk_id", ""),
                            content=c.get("content", ""),
                            score=c.get("score", 0.0),
                            source=c.get("source", "llamaindex"),
                        )
                        for c in li_result.citations
                    ],
                    query_analysis=analysis.model_dump(),
                    retrieval_count=len(li_result.citations),
                    rerank_count=len(li_result.citations),
                )
            # LlamaIndex 不可用或失败，降级到 Milvus 管道

        # 1.6 HyDE 查询改写（P1.2）：对 general/document_search 意图
        # 生成假设文档，用假设文档嵌入替代原始查询嵌入，提升召回率 ~28%
        if analysis.intent in ("general", "document_search") and precomputed_embed is not None:
            hyde_doc = await query_service.hyde_rewrite(question)
            if hyde_doc is not None:
                try:
                    hyde_embed = await embedding_service.embed_query(hyde_doc)
                    precomputed_embed = hyde_embed
                    logger.info(
                        "HyDE 启用：使用假设文档嵌入进行检索",
                        hyde_doc_len=len(hyde_doc),
                    )
                except Exception as err:
                    logger.warning("HyDE 嵌入失败，回退原始查询嵌入", error=str(err))
            # HyDE 返回 None 时保持原始预计算嵌入不变

        # 2. 并行检索：向量检索（复用预计算嵌入）与知识图谱检索
        retrieval_query = analysis.rewritten_query or question
        pool_size = settings.RAG_RERANK_POOL

        vector_results, graph_data = await self._parallel_retrieve(
            retrieval_query, question, analysis, pool_size, doc_ids, use_graph,
            precomputed_embed=precomputed_embed, kb_id=kb_id,
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
            answer = await self._generate(context, intent=analysis.intent, question=question)
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
            retrieval_query, vector_results, top_k, use_reranker,
            original_question=question,
        )

        # 4. 上下文组装
        context = self._build_context(final_chunks, graph_data, question)

        # 5. LLM 生成（传入 intent 和 question 用于 LLM 路由）
        answer = await self._generate(context, intent=analysis.intent, question=question)

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
        kb_id: uuid.UUID | None = None,
    ) -> AsyncGenerator[str, None]:
        """处理用户查询，流式返回 LLM 生成内容（用于 SSE）。

        流程与 :meth:`query` 相同，仅在 LLM 生成阶段使用流式输出。
        前置阶段（查询理解、检索、重排、上下文组装）同步完成后，
        再通过 ``llm_service.stream_generate`` 逐块 yield 文本。

        知识库隔离：``kb_id`` 非 None 时检索限定在 KB 专属向量 Collection
        与图谱 space，并跳过全局 LlamaIndex 索引路由。

        LlamaIndex 路径流式输出：对 summarization/comparison 意图，优先
        调用 ``_try_llamaindex_query`` 获取完整结果，再按句子分块 yield，
        模拟流式效果。失败时降级到 Milvus 路径的真实流式输出。

        Args:
            question: 用户问题文本。
            top_k: 最终返回的文档片段数量。
            doc_ids: 限定检索的文档 ID 列表。
            use_graph: 是否启用知识图谱检索。
            use_reranker: 是否启用重排。
            kb_id: 知识库 ID。``None`` 走全局命名空间（向后兼容）。

        Yields:
            str: LLM 生成的文本分片，调用方应累加拼接为完整输出。
        """
        # 1. 查询理解
        analysis = await self._understand_query(question)

        # 1.5 LlamaIndex 路径流式输出（summarization/comparison 意图）
        # 知识库隔离：LlamaIndex 索引为全局构建，KB 查询时跳过
        if kb_id is None and analysis.intent in ("summarization", "comparison"):
            li_result = await self._try_llamaindex_query(
                question, analysis.intent, top_k, analysis.sub_queries
            )
            if li_result is not None and li_result.answer:
                # 将完整答案按句子分块 yield，模拟流式输出
                async for chunk in self._stream_chunks(li_result.answer):
                    yield chunk
                return
            # LlamaIndex 不可用或失败，降级到 Milvus 流式路径

        # 2. 并行检索
        retrieval_query = analysis.rewritten_query or question
        pool_size = settings.RAG_RERANK_POOL

        vector_results, graph_data = await self._parallel_retrieve(
            retrieval_query, question, analysis, pool_size, doc_ids, use_graph,
            kb_id=kb_id,
        )

        # 向量检索失败时返回错误信息
        if vector_results is None:
            yield "抱歉，向量检索失败，无法获取相关文档。"
            return

        # 3. 重排
        final_chunks, _ = await self._rerank(
            retrieval_query, vector_results, top_k, use_reranker,
            original_question=question,
        )

        # 4. 上下文组装
        context = self._build_context(final_chunks, graph_data, question)

        # 5. 流式生成（使用意图模板）
        template_suffix = _INTENT_ANSWER_TEMPLATES.get(analysis.intent, "")
        stream_system_prompt = _SYSTEM_PROMPT + template_suffix if template_suffix else _SYSTEM_PROMPT
        try:
            async for chunk in llm_service.stream_generate(
                prompt=context,
                system_prompt=stream_system_prompt,
            ):
                yield chunk
        except Exception as err:
            logger.error("LLM 流式生成失败", error=str(err), exc_info=True)
            yield f"\n[生成失败：{err}]"

    @staticmethod
    async def _stream_chunks(
        text: str, chunk_size: int = 64
    ) -> AsyncGenerator[str, None]:
        """将完整文本按固定长度分块 yield，模拟流式输出。

        用于 LlamaIndex 路径（非真实流式），让前端能渐进式渲染。
        按字符数分块，避免在句子中间切断时产生乱码（UTF-8 安全）。

        Args:
            text: 完整文本。
            chunk_size: 每块字符数，默认 64。

        Yields:
            str: 文本分片。
        """
        if not text:
            return
        # 按字符切片，Python 字符串已按 Unicode 码点处理，不会产生乱码
        for i in range(0, len(text), chunk_size):
            yield text[i : i + chunk_size]
            # 短暂让出事件循环，模拟流式节奏
            await asyncio.sleep(0.02)

    # ---------------------------------------------------------------
    # 内部方法：LlamaIndex 索引路由
    # ---------------------------------------------------------------
    # LlamaIndex 路径超时阈值（秒），超时后自动降级到 Milvus 路径
    _LLAMAINDEX_TIMEOUT: float = 30.0

    async def _try_llamaindex_query(
        self,
        question: str,
        intent: str,
        top_k: int,
        sub_queries: list[str] | None = None,
    ) -> Any:
        """尝试使用 LlamaIndex 索引处理查询（带超时降级）。

        路由策略：
        - ``summarization`` → IndexManager.query_with_intent（SummaryIndex）
        - ``comparison`` → 优先 SubQuestionQueryEngine（子问题分解），
          失败降级到 IndexManager.query_with_intent（TreeIndex）

        超时保护：整个 LlamaIndex 路径执行时间超过 ``_LLAMAINDEX_TIMEOUT``
        秒后自动取消，降级到 Milvus 管道，避免用户长时间等待。

        若 LlamaIndex 不可用、未构建或查询失败，返回 None 由调用方降级到 Milvus。

        Args:
            question: 用户查询文本。
            intent: 查询意图（summarization 或 comparison）。
            top_k: 返回结果数量上限。
            sub_queries: 子问题列表（comparison 意图时使用）。

        Returns:
            IndexQueryResult | EngineQueryResult | None: 查询结果，失败返回 None。
        """
        async def _do_llamaindex_query() -> Any:
            """LlamaIndex 查询内部实现（可被超时取消）。"""
            # comparison 意图：优先尝试 SubQuestionQueryEngine
            if intent == "comparison" and sub_queries:
                sq_result = await self._try_subquestion_engine(
                    question, sub_queries, top_k
                )
                if sq_result is not None:
                    return sq_result
                # SubQuestionQueryEngine 失败，降级到 TreeIndex

            # 通用 LlamaIndex 索引查询（SummaryIndex/TreeIndex/KeywordTableIndex）
            im = _get_index_manager()
            if im is None:
                return None
            try:
                result = await im.query_with_intent(question, intent, top_k)
                # 索引未构建或查询失败时 result.answer 为空
                if not result.answer and not result.citations:
                    logger.debug(
                        "LlamaIndex 查询返回空结果，降级到 Milvus",
                        intent=intent,
                        index_type=result.index_type,
                    )
                    return None
                logger.info(
                    "LlamaIndex 索引查询成功",
                    intent=intent,
                    index_type=result.index_type,
                    citation_count=len(result.citations),
                )
                return result
            except Exception as err:
                logger.warning(
                    "LlamaIndex 索引查询异常，降级到 Milvus",
                    intent=intent,
                    error=str(err),
                )
                return None
            return None

        # 外层超时保护：超过阈值则取消并降级到 Milvus
        try:
            return await asyncio.wait_for(
                _do_llamaindex_query(), timeout=self._LLAMAINDEX_TIMEOUT
            )
        except asyncio.TimeoutError:
            logger.warning(
                "LlamaIndex 路径超时，降级到 Milvus",
                intent=intent,
                timeout=self._LLAMAINDEX_TIMEOUT,
            )
            return None

    async def _try_subquestion_engine(
        self,
        question: str,
        sub_queries: list[str],
        top_k: int,
    ) -> Any:
        """尝试使用 SubQuestionQueryEngine 处理 comparison 意图查询。

        Args:
            question: 原始用户问题。
            sub_queries: 子问题列表。
            top_k: 返回结果数量上限。

        Returns:
            EngineQueryResult | None: 查询结果，失败返回 None。
        """
        try:
            from app.services.rag.query_engines import subquestion_engine
            result = await subquestion_engine.query(
                question=question,
                sub_queries=sub_queries,
                top_k=top_k,
            )
            if not result.answer:
                logger.debug("SubQuestionQueryEngine 返回空结果")
                return None
            logger.info(
                "SubQuestionQueryEngine 查询成功",
                sub_query_count=len(sub_queries),
                citation_count=len(result.citations),
            )
            return result
        except ImportError:
            logger.debug("query_engines 模块不可用，跳过 SubQuestionQueryEngine")
            return None
        except Exception as err:
            logger.warning(
                "SubQuestionQueryEngine 查询异常",
                error=str(err),
            )
            return None

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
        precomputed_embed: dict | None = None,
        kb_id: uuid.UUID | None = None,
    ) -> tuple[list[dict] | None, dict | None]:
        """并行执行向量检索、BM25 检索与知识图谱检索。

        P2.3 优化：在原有向量检索（Dense+Sparse）与图谱检索基础上，
        增加 BM25 第三路检索，通过 RRF 融合三路结果提升召回率
        （预期 +15%）。

        知识库隔离：``kb_id`` 非 None 时，向量检索与图谱检索均路由到 KB
        专属 Collection/space；BM25 为全局内存索引（未按 KB 隔离），
        KB 查询时跳过 BM25 融合，避免跨 KB 数据泄漏。

        使用 ``asyncio.gather(return_exceptions=True)`` 确保单个检索失败
        不影响其他。向量检索失败时返回 ``(None, graph_data)``，由调用方
        决定是否中止；图谱检索失败时返回 ``(vector_results, None)``，
        跳过图谱上下文；BM25 检索失败时仅跳过 BM25 融合，不影响主流程。

        Args:
            retrieval_query: 重写后的检索查询。
            question: 用户原始问题（用于图谱检索回退）。
            analysis: 查询分析结果（用于图谱实体检索）。
            pool_size: 向量检索候选池大小。
            doc_ids: 限定文档 ID 列表。
            use_graph: 是否启用图谱检索。
            precomputed_embed: 预计算嵌入（来自意图分析与嵌入并行），
                传入时向量检索复用该嵌入，避免重复计算。
            kb_id: 知识库 ID。``None`` 走全局命名空间（向后兼容）。

        Returns:
            tuple: ``(融合后的检索结果列表或 None, 图谱数据字典或 None)``。
            融合结果为向量检索与 BM25 检索的 RRF 融合输出。
        """
        vector_task = self._vector_search(
            retrieval_query, pool_size, doc_ids, precomputed_embed, kb_id
        )
        graph_task = (
            self._graph_search(question, analysis, kb_id) if use_graph else None
        )
        # P2.3: BM25 第三路检索，复用重写后的查询与文档过滤
        # 知识库隔离：BM25 为全局内存索引，KB 查询时跳过（避免跨 KB 泄漏）
        bm25_task = (
            bm25_retriever.search(
                retrieval_query, top_k=pool_size, doc_ids=doc_ids
            )
            if kb_id is None
            else None
        )

        tasks = [vector_task]
        if graph_task is not None:
            tasks.append(graph_task)
        if bm25_task is not None:
            tasks.append(bm25_task)

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
        graph_chunks: list[dict] = []
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
                # P2.4: 提取图谱引导召回的 chunks
                graph_chunks = (graph_data or {}).get("graph_chunks", []) or []

        # 处理 BM25 检索结果（P2.3）
        # BM25 结果索引 = 1（无图谱）或 2（有图谱）；KB 查询跳过 BM25 时为空
        bm25_results: list[dict] = []
        if bm25_task is not None:
            bm25_index = 2 if graph_task is not None else 1
            bm25_result = results[bm25_index]
            if isinstance(bm25_result, Exception):
                logger.warning("BM25 检索失败，跳过 BM25 融合", error=str(bm25_result))
            else:
                bm25_results = bm25_result or []

        # 向量检索失败时直接返回（无融合）
        if vector_results is None:
            return None, graph_data

        # P2.3 + P2.4: 多路 RRF 融合
        # 路径 0: 向量检索（Dense+Sparse 已 RRF 融合）
        # 路径 1: BM25 检索（P2.3）
        # 路径 2: 图谱引导召回（P2.4，可选）
        all_paths: list[list[dict]] = [vector_results]
        if bm25_results:
            all_paths.append(bm25_results)
        if graph_chunks:
            all_paths.append(graph_chunks)

        if len(all_paths) > 1:
            vector_results = self._fuse_multi_path(
                all_paths, top_k=pool_size
            )
            logger.info(
                "多路检索融合完成",
                path_count=len(all_paths),
                vector_count=len(all_paths[0]),
                bm25_count=len(bm25_results),
                graph_chunk_count=len(graph_chunks),
                fused_count=len(vector_results),
            )

        return vector_results, graph_data

    def _fuse_multi_path(
        self,
        result_lists: list[list[dict]],
        top_k: int,
        k: int = 60,
    ) -> list[dict]:
        """RRF 融合多路检索结果（P2.3 + P2.4 通用版本）。

        对任意数量的检索路径做 RRF 融合，等价于多路 RRF。
        以 ``chunk_id`` 作为唯一键进行融合，多路同时命中的文档
        会获得更高的 RRF 累加分数。

        RRF 公式: score(d) = Σ 1/(k + rank_i(d))
        其中 k=60 为标准 RRF 平滑参数。

        P3 优化：对 chunk_type="table" 的表格分块施加 boost 因子（1.5x），
        使数值类查询能优先检索到表格数据，避免被前言描述误导。

        Args:
            result_lists: 多路检索结果列表，每路为 list[dict]，每项需含
                ``chunk_id`` 字段。各路结果应已按相关性降序排列。
            top_k: 返回前 K 条融合结果。
            k: RRF 平滑参数，默认 60。

        Returns:
            list[dict]: 融合后的结果列表，按 RRF 分数降序排列，每项包含：
                - id/chunk_id/text/doc_id/title_chain/metadata: 来自首次命中的实体
                - score: RRF 累加分数
                - rank: 最终排名（从 1 开始）
        """
        # 表格 chunk 的 RRF 分数 boost 因子（P3 优化）
        _TABLE_BOOST: float = 1.5

        # chunk_id -> {"score": float, "entity": dict, "path_ranks": dict, "is_table": bool}
        scores: dict[str, dict] = {}

        for path_idx, results in enumerate(result_lists):
            for rank, hit in enumerate(results):
                chunk_id = hit.get("chunk_id", "")
                if not chunk_id:
                    continue
                rrf_score = 1.0 / (k + rank + 1)
                # 检测表格 chunk（metadata.chunk_type == "table"）
                meta = hit.get("metadata", {}) or {}
                is_table = meta.get("chunk_type") == "table"
                if is_table:
                    rrf_score *= _TABLE_BOOST

                if chunk_id in scores:
                    scores[chunk_id]["score"] += rrf_score
                    scores[chunk_id]["path_ranks"][path_idx] = rank + 1
                else:
                    scores[chunk_id] = {
                        "score": rrf_score,
                        "entity": hit,
                        "path_ranks": {path_idx: rank + 1},
                        "is_table": is_table,
                    }

        # 按 RRF 分数降序排列
        sorted_results = sorted(
            scores.items(), key=lambda x: x[1]["score"], reverse=True
        )

        # 格式化输出，截取 top_k 条
        fused: list[dict] = []
        for rank, (_chunk_id, info) in enumerate(sorted_results[:top_k]):
            entity = info["entity"]
            fused.append(
                {
                    "id": entity.get("id"),
                    "chunk_id": entity.get("chunk_id", ""),
                    "text": entity.get("text", ""),
                    "doc_id": entity.get("doc_id", ""),
                    "title_chain": entity.get("title_chain", ""),
                    "metadata": entity.get("metadata", {}),
                    "score": info["score"],
                    "rank": rank + 1,
                }
            )

        return fused

    # ---------------------------------------------------------------
    # 内部方法：向量检索
    # ---------------------------------------------------------------
    async def _vector_search(
        self,
        query: str,
        pool_size: int,
        doc_ids: list[str] | None,
        precomputed_embed: dict | None = None,
        kb_id: uuid.UUID | None = None,
    ) -> list[dict]:
        """向量检索：嵌入查询 → 混合检索（含 L3 检索结果缓存）。

        L3 缓存策略：embedding 之后，使用查询向量的前 16 维哈希作为键
        检查 L3 缓存，命中时跳过 Milvus 检索；未命中时执行检索并异步回写。

        通过 ``embedding_service.embed_query`` 生成 Dense+Sparse 向量，
        再调用 ``vector_store.hybrid_search`` 执行 RRF 融合检索。

        知识库隔离：``kb_id`` 非 None 时检索 KB 专属 Collection，缓存键带
        KB 前缀；``None`` 时走全局 Collection（向后兼容）。

        Args:
            query: 检索查询文本（重写后的查询）。
            pool_size: 检索候选池大小（重排前数量）。
            doc_ids: 限定文档 ID 列表，``None`` 不限制。
            precomputed_embed: 预计算嵌入结果（来自意图分析与嵌入并行），
                提供时跳过 embed_query 调用以避免重复计算。
            kb_id: 知识库 ID。``None`` 走全局 Collection（向后兼容）。

        Returns:
            list[dict]: 向量检索结果列表（vector_store 原始格式，含
            ``chunk_id``/``text``/``doc_id``/``score``/``metadata`` 等字段）。
        """
        # 嵌入查询：优先复用预计算结果，否则现场嵌入
        if precomputed_embed is not None:
            embed_result = precomputed_embed
        else:
            embed_result = await embedding_service.embed_query(query)
        dense_vec = embed_result["dense_vector"]
        sparse_vec = embed_result["sparse_for_milvus"]

        # L3 检索结果缓存：命中时跳过 Milvus 检索
        cached_retrieval = await rag_cache_service.get_retrieval(
            dense_vec, pool_size, doc_ids, kb_id
        )
        if cached_retrieval is not None:
            results = cached_retrieval.get("results", [])
            logger.info(
                "L3 检索缓存命中，跳过 Milvus 检索",
                query=query[:100],
                cached_count=len(results),
            )
            return results

        # 混合检索（Dense + Sparse + RRF 融合）
        results = await vector_store.hybrid_search(
            query_dense=dense_vec,
            query_sparse=sparse_vec,
            top_k=pool_size,
            kb_id=kb_id,
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

        # 异步回写 L3 检索结果缓存
        try:
            asyncio.create_task(
                rag_cache_service.set_retrieval(
                    dense_vec,
                    {"results": results},
                    pool_size,
                    doc_ids,
                    kb_id,
                )
            )
        except Exception as err:
            logger.debug("L3 缓存回写失败", error=str(err))

        return results

    # ---------------------------------------------------------------
    # 内部方法：知识图谱检索
    # ---------------------------------------------------------------
    async def _graph_search(
        self,
        question: str,
        analysis: QueryAnalysis,
        kb_id: uuid.UUID | None = None,
    ) -> dict | None:
        """知识图谱检索：搜索实体、获取关系子图，并通过图谱实体召回相关文档片段。

        P2.4 优化：除原有实体+关系信息外，新增图谱引导的文档片段召回：
        1. 从用户查询抽取实体
        2. 在 NebulaGraph 中查找实体节点
        3. 对所有 Top-N 实体获取 2 跳子图（原仅首个实体 1 跳，扩展上下文）
        4. 收集子图中的相关实体名称（扩展查询实体集）
        5. 通过 BM25 检索包含相关实体名称的文档片段（图谱引导召回）

        知识库隔离：``kb_id`` 非 None 时检索 KB 专属 graph space；
        图谱引导召回的 BM25 为全局索引，KB 查询时跳过（避免跨 KB 泄漏）。
        6. 返回的 ``graph_chunks`` 将在 ``_parallel_retrieve`` 中与向量+BM25
           结果做 RRF 融合，预期提升召回率 35%

        Args:
            question: 用户原始问题（无实体时作为搜索回退词）。
            analysis: 查询分析结果（提供抽取的实体列表）。

        Returns:
            dict | None: ``{"entities": [...], "relations": [...],
            "graph_chunks": [...]}`` 或 ``None``。
        """
        try:
            # 1. 使用查询分析提取的实体文本作为搜索词
            # P2.4: 同时对原始问题用 jieba 分词，将有意义词汇加入搜索词，
            # 避免实体文本与图谱节点名称不完全匹配时（如"不锈钢材料"vs"不锈钢"）
            # 或查询理解未抽取出实体时找不到节点
            search_terms = [e.text for e in analysis.entities if e.text]

            # P2.4: 对原始问题 jieba 分词，提取长度 >= 2 的有意义词项
            # 这样子串如"不锈钢"能从"不锈钢执行标准是什么"中提取出来匹配节点
            if question:
                try:
                    import jieba
                    question_tokens = [
                        t for t in jieba.cut(question)
                        if len(t.strip()) >= 2 and t.strip() not in search_terms
                    ]
                    search_terms.extend(question_tokens)
                except ImportError:
                    # jieba 不可用时退化为原始问题
                    if question not in search_terms:
                        search_terms.append(question)

            # 2. 对前 8 个搜索词进行节点搜索（P2.4: 扩大搜索范围）
            all_nodes: list[dict] = []
            seen_ids: set = set()
            for term in search_terms[:8]:
                nodes = await graph_store.search_nodes(name=term, limit=5, kb_id=kb_id)
                for node in nodes:
                    node_id = node.get("id")
                    if node_id not in seen_ids:
                        seen_ids.add(node_id)
                        all_nodes.append(node)

            if not all_nodes:
                return {"entities": [], "relations": [], "graph_chunks": []}

            # 3. P2.4: 对所有 Top-N 实体获取 2 跳子图（原仅首个实体 1 跳）
            relations: list[dict] = []
            related_entity_names: set[str] = set()
            seen_edges: set[tuple] = set()
            try:
                for node in all_nodes[:5]:  # 限制最多 5 个实体避免过度查询
                    subgraph = await graph_store.get_subgraph(
                        node["name"], max_hops=2, kb_id=kb_id
                    )
                    # 收集去重的关系
                    for edge in subgraph.get("edges", []):
                        edge_key = (
                            edge.get("source", ""),
                            edge.get("target", ""),
                            edge.get("type", ""),
                        )
                        if edge_key not in seen_edges:
                            seen_edges.add(edge_key)
                            relations.append(edge)
                    # P2.4: 收集子图中的相关实体名称（扩展查询实体集）
                    for n in subgraph.get("nodes", []):
                        name = n.get("name", "")
                        if name and name not in related_entity_names:
                            related_entity_names.add(name)
            except Exception as err:
                logger.warning(
                    "获取子图关系失败，仅使用实体信息", error=str(err)
                )

            # 4. P2.4: 图谱引导召回 - 通过 BM25 检索包含相关实体名称的文档片段
            # 这些 chunks 可能因查询语义距离较远被向量检索漏召，
            # 但通过图谱实体关系可关联召回
            graph_chunks: list[dict] = []
            # 知识库隔离：图谱引导召回依赖全局 BM25 索引，KB 查询时跳过
            if related_entity_names and kb_id is None:
                # 用相关实体名称作为查询，通过 BM25 召回相关文档片段
                entity_query = " ".join(list(related_entity_names)[:20])
                try:
                    graph_chunks = await bm25_retriever.search(
                        entity_query, top_k=10
                    )
                    logger.info(
                        "图谱引导召回完成",
                        entity_count=len(related_entity_names),
                        chunk_count=len(graph_chunks),
                    )
                except Exception as err:
                    logger.warning(
                        "图谱引导召回失败", error=str(err)
                    )

            return {
                "entities": all_nodes,
                "relations": relations,
                "graph_chunks": graph_chunks,
            }
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
        original_question: str = "",
    ) -> tuple[list[dict], int]:
        """对向量检索结果进行重排。

        ``use_reranker=False`` 时直接截取前 ``top_k`` 条原始结果。
        重排失败时降级使用原始结果。

        Args:
            query: 重写后的检索查询（作为 CrossEncoder 输入）。
            vector_results: 向量检索结果列表（vector_store 格式）。
            top_k: 最终返回数量。
            use_reranker: 是否启用重排。
            original_question: 用户原始问题（用于牌号精确匹配加权）。

        Returns:
            tuple: ``(最终文档列表, 重排后数量)``。文档列表中每项为
            统一内部格式（含 ``chunk_id``/``document_id``/``content``/
            ``score``/``metadata``）。
        """
        # 将 vector_store 格式转换为统一内部格式（text→content, doc_id→document_id）
        chunks = [self._convert_vector_result(r) for r in vector_results]

        if not use_reranker or reranker_service is None:
            final = chunks[:top_k]
            if reranker_service is None and use_reranker:
                logger.warning("reranker_service不可用，跳过重排")
            return final, len(final)

        try:
            # P3 优化：扩大 reranker 候选数，确保包含牌号的 chunk 不被提前淘汰
            # reranker top_k 扩大到全部向量检索候选（pool_size），后续通过牌号
            # 加权+表格加权后截取 top_k，避免含目标牌号的表格被 reranker 误淘汰
            rerank_top_k = max(top_k * 3, len(chunks))
            rerank_results = await reranker_service.rerank(
                query=query,
                documents=chunks,
                top_k=rerank_top_k,
            )
            final = [self._convert_rerank_result(r) for r in rerank_results]

            # P3 优化：重排后对表格 chunk 分数加权，确保数值类查询优先使用表格数据
            final = self._boost_table_chunks(final)

            # P3 优化：牌号精确匹配加权，确保包含查询牌号的 chunk 进入最终 top_k
            final = self._boost_exact_match_chunks(final, original_question)

            # P3 优化：强制注入含查询牌号的 chunk（防止 reranker 低估表格导致遗漏）
            final = self._ensure_grade_chunks(final, original_question, top_k)

            # 截取最终 top_k
            final = final[:top_k]

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

    @staticmethod
    def _boost_table_chunks(
        chunks: list[dict],
        boost: float = 1.5,
    ) -> list[dict]:
        """对表格 chunk 的重排分数加权并重新排序（P3 优化）。

        重排模型（CrossEncoder）对自然语言前言片段的打分通常高于
        结构化表格数据，导致数值类查询时前言片段排在表格前面，LLM
        被前言中的描述性数值误导。本方法对 chunk_type="table" 的
        结果分数乘以 boost 因子后重新排序，使表格数据在上下文中
        优先展示。

        Args:
            chunks: 重排后的 chunk 列表（内部格式，含 score/metadata）。
            boost: 表格 chunk 的分数 boost 因子，默认 1.5。

        Returns:
            list[dict]: 重新排序后的 chunk 列表。
        """
        if not chunks:
            return chunks

        table_count = 0
        for chunk in chunks:
            meta = chunk.get("metadata", {}) or {}
            if meta.get("chunk_type") == "table":
                chunk["score"] = chunk.get("score", 0.0) * boost
                table_count += 1

        if table_count > 0:
            chunks.sort(key=lambda x: x.get("score", 0.0), reverse=True)
            logger.info(
                "表格 chunk 加权完成",
                table_count=table_count,
                boost=boost,
            )
        return chunks

    @staticmethod
    def _boost_exact_match_chunks(
        chunks: list[dict],
        query: str,
        boost_per_grade: float = 2.0,
    ) -> list[dict]:
        """对包含查询中牌号的 chunk 做精确匹配加权（P3 优化）。

        向量检索和重排模型对牌号（如 06Cr19Ni10N）的语义匹配不够精确，
        可能将含目标牌号的表格排在 top_k 之外。本方法从查询中提取牌号
        模式（如 12Cr18Ni9、06Cr19Ni10N、022Cr19Ni10），对文本包含
        该牌号的 chunk 分数做指数加权（每匹配一个牌号 ×boost_per_grade），
        确保含目标牌号的 chunk 进入最终 top_k。

        对同时包含多个查询牌号的 chunk（如对比类查询涉及两个牌号），
        会累乘 boost，使其排名高于只含一个牌号的 chunk。

        **属性匹配额外加权**：当查询包含数值属性关键词（如 Rp0.2、屈服、
        抗拉、热处理等）时，对同时包含牌号和该属性列的表格 chunk 额外
        加权（×1.5 per attribute），避免牌号出现在"特性用途"等无关表格
        中误导排序。

        Args:
            chunks: 重排后的 chunk 列表（内部格式，含 content/score）。
            query: 用户原始查询（用于提取牌号）。
            boost_per_grade: 每匹配一个牌号的 boost 因子，默认 2.0。

        Returns:
            list[dict]: 重新排序后的 chunk 列表。
        """
        if not chunks or not query:
            return chunks

        # 从查询中提取牌号：数字+Cr+数字+(可选字母/数字)
        grades: list[str] = re.findall(r"\d+Cr\d+[A-Za-z0-9]*", query)
        if not grades:
            return chunks

        # 去重
        grades = list(dict.fromkeys(grades))

        # 从查询中提取数值属性关键词，用于区分"特性用途表"和"力学性能表"
        # 当查询问 Rp0.2/屈服/抗拉 时，应优先返回含这些列的表格
        attribute_keywords: list[str] = [
            "Rp0.2", "Rp0.2b", "Rp.2", "Rp.2b", "Rp2b", "Rp2",
            "规定非比例延伸", "屈服", "抗拉", "伸长率", "断面收缩",
            "硬度", "力学性能",
            "热处理", "退火", "淬火", "回火", "固溶",
            "化学成分", "碳", "硅", "锰", "磷", "硫", "铬", "镍", "钼",
            "旧牌号", "新牌号", "统一数字代号",
        ]
        query_attrs: list[str] = [
            kw for kw in attribute_keywords if kw in query
        ]

        match_count = 0
        for chunk in chunks:
            content = chunk.get("content", "") or ""
            # 统计 chunk 包含多少个查询牌号
            matched_grades = [g for g in grades if g in content]
            if not matched_grades:
                continue

            # 每匹配一个牌号，乘以一次 boost（累乘）
            boost = boost_per_grade ** len(matched_grades)

            # 属性匹配额外加权：chunk 同时包含牌号和查询属性关键词时
            # 额外 ×1.5 per attribute，避免牌号在"特性用途表"中误导排序
            if query_attrs:
                matched_attrs = [a for a in query_attrs if a in content]
                if matched_attrs:
                    boost *= 1.5 ** len(matched_attrs)

            chunk["score"] = chunk.get("score", 0.0) * boost
            match_count += 1

        if match_count > 0:
            chunks.sort(key=lambda x: x.get("score", 0.0), reverse=True)
            logger.info(
                "牌号精确匹配加权完成",
                grades=grades,
                query_attrs=query_attrs,
                match_count=match_count,
            )
        return chunks

    @staticmethod
    def _ensure_grade_chunks(
        chunks: list[dict],
        query: str,
        top_k: int,
    ) -> list[dict]:
        """强制注入含查询牌号的 chunk（P3 优化）。

        当 reranker 对表格数据打分偏低时，含目标牌号的力学性能表格可能
        被排在 top_k 之外，导致 LLM 无法提取数值。本方法检查 top_k 结果
        中是否包含含查询牌号 **且含查询属性** 的表格 chunk，若缺失则从
        全部候选中找到含牌号+属性的表格 chunk，强制注入到 top_k 前列。

        策略：
        1. 从查询提取牌号和属性关键词
        2. 检查 chunks[:top_k] 中是否已有"含牌号+含属性"的表格 chunk
        3. 若有，直接返回（已满足）
        4. 若无，从 chunks[top_k:] 中查找"含牌号+含属性"的表格 chunk
        5. 找到后，将其分数设为 top_k 内的最高分+0.1，注入到前列

        Args:
            chunks: 已加权排序的 chunk 列表。
            query: 用户原始查询（用于提取牌号）。
            top_k: 最终返回数量。

        Returns:
            list[dict]: 可能注入了含牌号 chunk 的列表。
        """
        if not chunks or not query or len(chunks) <= top_k:
            return chunks

        # 从查询中提取牌号
        grades: list[str] = re.findall(r"\d+Cr\d+[A-Za-z0-9]*", query)
        if not grades:
            return chunks
        grades = list(dict.fromkeys(grades))

        # 从查询中提取属性关键词
        attribute_keywords: list[str] = [
            "Rp0.2", "Rp0.2b", "Rp.2", "Rp.2b", "Rp2b", "Rp2",
            "规定非比例延伸", "屈服", "抗拉", "伸长率", "断面收缩",
            "硬度", "力学性能",
            "热处理", "退火", "淬火", "回火", "固溶",
            "化学成分", "旧牌号", "新牌号", "统一数字代号",
        ]
        query_attrs: list[str] = [
            kw for kw in attribute_keywords if kw in query
        ]

        def _has_grade_attr_table(chunk_list: list[dict]) -> bool:
            """检查列表中是否有含牌号+含属性的表格 chunk。"""
            for c in chunk_list:
                meta = c.get("metadata", {}) or {}
                if meta.get("chunk_type") != "table":
                    continue
                content = c.get("content", "") or ""
                has_grade = any(g in content for g in grades)
                if not has_grade:
                    continue
                # 若查询无属性关键词，只要有牌号表格即可
                if not query_attrs:
                    return True
                # 若查询有属性关键词，要求 chunk 含至少一个属性
                if any(a in content for a in query_attrs):
                    return True
            return False

        # 检查 top_k 内是否已有"含牌号+含属性"的表格 chunk
        top_k_chunks = chunks[:top_k]
        if _has_grade_attr_table(top_k_chunks):
            return chunks  # 已满足，无需注入

        # 从 top_k 之外查找"含牌号+含属性"的表格 chunk
        # 优先查找同时包含多个查询牌号 + 属性的 chunk
        candidates: list[tuple[int, int, int, dict]] = []  # (grade_count, attr_count, content_len, chunk)
        for chunk in chunks[top_k:]:
            content = chunk.get("content", "") or ""
            meta = chunk.get("metadata", {}) or {}
            if meta.get("chunk_type") != "table":
                continue
            matched_grades = [g for g in grades if g in content]
            if not matched_grades:
                continue
            matched_attrs = [a for a in query_attrs if a in content] if query_attrs else [1]
            if query_attrs and not matched_attrs:
                continue  # 查询有属性但 chunk 不含属性，跳过
            candidates.append(
                (len(matched_grades), len(matched_attrs), len(content), chunk)
            )

        if not candidates:
            return chunks  # 没有可注入的候选

        # 按（牌号数, 属性数, 内容长度）降序排序，选最佳候选
        candidates.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
        best_chunk = candidates[0][3]

        # 将最佳候选的分数设为 top_k 内最高分 + 0.1，注入到第1位
        max_score = max((c.get("score", 0.0) for c in top_k_chunks), default=0.0)
        best_chunk["score"] = max_score + 0.1

        # 移除原列表中的 best_chunk，插入到第1位
        chunks = [c for c in chunks if c is not best_chunk]
        chunks.insert(0, best_chunk)

        logger.info(
            "强制注入含牌号+属性表格 chunk",
            grades=grades,
            query_attrs=query_attrs,
            injected_chunk_id=best_chunk.get("chunk_id", ""),
            grade_count=candidates[0][0],
            attr_count=candidates[0][1],
        )
        return chunks

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
    # 简单事实查询关键词，命中时使用轻量模型（gemma2:2b）降低延迟
    _SIMPLE_QUERY_KEYWORDS: list[str] = [
        "是什么", "多少", "哪个", "哪些", "定义", "含义",
        "什么是", "解释", "说明", "列举",
    ]

    # 需要从表格精确提取数值的复杂查询关键词，命中时使用大模型
    # 包含牌号或这些关键词的查询需要更强的表格理解能力
    _TABLE_EXTRACTION_KEYWORDS: list[str] = [
        "Rp0.2", "Rp0.2b", "Rp.2", "Rp.2b", "规定非比例延伸",
        "屈服", "抗拉", "伸长率", "断面收缩", "硬度",
        "化学成分", "热处理", "退火", "淬火", "回火", "固溶",
        "旧牌号", "新牌号", "统一数字代号", "牌号对照",
        "力学性能", "工艺性能",
    ]

    # 牌号模式：数字+Cr（如12Cr、06Cr、022Cr）或元素符号组合
    _GRADE_PATTERN: re.Pattern[str] = re.compile(r"\d+Cr\d+", re.IGNORECASE)

    def _should_use_light_model(self, intent: str, question: str) -> bool:
        """判断是否应使用轻量模型（LLM 路由）。

        仅对 general/document_search 意图且包含简单事实查询关键词时
        启用轻量模型。summarization/comparison 等复杂意图使用大模型。

        **例外**：当查询包含牌号（如12Cr18Ni9）或需要从表格提取数值的
        关键词（如Rp0.2、屈服强度、热处理、旧牌号等）时，必须使用大模型，
        因为轻量模型（gemma4:12b）无法可靠地从表格行中提取具体数值。

        Args:
            intent: 查询意图。
            question: 用户原始问题。

        Returns:
            bool: True 表示使用轻量模型。
        """
        if intent in ("summarization", "comparison"):
            return False
        # 包含牌号或表格数值提取关键词时，使用大模型
        if self._GRADE_PATTERN.search(question):
            return False
        if any(kw in question for kw in self._TABLE_EXTRACTION_KEYWORDS):
            return False
        return any(kw in question for kw in self._SIMPLE_QUERY_KEYWORDS)

    async def _generate(self, context: str, intent: str = "", question: str = "") -> str:
        """调用 LLM 生成回答（支持 LLM 路由与意图模板）。

        根据 intent 和 question 判断是否使用轻量模型，降低简单查询的延迟。
        根据意图拼接对应的答案结构化模板到系统提示词，引导输出格式。
        生成失败时返回包含错误信息的兜底回答，不抛出异常。

        Args:
            context: 组装好的上下文字符串。
            intent: 查询意图（用于 LLM 路由与模板选择）。
            question: 用户原始问题（用于 LLM 路由）。

        Returns:
            str: LLM 生成的回答文本。
        """
        try:
            model_override = None
            if self._should_use_light_model(intent, question):
                model_override = settings.LLM_LIGHT_MODEL
                logger.info("LLM 路由：使用轻量模型", model=model_override)

            # 根据意图拼接答案结构化模板
            template_suffix = _INTENT_ANSWER_TEMPLATES.get(intent, "")
            system_prompt = _SYSTEM_PROMPT + template_suffix if template_suffix else _SYSTEM_PROMPT

            answer = await llm_service.generate(
                prompt=context,
                system_prompt=system_prompt,
                model_override=model_override,
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

    # ---------------------------------------------------------------
    # 内部方法：缓存序列化
    # ---------------------------------------------------------------
    @staticmethod
    def _response_to_dict(response: RAGResponse) -> dict[str, Any]:
        """将 RAGResponse 序列化为可缓存字典。

        Args:
            response: RAGResponse 对象。

        Returns:
            dict: 包含 answer/intent/entities/citations 等字段的字典。
        """
        return {
            "answer": response.answer,
            "intent": response.intent,
            "entities": response.entities,
            "citations": [
                {
                    "document_id": c.document_id,
                    "chunk_id": c.chunk_id,
                    "content": c.content,
                    "score": c.score,
                    "source": c.source,
                }
                for c in response.citations
            ],
            "query_analysis": response.query_analysis,
            "retrieval_count": response.retrieval_count,
            "rerank_count": response.rerank_count,
        }

    @staticmethod
    def _dict_to_response(data: dict[str, Any]) -> RAGResponse:
        """将缓存字典反序列化为 RAGResponse 对象。

        Args:
            data: 缓存字典。

        Returns:
            RAGResponse: 反序列化后的响应对象。
        """
        return RAGResponse(
            answer=data.get("answer", ""),
            intent=data.get("intent", "general"),
            entities=data.get("entities", []),
            citations=[
                Citation(
                    document_id=c.get("document_id", ""),
                    chunk_id=c.get("chunk_id", ""),
                    content=c.get("content", ""),
                    score=c.get("score", 0.0),
                    source=c.get("source", "vector"),
                )
                for c in data.get("citations", [])
            ],
            query_analysis=data.get("query_analysis", {}),
            retrieval_count=data.get("retrieval_count", 0),
            rerank_count=data.get("rerank_count", 0),
        )

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
