"""bge-reranker-v2-m3 CrossEncoder 重排服务模块。

本模块基于 BAAI/bge-reranker-v2-m3 模型对向量检索召回的候选文档进行二次重排，
通过 CrossEncoder 计算 (query, document) 文本对的相关性分数，按分数降序返回 top_k 结果。

按方案 8.3 节实现关键约束：
- 使用 sentence_transformers.CrossEncoder 加载 bge-reranker-v2-m3
- max_length=512 限制输入对长度，防止显存溢出
- 懒加载 + 线程锁，确保模型仅加载一次且线程安全
- 通过 asyncio.to_thread 将同步 predict 调用包装为非阻塞异步接口
- 批量 predict 提升吞吐，batch_size 可配置
- 模型加载失败时优雅降级：记录错误日志并按原始顺序返回文档

使用示例：
    from app.services.reranker_service import reranker_service

    # 候选文档来自 vector_store.hybrid_search，每个 dict 形如：
    # {"chunk_id": ..., "document_id": ..., "content": ..., "score": ..., "metadata": ...}
    results = await reranker_service.rerank(
        query="采购技术规范",
        documents=candidates,
        top_k=5,
        batch_size=4,
    )
    # results 为 list[RerankResult]，按 rerank_score 降序排列
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field
from typing import Any

from sentence_transformers import CrossEncoder

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class RerankResult:
    """重排结果项。

    封装一条候选文档经 CrossEncoder 重排后的完整信息，
    同时保留原始检索分数以便对比与调试。

    Attributes:
        chunk_id: 分块唯一标识，沿用输入 documents 中的 chunk_id。
        document_id: 所属文档 ID。
        content: 分块原文。
        original_score: 向量检索阶段给出的原始分数（RRF 等）。
        rerank_score: CrossEncoder 计算得到的相关性分数。
        rank: 本次重排后的最终排名（从 1 开始）。
        metadata: 扩展元信息（页码、坐标等）。
    """

    chunk_id: str
    document_id: str
    content: str
    original_score: float
    rerank_score: float
    rank: int
    metadata: dict = field(default_factory=dict)


class RerankerService:
    """bge-reranker-v2-m3 CrossEncoder 重排服务。

    采用懒加载策略：模块导入与构造时不加载模型，首次调用 ``rerank``
    时才加载 CrossEncoder 实例，避免无 GPU 环境下导入即失败。
    通过 ``threading.Lock`` 保证多线程并发首次调用时模型只加载一次。

    模型加载失败时进入优雅降级：``_loaded`` 保持 False，``rerank``
    会跳过推理直接按原始顺序返回候选文档，确保上层 RAG 链路可用。

    Attributes:
        _model: CrossEncoder 模型实例，懒加载。
        _loaded: 模型是否已成功加载。
        _lock: 模型加载线程锁。
    """

    def __init__(self) -> None:
        """初始化重排服务，不加载模型（懒加载）。"""
        self._model: CrossEncoder | None = None
        self._loaded: bool = False
        self._lock: threading.Lock = threading.Lock()

    def _ensure_loaded(self) -> bool:
        """懒加载 CrossEncoder 模型（线程安全）。

        使用双重检查锁定模式：先检查 ``_loaded`` 标志，未加载时获取锁，
        再次检查后加载模型，避免重复加载与死锁。

        Returns:
            bool: 模型是否加载成功。失败时返回 False，由调用方决定降级策略。
        """
        if self._loaded:
            return True

        with self._lock:
            # 双重检查：拿到锁后可能已被其他线程加载完成
            if self._loaded:
                return True

            model_path = settings.RERANKER_MODEL_DIR
            try:
                logger.info(
                    "开始加载 bge-reranker-v2-m3 CrossEncoder 模型",
                    model_path=model_path,
                )
                self._model = CrossEncoder(
                    model_path,
                    max_length=512,  # 限制输入对长度，防止显存溢出
                )
                self._loaded = True
                logger.info(
                    "bge-reranker-v2-m3 CrossEncoder 模型加载完成",
                    model_path=model_path,
                )
                return True
            except Exception as exc:  # noqa: BLE001 - 顶层需统一捕获加载类异常
                # 加载失败时不抛出，由调用方按降级策略处理
                logger.error(
                    "加载 CrossEncoder 模型失败，将进入优雅降级模式",
                    model_path=model_path,
                    error=str(exc),
                )
                # 清理半成品模型引用，避免后续误用
                self._model = None
                self._loaded = False
                return False

    async def rerank(
        self,
        query: str,
        documents: list[dict],
        top_k: int = 5,
        batch_size: int = 4,
    ) -> list[RerankResult]:
        """对候选文档按查询相关性进行重排。

        处理流程：
        1. 空输入直接返回空列表。
        2. 过滤掉 content 为空的文档（避免无效推理）。
        3. 调用 ``_ensure_loaded`` 加载模型；失败则按原始顺序优雅降级返回。
        4. 构造 (query, content) 文本对，通过 ``asyncio.to_thread`` 调用
           ``CrossEncoder.predict`` 完成批量推理，避免阻塞事件循环。
        5. 按重排分数降序排序，截取前 ``top_k`` 条，赋予 1-based rank。

        Args:
            query: 用户查询文本。
            documents: 候选文档列表，每个 dict 包含：
                - chunk_id: str, 分块唯一标识
                - document_id: str, 所属文档 ID
                - content: str, 分块原文
                - score: float, 原始检索分数
                - metadata: dict, 扩展元信息
            top_k: 返回前 K 条结果，默认 5。
            batch_size: 模型推理批量大小，默认 4。

        Returns:
            list[RerankResult]: 按 rerank_score 降序排列的重排结果列表。
                若模型加载失败，则按输入文档原始顺序返回（无截断）。
        """
        # 空输入快速返回
        if not documents:
            return []

        # 过滤掉 content 为空或缺失的文档，避免无效推理
        valid_docs: list[dict] = [
            doc for doc in documents if doc.get("content")
        ]
        if not valid_docs:
            logger.warning("重排输入均为空文档，返回空结果", query=query)
            return []

        # 模型懒加载；失败时优雅降级，按原始顺序返回前 top_k 条
        if not self._ensure_loaded() or self._model is None:
            logger.warning(
                "CrossEncoder 模型未加载，按原始顺序降级返回候选文档",
                top_k=top_k,
                doc_count=len(valid_docs),
            )
            return self._fallback_rerank(valid_docs, top_k)

        # 构造 (query, content) 文本对
        pairs: list[list[str]] = [
            [query, doc.get("content", "")] for doc in valid_docs
        ]

        # 通过 asyncio.to_thread 包装同步 predict，避免阻塞事件循环
        try:
            scores: list[float] = await asyncio.to_thread(
                self._model.predict,
                pairs,
                batch_size=batch_size,
                convert_to_numpy=True,
            )
        except Exception as exc:  # noqa: BLE001 - 推理失败时降级返回
            logger.error(
                "CrossEncoder 推理失败，按原始顺序降级返回候选文档",
                error=str(exc),
            )
            return self._fallback_rerank(valid_docs, top_k)

        # 将 numpy 类型转换为原生 float，便于序列化与排序
        score_list: list[float] = [float(s) for s in scores]

        # 组装 RerankResult，按 rerank_score 降序排序
        paired: list[tuple[float, dict]] = list(zip(score_list, valid_docs))
        paired.sort(key=lambda x: x[0], reverse=True)

        # 截取 top_k 条并赋予 1-based rank
        results: list[RerankResult] = []
        for rank, (rerank_score, doc) in enumerate(paired[:top_k], start=1):
            results.append(
                RerankResult(
                    chunk_id=doc.get("chunk_id", ""),
                    document_id=doc.get("document_id", ""),
                    content=doc.get("content", ""),
                    original_score=float(doc.get("score", 0.0)),
                    rerank_score=rerank_score,
                    rank=rank,
                    metadata=doc.get("metadata", {}) or {},
                )
            )

        logger.info(
            "重排完成",
            query=query,
            input_count=len(valid_docs),
            output_count=len(results),
            top_k=top_k,
        )
        return results

    def _fallback_rerank(
        self, documents: list[dict], top_k: int
    ) -> list[RerankResult]:
        """优雅降级：按原始顺序构造 RerankResult。

        模型加载或推理失败时调用，保留输入文档的原始顺序与原始分数，
        ``rerank_score`` 与 ``original_score`` 相同，便于上层链路继续工作。

        Args:
            documents: 候选文档列表。
            top_k: 返回前 K 条结果。

        Returns:
            list[RerankResult]: 按原始顺序排列的重排结果。
        """
        results: list[RerankResult] = []
        for rank, doc in enumerate(documents[:top_k], start=1):
            original_score = float(doc.get("score", 0.0))
            results.append(
                RerankResult(
                    chunk_id=doc.get("chunk_id", ""),
                    document_id=doc.get("document_id", ""),
                    content=doc.get("content", ""),
                    original_score=original_score,
                    rerank_score=original_score,  # 降级时沿用原始分数
                    rank=rank,
                    metadata=doc.get("metadata", {}) or {},
                )
            )
        return results


# 模块级单例，懒加载，导入时不加载模型
reranker_service = RerankerService()
