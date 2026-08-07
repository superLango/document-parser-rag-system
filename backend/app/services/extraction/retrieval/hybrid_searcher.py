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
from app.core.exceptions import BusinessException
from app.services.extraction.extraction_models import RetrievedChunk
from app.services.vector.five_dim_vector_store import five_dim_vector_store

logger = get_logger(__name__)


class HybridSearcher:
    """五维 hybrid_search 检索器。

    调用 ``FiveDimVectorStore.hybrid_search`` 执行多向量字段并行检索 +
    WeightedRanker 融合，返回 ``RetrievedChunk`` 列表。
    """

    def __init__(self) -> None:
        pass

    async def search(
        self,
        query_vectors: dict[str, list[float]],
        doc_id: str,
        feature: str = "",
        top_k: int | None = None,
        per_dim_top_k: int | None = None,
        weights: dict[str, float] | None = None,
        kb_id: str | None = None,
        sparse_query: dict[int, float] | None = None,
        hybrid_cfg: dict | None = None,
    ) -> list[RetrievedChunk]:
        """执行混合检索（稠密五维 + 稀疏 BM25，RRF 融合）。

        Args:
            query_vectors: 五维查询向量，形如
                ``{"path": [1024], "title": [...], "content": [...], ...}``。
            doc_id: 文档 ID（过滤条件）。
            feature: feature 名（仅用于日志）。
            top_k: 融合后最终返回数。
            per_dim_top_k: 每维独立检索 top_k。
            weights: 五维权重。
            kb_id: 知识库 ID，用于向量 Collection 隔离。
            sparse_query: 稀疏（BM25）查询向量；为 None 表示仅稠密路。
            hybrid_cfg: 混合检索配置（dense_candidate_k / keyword_top_k /
                rrf_k / dense_weight / keyword_weight）。

        Returns:
            list[RetrievedChunk]: RRF 融合后的检索结果，按 score 降序。
        """
        # 检索参数由调用方从配置解析传入，缺失即报错（不允许 settings/env 兜底）
        if top_k is None:
            raise BusinessException("未配置检索 top_k（retrieval.top_k 或类别级 top_k）")
        if per_dim_top_k is None:
            raise BusinessException("未配置检索 per_dim_top_k（retrieval.per_dim_top_k）")
        if not weights:
            raise BusinessException("未配置检索权重（retrieval.weights）")
        _top_k = top_k
        _per_dim_top_k = per_dim_top_k
        _weights = weights
        _hybrid = hybrid_cfg or {}

        # 混合检索开启时采用稠密+词法 RRF 融合；否则纯稠密 WeightedRanker
        use_hybrid = bool(_hybrid.get("enabled")) and sparse_query is not None

        # ── 1) 稠密路：五维 WeightedRanker（不含稀疏），召回 dense_candidate_k 候选 ──
        dense_candidate_k = int(_hybrid.get("dense_candidate_k") or _top_k)
        dense_hits = await five_dim_vector_store.hybrid_search(
            query_vectors=query_vectors,
            doc_id=doc_id,
            top_k=max(dense_candidate_k, _top_k),
            per_dim_top_k=_per_dim_top_k,
            weights=_weights,
            kb_id=kb_id,
        )

        # ── 2) 词法路（可选）：稀疏 BM25，召回 keyword_top_k 候选 ──
        keyword_hits: list[dict[str, Any]] = []
        if use_hybrid:
            keyword_top_k = int(_hybrid.get("keyword_top_k") or _top_k)
            keyword_hits = await five_dim_vector_store.sparse_search(
                sparse_query=sparse_query,
                doc_id=doc_id,
                top_k=keyword_top_k,
                kb_id=kb_id,
            )

        # 词法命中=0 的类别剔除（词法无证据，文档大概率不含该类别）
        # 混合检索启用时，sparse_query 为 None（query_terms 空）或 keyword_hits 为空
        # 均视为词法无命中，直接剔除以跳过无效 LLM 调用
        if bool(_hybrid.get("enabled")) and not keyword_hits:
            logger.info(
                "【Phase 3·剔除】词法命中=0，跳过该类别",
                extra={"feature": feature, "doc_id": doc_id, "use_hybrid": use_hybrid},
            )
            return []

        # ── 3) RRF 融合（rank 取反，weight/(rrf_k+rank)）──
        rrf_k = float(_hybrid.get("rrf_k") or 60.0)
        dense_w = float(_hybrid.get("dense_weight") or 1.0)
        kw_w = float(_hybrid.get("keyword_weight") or 1.2)

        # 各路按 score 降序得到 rank（1-based）
        dense_sorted = sorted(dense_hits, key=lambda h: h.get("score", 0.0), reverse=True)
        kw_sorted = sorted(keyword_hits, key=lambda h: h.get("score", 0.0), reverse=True)
        dense_rank = {h["chunk_id"]: i + 1 for i, h in enumerate(dense_sorted)}
        kw_rank = {h["chunk_id"]: i + 1 for i, h in enumerate(kw_sorted)}

        # 块数据索引（稠密优先，词法命中但稠密未命中的块补入）
        chunk_map: dict[str, dict[str, Any]] = {h["chunk_id"]: h for h in dense_sorted}
        for h in kw_sorted:
            chunk_map.setdefault(h["chunk_id"], h)

        all_ids = set(dense_rank) | set(kw_rank)
        scored: list[tuple[dict[str, Any], float]] = []
        for cid in all_ids:
            score = 0.0
            if cid in dense_rank:
                score += dense_w / (rrf_k + dense_rank[cid])
            if cid in kw_rank:
                score += kw_w / (rrf_k + kw_rank[cid])
            chunk = chunk_map[cid]
            scored.append((chunk, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        scored = scored[:_top_k]

        chunks: list[RetrievedChunk] = []
        for chunk, score in scored:
            converted = self._to_retrieved_chunk({**chunk, "score": score})
            chunks.append(converted)

        logger.info(
            "混合检索（RRF）完成",
            extra={
                "feature": feature,
                "doc_id": doc_id,
                "top_k": _top_k,
                "dense_candidates": len(dense_hits),
                "keyword_candidates": len(keyword_hits),
                "returned": len(chunks),
                "use_hybrid": use_hybrid,
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
