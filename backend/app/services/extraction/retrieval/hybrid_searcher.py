"""五维 hybrid_search 检索器（Phase 3）。

封装 ``FiveDimVectorStore.hybrid_search``，将返回的 dict 列表转换为
``RetrievedChunk`` 对象列表，供 reranker 和 context_assembler 使用。

与 Phase 2 的检索区别：
- Phase 2：top_k=5，仅用于判断 feature 是否存在（快速）
- Phase 3：top_k=20，用于获取完整上下文（精确）

使用示例::

    from app.services.extraction.retrieval.hybrid_searcher import hybrid_searcher

    chunks = await hybrid_searcher.search(query_vectors, doc_id, feature="化学成分")
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.logging import get_logger
from app.services.extraction.extraction_config import get_extraction_settings
from app.services.extraction.extraction_models import RetrievedChunk
from app.services.vector.five_dim_vector_store import five_dim_vector_store

logger = get_logger(__name__)


class HybridSearcher:
    """五维 hybrid_search 检索器。

    调用 ``FiveDimVectorStore.hybrid_search`` 执行多向量字段并行检索 +
    WeightedRanker 融合，返回 ``RetrievedChunk`` 列表。
    """

    def __init__(self) -> None:
        self._settings = get_extraction_settings()

    async def search(
        self,
        query_vectors: dict[str, list[float]],
        doc_id: str,
        feature: str = "",
        top_k: int | None = None,
        per_dim_top_k: int | None = None,
        weights: dict[str, float] | None = None,
        kb_id: str | None = None,
    ) -> list[RetrievedChunk]:
        """执行五维 hybrid_search 检索。

        Args:
            query_vectors: 五维查询向量，形如
                ``{"path": [1024], "title": [...], "content": [...], ...}``。
            doc_id: 文档 ID（过滤条件）。
            feature: feature 名（仅用于日志）。
            top_k: 融合后返回数，None 时使用配置项（默认 20）。
            per_dim_top_k: 每维独立检索 top_k，None 时使用配置项（默认 30）。
            weights: 五维权重，None 时使用配置项。
            kb_id: 知识库 ID，用于向量 Collection 隔离。

        Returns:
            list[RetrievedChunk]: 检索结果，按 score 降序。
        """
        settings = self._settings
        _top_k = top_k or settings.retrieval_top_k
        _per_dim_top_k = per_dim_top_k or settings.retrieval_per_dim_top_k
        _weights = weights or settings.hybrid_search_weights

        hits = await five_dim_vector_store.hybrid_search(
            query_vectors=query_vectors,
            doc_id=doc_id,
            top_k=_top_k,
            per_dim_top_k=_per_dim_top_k,
            weights=_weights,
            kb_id=kb_id,
        )

        # 转换为 RetrievedChunk 对象列表
        chunks: list[RetrievedChunk] = []
        for hit in hits:
            chunks.append(self._to_retrieved_chunk(hit))

        logger.info(
            "hybrid_search 检索完成",
            extra={
                "feature": feature,
                "doc_id": doc_id,
                "top_k": _top_k,
                "returned": len(chunks),
                "top_score": chunks[0].score if chunks else 0.0,
            },
        )
        return chunks

    @staticmethod
    def _to_retrieved_chunk(hit: dict[str, Any]) -> RetrievedChunk:
        """将 hybrid_search 返回的 dict 转换为 RetrievedChunk。

        Args:
            hit: hybrid_search 返回的单条结果。

        Returns:
            RetrievedChunk: 转换后的检索块对象。
        """
        source_pages = hit.get("source_pages", [])
        # source_pages 可能是 JSON 字符串或列表
        if isinstance(source_pages, str):
            import json
            try:
                source_pages = json.loads(source_pages)
            except (json.JSONDecodeError, ValueError):
                source_pages = []

        return RetrievedChunk(
            chunk_id=hit.get("chunk_id", ""),
            score=float(hit.get("score", 0.0)),
            content=hit.get("content", ""),
            parent_text=hit.get("parent_text", ""),
            hierarchy_path=hit.get("hierarchy_path", ""),
            title=hit.get("title", ""),
            has_table=bool(hit.get("has_table", False)),
            source_pages=source_pages if isinstance(source_pages, list) else [],
            chunk_index=int(hit.get("chunk_index", 0)),
            level=int(hit.get("level", 0)),
        )


# 模块级单例
hybrid_searcher = HybridSearcher()
