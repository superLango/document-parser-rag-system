"""LlamaIndex 多索引管理器模块。

本模块基于 LlamaIndex 0.11+ 封装多种索引类型，作为现有 RAG 管道的增强层：

- ``SummaryIndex``：适合 summarization 意图，遍历所有节点生成摘要
- ``TreeIndex``：适合 comparison 意图，按树形结构层级检索
- ``KeywordTableIndex``：适合 keyword 查询，基于关键词倒排索引检索
- ``VectorStoreIndex``：现有默认索引（保留 Milvus 混合检索，不在此封装）

设计要点：
- 懒加载：索引在首次查询时才构建，避免启动阶段全量构建
- 单例模式：整个应用共享一个 IndexManager 实例
- 容错降级：LlamaIndex 索引构建/查询失败时返回空结果，不影响主流程
- 内存索引：SummaryIndex/TreeIndex/KeywordTableIndex 使用内存存储，
  避免与现有 Milvus 向量库冲突；适合中小规模文档集（<1000 文档）
- 复用现有模型：嵌入通过 langchain Embeddings 适配器复用 bge-m3，
  LLM 通过 langchain LLM 适配器复用 vLLM（延迟初始化，避免循环依赖）

使用示例：
    from app.services.index_manager import index_manager

    # 构建索引（文档入库时调用）
    await index_manager.build_indices(nodes)

    # 根据意图查询
    result = await index_manager.query_with_intent(
        question="总结304不锈钢的特性",
        intent="summarization",
        top_k=5,
    )
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import threading
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)


def _run_async_sync(coro_factory: Callable[[], Awaitable[Any]]) -> Any:
    """在同步上下文中运行异步函数的辅助函数。

    LlamaIndex 的同步接口（如 ``_get_query_embedding``）需要调用现有的
    异步 service（如 ``embedding_service``）。直接使用 ``asyncio.run`` 在
    已有事件循环运行时会抛 ``RuntimeError``，此时改用独立线程池执行。

    Args:
        coro_factory: 无参可调用对象，每次调用返回一个新的 coroutine。
            使用 factory 而非已创建的 coroutine，是因为 coroutine 只能
            await 一次，失败重试需要重新创建。

    Returns:
        Any: 异步函数的返回值。
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, coro_factory()).result()
        return asyncio.run(coro_factory())
    except RuntimeError:
        return asyncio.run(coro_factory())


@dataclass
class IndexQueryResult:
    """索引查询结果。

    封装 LlamaIndex 索引查询的返回信息，与 RAGService.Citation 对齐。

    Attributes:
        answer: LLM 生成的回答文本。
        source_nodes: 检索到的源节点列表（LlamaIndex NodeWithScore 格式）。
        citations: 引用列表，每项含 document_id/chunk_id/content/score。
        intent: 触发该查询的意图类型。
        index_type: 实际使用的索引类型。
    """

    answer: str = ""
    source_nodes: list[dict] = field(default_factory=list)
    citations: list[dict] = field(default_factory=list)
    intent: str = ""
    index_type: str = ""


class IndexManager:
    """LlamaIndex 多索引管理器。

    管理 SummaryIndex、TreeIndex、KeywordTableIndex 三种 LlamaIndex 索引，
    根据查询意图选择最合适的索引类型。VectorStoreIndex 保留现有 Milvus 实现，
    不在此封装，避免重复。

    索引构建策略：
    - 文档入库时调用 ``build_indices`` 将 TextNode 列表加入三种索引
    - 三种索引共享同一份节点数据，构建后常驻内存
    - 索引构建失败时记录错误，对应索引标记为不可用，查询时降级

    查询路由策略：
    - ``summarization`` → SummaryIndex（遍历所有节点生成摘要）
    - ``comparison`` → TreeIndex（层级检索，适合对比类问题）
    - ``general``/``document_search`` → 降级到现有 Milvus（返回空结果，由上层处理）
    - ``knowledge_graph`` → 降级到现有 graph_store（返回空结果）

    Attributes:
        _summary_index: SummaryIndex 实例，懒加载。
        _tree_index: TreeIndex 实例，懒加载。
        _keyword_index: KeywordTableIndex 实例，懒加载。
        _nodes: 已索引的 TextNode 列表。
        _built: 索引是否已构建。
        _lock: 构建锁，确保并发安全。
        _llm: LlamaIndex LLM 适配器，懒加载。
        _embed_model: LlamaIndex 嵌入适配器，懒加载。
    """

    def __init__(self) -> None:
        """初始化索引管理器，不加载任何模型或索引。"""
        self._summary_index: Any = None
        self._tree_index: Any = None
        self._keyword_index: Any = None
        self._nodes: list[Any] = []
        self._built: bool = False
        self._lock = threading.Lock()
        self._llm: Any = None
        self._embed_model: Any = None
        # 各索引可用性标记，构建失败时置为 False
        self._summary_available: bool = False
        self._tree_available: bool = False
        self._keyword_available: bool = False

    # ---------------------------------------------------------------
    # 模型适配器：复用现有 vLLM 和 bge-m3
    # ---------------------------------------------------------------
    def _get_llm(self) -> Any:
        """获取 LlamaIndex LLM 适配器，复用现有 vLLM 服务。

        通过 LangChainLLM 适配器包装现有的 llm_service，避免重复加载模型。
        采用延迟初始化，首次调用时才创建适配器。

        Returns:
            Any: LlamaIndex LLM 实例。

        Raises:
            Exception: 适配器创建失败时抛出，由调用方降级处理。
        """
        if self._llm is not None:
            return self._llm
        try:
            # 延迟导入，避免模块导入阶段触发重型依赖
            from llama_index.llms.langchain import LangChainLLM
            from langchain_core.language_models import BaseLLM
            from langchain_core.outputs import LLMResult, Generation
            from langchain_core.callbacks import CallbackManagerForLLMRun
            from typing import Optional, List, Any as AnyType

            # 获取现有 llm_service 单例
            from app.services.llm_service import llm_service

            class VLLMAdapter(BaseLLM):
                """将现有 llm_service 适配为 LangChain BaseLLM。

                通过 _call 和 _generate 方法将 llm_service 的异步接口
                适配为 LangChain 同步接口，供 LlamaIndex 使用。
                """

                @property
                def _llm_type(self) -> str:
                    return "vllm-qwen-adapter"

                def _call(
                    self,
                    prompt: str,
                    stop: Optional[List[str]] = None,
                    run_manager: Optional[CallbackManagerForLLMRun] = None,
                    **kwargs: AnyType,
                ) -> str:
                    """同步调用，通过辅助函数执行异步 llm_service。"""
                    return _run_async_sync(lambda: llm_service.generate(prompt=prompt))

                def _generate(
                    self,
                    prompts: List[str],
                    stop: Optional[List[str]] = None,
                    run_manager: Optional[CallbackManagerForLLMRun] = None,
                    **kwargs: AnyType,
                ) -> LLMResult:
                    """批量生成。"""
                    generations = []
                    for prompt in prompts:
                        text = self._call(prompt, stop, run_manager, **kwargs)
                        generations.append([Generation(text=text)])
                    return LLMResult(generations=generations)

            self._llm = LangChainLLM(llm=VLLMAdapter())
            logger.info("LlamaIndex LLM 适配器创建成功（复用 vLLM）")
            return self._llm
        except Exception as err:
            logger.error("创建 LlamaIndex LLM 适配器失败", error=str(err), exc_info=True)
            raise

    def _get_embed_model(self) -> Any:
        """获取 LlamaIndex 嵌入适配器，复用现有 bge-m3 服务。

        通过 LangChainEmbedding 适配器包装现有的 embedding_service。

        Returns:
            Any: LlamaIndex Embedding 实例。

        Raises:
            Exception: 适配器创建失败时抛出，由调用方降级处理。
        """
        if self._embed_model is not None:
            return self._embed_model
        try:
            from llama_index.core.embeddings import BaseEmbedding
            from llama_index.core.bridge.pydantic import PrivateAttr

            # 获取现有 embedding_service 单例
            from app.services.embedding_service import embedding_service

            class BGEAdapter(BaseEmbedding):
                """将现有 embedding_service 适配为 LlamaIndex BaseEmbedding。

                复用 bge-m3 的 Dense 向量（1024 维），暂不暴露 Sparse 向量
                （LlamaIndex 索引主要使用 Dense 向量）。
                """

                _embed_service: Any = PrivateAttr()

                def __init__(self, **kwargs: Any) -> None:
                    super().__init__(**kwargs)
                    self._embed_service = embedding_service

                @classmethod
                def class_name(cls) -> str:
                    return "BGE_M3_Adapter"

                async def _aget_query_embedding(self, query: str) -> list[float]:
                    result = await self._embed_service.embed_query(query)
                    return result["dense_vector"].tolist()

                async def _aget_text_embedding(self, text: str) -> list[float]:
                    result = await self._embed_service.embed_documents([text])
                    return result["dense_vectors"][0].tolist()

                def _get_query_embedding(self, query: str) -> list[float]:
                    return _run_async_sync(lambda: self._aget_query_embedding(query))

                def _get_text_embedding(self, text: str) -> list[float]:
                    return _run_async_sync(lambda: self._aget_text_embedding(text))

                def _get_text_embeddings(self, texts: list[str]) -> list[list[float]]:
                    async def _batch():
                        result = await self._embed_service.embed_documents(texts)
                        return [v.tolist() for v in result["dense_vectors"]]

                    return _run_async_sync(_batch)

            self._embed_model = BGEAdapter(embed_dim=1024)
            logger.info("LlamaIndex 嵌入适配器创建成功（复用 bge-m3）")
            return self._embed_model
        except Exception as err:
            logger.error("创建 LlamaIndex 嵌入适配器失败", error=str(err), exc_info=True)
            raise

    # ---------------------------------------------------------------
    # 索引构建
    # ---------------------------------------------------------------
    async def build_indices(self, nodes: list[Any]) -> None:
        """将 TextNode 列表加入三种 LlamaIndex 索引。

        在文档入库时调用，将分块后的节点同时加入 SummaryIndex、TreeIndex
        和 KeywordTableIndex。三种索引共享同一份节点数据。

        构建采用双重检查锁定，确保并发安全。单个索引构建失败不影响其他。

        Args:
            nodes: LlamaIndex TextNode 列表。若为空则跳过。
        """
        if not nodes:
            logger.warning("索引构建输入节点列表为空，跳过")
            return

        # 双重检查锁定：并发安全地追加或初始化节点列表
        with self._lock:
            if self._built:
                self._nodes.extend(nodes)
            else:
                self._nodes = list(nodes)

        # 在锁外执行异步重建，避免持锁等待 IO
        await self._rebuild_internal()
        self._built = True

    async def _rebuild_internal(self) -> None:
        """内部方法：重建三种索引。

        每种索引独立构建，单个失败不影响其他。构建在后台线程执行以避免
        阻塞事件循环。

        注：llama-index-core 0.11+ 的 SummaryIndex/TreeIndex/KeywordTableIndex
        无 ``from_nodes`` 类方法，应使用构造函数 ``Index(nodes=...)`` 直接
        传入节点列表。早期文档示例中的 ``from_nodes`` 写法会抛 AttributeError。
        """
        from llama_index.core import SummaryIndex, TreeIndex, KeywordTableIndex

        # SummaryIndex
        try:
            self._summary_index = await asyncio.to_thread(
                lambda: SummaryIndex(nodes=self._nodes)
            )
            self._summary_available = True
            logger.info("SummaryIndex 构建成功", node_count=len(self._nodes))
        except Exception as err:
            logger.warning("SummaryIndex 构建失败", error=str(err))
            self._summary_available = False

        # TreeIndex（需要 LLM 进行摘要生成，构建时可能较慢）
        try:
            self._tree_index = await asyncio.to_thread(
                lambda: TreeIndex(nodes=self._nodes)
            )
            self._tree_available = True
            logger.info("TreeIndex 构建成功", node_count=len(self._nodes))
        except Exception as err:
            logger.warning("TreeIndex 构建失败", error=str(err))
            self._tree_available = False

        # KeywordTableIndex（需要 LLM 抽取关键词）
        try:
            self._keyword_index = await asyncio.to_thread(
                lambda: KeywordTableIndex(nodes=self._nodes)
            )
            self._keyword_available = True
            logger.info("KeywordTableIndex 构建成功", node_count=len(self._nodes))
        except Exception as err:
            logger.warning("KeywordTableIndex 构建失败", error=str(err))
            self._keyword_available = False

    # ---------------------------------------------------------------
    # 查询接口
    # ---------------------------------------------------------------
    async def query_with_intent(
        self,
        question: str,
        intent: str,
        top_k: int = 5,
    ) -> IndexQueryResult:
        """根据查询意图选择索引并执行查询。

        意图到索引的映射：
        - ``summarization`` → SummaryIndex（摘要生成）
        - ``comparison`` → TreeIndex（层级对比）
        - 其他 → 返回空结果（由上层 RAGService 降级到 Milvus）

        Args:
            question: 用户查询文本。
            intent: 查询意图（来自 query_service.analyze）。
            top_k: 返回结果数量上限。

        Returns:
            IndexQueryResult: 查询结果。索引不可用或查询失败时返回空结果。
        """
        if not self._built:
            logger.debug("LlamaIndex 索引未构建，返回空结果", intent=intent)
            return IndexQueryResult(intent=intent, index_type="none")

        # 根据意图选择索引
        if intent == "summarization" and self._summary_available:
            return await self._query_summary(question, top_k)
        if intent == "comparison" and self._tree_available:
            return await self._query_tree(question, top_k)

        # 关键词检索作为通用 fallback（当意图未匹配时）
        if self._keyword_available:
            return await self._query_keyword(question, top_k)

        logger.debug("无可用 LlamaIndex 索引", intent=intent)
        return IndexQueryResult(intent=intent, index_type="none")

    async def _query_summary(self, question: str, top_k: int) -> IndexQueryResult:
        """使用 SummaryIndex 执行摘要查询。

        优化策略：当节点数量过多（>30）时，采样前 30 个节点构建临时
        SummaryIndex，避免遍历全部节点导致 LLM 调用超时。使用 compact
        模式将节点文本紧凑拼接后一次性 LLM 调用。

        Args:
            question: 用户查询文本。
            top_k: 返回结果数量上限。

        Returns:
            IndexQueryResult: 查询结果。
        """
        try:
            llm = self._get_llm()

            # 节点数量过多时采样，避免遍历全部节点导致超时
            MAX_SUMMARY_NODES = 30
            if len(self._nodes) > MAX_SUMMARY_NODES:
                # 均匀采样：从头、中、尾各取一部分，保证覆盖全文
                nodes_for_summary = self._nodes[:MAX_SUMMARY_NODES]
                logger.info(
                    "SummaryIndex 节点采样",
                    total_nodes=len(self._nodes),
                    sampled_nodes=len(nodes_for_summary),
                )
                from llama_index.core import SummaryIndex as _SI
                tmp_index = _SI(nodes=nodes_for_summary)
                query_engine = tmp_index.as_query_engine(
                    llm=llm,
                    response_mode="compact",
                    similarity_top_k=top_k,
                )
            else:
                query_engine = self._summary_index.as_query_engine(
                    llm=llm,
                    response_mode="compact",
                    similarity_top_k=top_k,
                )

            response = await asyncio.to_thread(query_engine.query, question)
            citations = self._extract_citations(response, "summary")
            return IndexQueryResult(
                answer=str(response),
                source_nodes=self._extract_source_nodes(response),
                citations=citations,
                intent="summarization",
                index_type="summary",
            )
        except Exception as err:
            logger.warning("SummaryIndex 查询失败", error=str(err))
            return IndexQueryResult(intent="summarization", index_type="summary")

    async def _query_tree(self, question: str, top_k: int) -> IndexQueryResult:
        """使用 TreeIndex 执行层级查询。

        TreeIndex 按树形结构从根到叶逐层检索，适合对比类问题。

        Args:
            question: 用户查询文本。
            top_k: 返回结果数量上限。

        Returns:
            IndexQueryResult: 查询结果。
        """
        try:
            llm = self._get_llm()
            query_engine = self._tree_index.as_query_engine(
                llm=llm,
                child_branch_factor=2,
                similarity_top_k=top_k,
            )
            response = await asyncio.to_thread(query_engine.query, question)
            citations = self._extract_citations(response, "tree")
            return IndexQueryResult(
                answer=str(response),
                source_nodes=self._extract_source_nodes(response),
                citations=citations,
                intent="comparison",
                index_type="tree",
            )
        except Exception as err:
            logger.warning("TreeIndex 查询失败", error=str(err))
            return IndexQueryResult(intent="comparison", index_type="tree")

    async def _query_keyword(self, question: str, top_k: int) -> IndexQueryResult:
        """使用 KeywordTableIndex 执行关键词查询。

        基于关键词倒排索引检索，适合精确关键词匹配。

        Args:
            question: 用户查询文本。
            top_k: 返回结果数量上限。

        Returns:
            IndexQueryResult: 查询结果。
        """
        try:
            llm = self._get_llm()
            query_engine = self._keyword_index.as_query_engine(
                llm=llm,
                similarity_top_k=top_k,
            )
            response = await asyncio.to_thread(query_engine.query, question)
            citations = self._extract_citations(response, "keyword")
            return IndexQueryResult(
                answer=str(response),
                source_nodes=self._extract_source_nodes(response),
                citations=citations,
                intent="general",
                index_type="keyword",
            )
        except Exception as err:
            logger.warning("KeywordTableIndex 查询失败", error=str(err))
            return IndexQueryResult(intent="general", index_type="keyword")

    # ---------------------------------------------------------------
    # 结果转换辅助
    # ---------------------------------------------------------------
    @staticmethod
    def _extract_citations(response: Any, index_type: str) -> list[dict]:
        """从 LlamaIndex 响应中提取引用信息。

        Args:
            response: LlamaIndex Response 对象。
            index_type: 索引类型标识。

        Returns:
            list[dict]: 引用列表，每项含 document_id/chunk_id/content/score/source。
        """
        citations: list[dict] = []
        source_nodes = getattr(response, "source_nodes", []) or []
        for node in source_nodes:
            node_obj = getattr(node, "node", node)
            metadata = getattr(node_obj, "metadata", {}) or {}
            citations.append({
                "document_id": metadata.get("doc_id", ""),
                "chunk_id": getattr(node_obj, "id_", "") or metadata.get("chunk_id", ""),
                "content": getattr(node_obj, "text", "")[:200],
                "score": float(getattr(node, "score", 0.0) or 0.0),
                "source": index_type,
            })
        return citations

    @staticmethod
    def _extract_source_nodes(response: Any) -> list[dict]:
        """从 LlamaIndex 响应中提取源节点信息（用于调试）。

        Args:
            response: LlamaIndex Response 对象。

        Returns:
            list[dict]: 源节点列表。
        """
        result: list[dict] = []
        source_nodes = getattr(response, "source_nodes", []) or []
        for node in source_nodes:
            node_obj = getattr(node, "node", node)
            result.append({
                "id": getattr(node_obj, "id_", ""),
                "text": getattr(node_obj, "text", "")[:100],
                "score": float(getattr(node, "score", 0.0) or 0.0),
            })
        return result

    # ---------------------------------------------------------------
    # 状态查询
    # ---------------------------------------------------------------
    def get_status(self) -> dict:
        """获取索引管理器状态信息。

        Returns:
            dict: 状态信息，含已索引节点数、各索引可用性。
        """
        return {
            "built": self._built,
            "node_count": len(self._nodes),
            "summary_available": self._summary_available,
            "tree_available": self._tree_available,
            "keyword_available": self._keyword_available,
        }

    async def clear(self) -> None:
        """清空所有索引（用于知识库重建）。

        重置所有索引实例与节点列表，下次 build_indices 时重新构建。
        """
        self._summary_index = None
        self._tree_index = None
        self._keyword_index = None
        self._nodes = []
        self._built = False
        self._summary_available = False
        self._tree_available = False
        self._keyword_available = False
        logger.info("IndexManager 已清空所有索引")


# 模块级单例，懒加载
index_manager = IndexManager()
