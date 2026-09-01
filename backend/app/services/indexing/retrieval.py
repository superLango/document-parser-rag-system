"""检索服务（S6/D6）：双向量 dense + jieba BM25 + RRF 融合。

流程：
1. 查询编码：query 分别编码 title/content 双路（BGE-M3）；
2. dense：title_vector / content_vector 两路 pgvector 余弦近邻（top_k*candidate_mult）；
3. sparse：kb_bm25_service.score_query 词法打分；
4. 融合：title/content 按权重加权合成 dense 分数 → 与 BM25 做 RRF（k=60，权重配置化）；
5. rerank 接口占位（本期直通）。

与旧项目检索的关系：沿用 RRF 与权重配置思想，但存储/查询全部基于 pgvector +
PG 表（无 Milvus WeightedRanker），查询编码仅双文本（无五维复制）。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.services.embedding.embedding_service import embedding_service

from .bm25 import kb_bm25_service
from .reranker import get_reranker

logger = get_logger(__name__)


@dataclass(slots=True)
class SearchFilters:
    """检索过滤条件（可选）。"""

    document_id: uuid.UUID | None = None
    has_table: bool | None = None
    level: int | None = None


@dataclass(slots=True)
class SearchResult:
    """单条检索命中。"""

    chunk_id: str
    document_id: str
    content: str
    parent_text: str | None = None
    hierarchy_path: str = ""
    title: str = ""
    source_pages: list = field(default_factory=list)
    has_table: bool = False
    score: float = 0.0
    keyword_matched: bool = False
    rerank_score: float | None = None


def _vector_literal(vec: list[float]) -> str:
    """向量列表 → pgvector 字面量字符串。"""
    return "[" + ",".join(f"{v:.8f}" for v in vec) + "]"


def _filters_sql(filters: SearchFilters | None) -> tuple[str, dict]:
    """构造过滤条件 SQL 片段与参数。"""
    if filters is None:
        return "", {}
    conds: list[str] = []
    params: dict = {}
    if filters.document_id is not None:
        conds.append("document_id = :f_doc")
        params["f_doc"] = filters.document_id
    if filters.has_table is not None:
        conds.append("has_table = :f_table")
        params["f_table"] = filters.has_table
    if filters.level is not None:
        conds.append("level = :f_level")
        params["f_level"] = filters.level
    return (" AND " + " AND ".join(conds)) if conds else "", params


class RetrievalService:
    """双向量 + BM25 + RRF 检索服务。"""

    async def search(
        self,
        db: AsyncSession,
        kb_id: uuid.UUID,
        query: str,
        top_k: int | None = None,
        filters: SearchFilters | None = None,
        rerank_query: str | None = None,
        retrieval_config: dict | None = None,
        per_dim_top_k: int | None = None,
        skip_rerank: bool = False,
    ) -> list[SearchResult]:
        """执行混合检索。

        Args:
            db: 数据库会话（已激活 KB RLS 上下文）。
            kb_id: 知识库 ID。
            query: 查询文本。
            top_k: 返回数量（默认配置）。
            filters: 可选过滤（文档/表格/层级）。
            retrieval_config: KB 全局配置 retrieval 区块；未传时回退 settings 常量。
                生效键：candidate_mult/weights/hybrid.enabled/rrf_k/dense_weight/keyword_weight/
                reranker.enabled/top_n；per_dim_top_k 用于类别召回两段式检索的每维候选数。

        Returns:
            按 RRF 分数降序的命中列表。
        """
        query = (query or "").strip()
        if not query:
            return []
        rcfg = retrieval_config or {}
        top_k = top_k or int(rcfg.get("top_k") or settings.RETRIEVAL_TOP_K)
        candidate_mult = int(rcfg.get("candidate_mult") or settings.RETRIEVAL_CANDIDATE_MULT)
        if per_dim_top_k is not None:
            candidate_k = max(int(per_dim_top_k), top_k)
        else:
            candidate_k = max(top_k * candidate_mult, top_k)
        title_w = float((rcfg.get("weights") or {}).get("title") or settings.RETRIEVAL_TITLE_WEIGHT)
        content_w = float((rcfg.get("weights") or {}).get("content") or settings.RETRIEVAL_CONTENT_WEIGHT)
        hybrid_cfg = rcfg.get("hybrid") or {}
        hybrid_enabled = bool(hybrid_cfg.get("enabled", True))
        rrf_k = float(hybrid_cfg.get("rrf_k") or settings.RETRIEVAL_RRF_K)
        dense_w = float(hybrid_cfg.get("dense_weight") or settings.RETRIEVAL_DENSE_WEIGHT)
        kw_w = float(hybrid_cfg.get("keyword_weight") or settings.RETRIEVAL_KEYWORD_WEIGHT)
        filters_sql, filter_params = _filters_sql(filters)

        # 1) 查询编码（title/content 双路一次批量）
        vectors = await embedding_service.embed([query, query])
        title_vec, content_vec = vectors[0], vectors[1]

        # 2) dense 两路 ANN
        title_hits = await self._ann_search(
            db, kb_id, "title_vector", title_vec, candidate_k, filters_sql, filter_params
        )
        content_hits = await self._ann_search(
            db, kb_id, "content_vector", content_vec, candidate_k, filters_sql, filter_params
        )

        # 3) BM25 词法路（hybrid.enabled 控制；同样应用过滤条件）
        keyword_hits = []
        if hybrid_enabled:
            keyword_hits = await kb_bm25_service.score_query(
                db, kb_id, query, top_k=candidate_k,
                extra_where=filters_sql, extra_params=filter_params,
            )

        # 4) dense 融合（title 0.2 + content 0.8，相似度加权）
        dense_scores: dict[str, dict] = {}
        for hit in title_hits:
            dense_scores.setdefault(hit["chunk_id"], hit)["_t"] = hit["_dist"]
        for hit in content_hits:
            dense_scores.setdefault(hit["chunk_id"], hit)["_c"] = hit["_dist"]
        dense_list: list[tuple[str, float, dict]] = []
        for cid, hit in dense_scores.items():
            t = 1.0 - hit.get("_t", 1.0)
            c = 1.0 - hit.get("_c", 1.0)
            score = title_w * t + content_w * c
            dense_list.append((cid, score, hit))
        dense_list.sort(key=lambda x: x[1], reverse=True)

        # 5) RRF 融合（权重可配置）
        top = self._rrf_fuse(dense_list, keyword_hits, top_k, rrf_k, dense_w, kw_w)

        # 6) 重排（默认直通；reranker.enabled=true 时 BGE-M3 语义精排）
        chunk_map: dict[str, dict] = {cid: h for cid, _, h in dense_list}
        for h in keyword_hits:
            chunk_map.setdefault(h["chunk_id"], h)
        kw_set = {h["chunk_id"] for h in keyword_hits}
        raw_hits = [self._to_hit(chunk_map[cid], score, cid in kw_set) for cid, score in top]
        reranker = get_reranker(rcfg)
        reranker_top_n = int((rcfg.get("reranker") or {}).get("top_n") or top_k)
        # 重排 query 与检索 query 分离：rerank_query 传入时用于重排打分
        # （类别抽取场景：检索用精简术语召回，重排用完整术语+Schema 字段提升相关性打分）
        # rerank 候选控制(2026-08-29): raw_hits 为 RRF 融合后 top_k(k40),
        # 若全量送入 CrossEncoder 逐批打分, 候选多(40)时 GPU 推理耗时高(41类×5-10s)。
        # 仅对前 max(top_n, 25) 个候选精排(取 top_n), 兼顾召回与耗时:
        #   top_n=15 → 输入 25 候选(RSL 保留, 避免 top17-25 的高相关块被重排窗口遗漏)
        #   top_n=40 → 输入 40(全量)
        # rerank 候选控制(2026-08-29 v2): 直接只对前 reranker_top_n(top_n=15)
        # 候选精排——因为最终只保留 top_n, 额外候选精排是浪费(实测 25 → 3.4s,
        # 15 → ~2s; 且上下文排序页序时 rerank 分主要用于过滤/0条重试)。
        rerank_candidates = raw_hits[: min(reranker_top_n, len(raw_hits))]
        if skip_rerank:
            # 跳过重排: 不截断到 reranker_top_n —— 返回完整 top_k 候选
            # (数据路 top_k=40 / 元信息路 top_k=20 应完整保留; 之前被 min(reranker_top_n,top_k)=15
            #  压住导致两路各只返回 15, 候选 60→30 的隐藏退化)
            reranked = raw_hits[:top_k]
        else:
            reranked = await reranker.rerank(
                (rerank_query or query).strip() or query,
                rerank_candidates,
                min(reranker_top_n, top_k),
            )
        logger.info(
            "检索完成",
            kb_id=str(kb_id),
            query_len=len(query),
            title_hits=len(title_hits),
            content_hits=len(content_hits),
            keyword_hits=len(keyword_hits),
            returned=len(reranked),
        )
        return reranked

    @staticmethod
    def _rrf_fuse(
        dense_list: list[tuple[str, float, dict]],
        keyword_hits: list[dict],
        top_k: int,
        rrf_k: float,
        dense_w: float,
        kw_w: float,
    ) -> list[tuple[str, float]]:
        """RRF 融合：dense 排名（已按加权分排序）与 BM25 排名加权求和。"""
        dense_rank = {cid: i + 1 for i, (cid, _, _) in enumerate(dense_list)}
        keyword_rank = {h["chunk_id"]: i + 1 for i, h in enumerate(keyword_hits)}
        fused: list[tuple[str, float]] = []
        for cid in set(dense_rank) | set(keyword_rank):
            score = 0.0
            if cid in dense_rank:
                score += dense_w / (rrf_k + dense_rank[cid])
            if cid in keyword_rank:
                score += kw_w / (rrf_k + keyword_rank[cid])
            fused.append((cid, score))
        fused.sort(key=lambda x: x[1], reverse=True)
        return fused[:top_k]

    async def _ann_search(
        self,
        db: AsyncSession,
        kb_id: uuid.UUID,
        column: str,
        query_vec: list[float],
        limit: int,
        filters_sql: str,
        filter_params: dict,
    ) -> list[dict]:
        """单路向量 ANN：余弦距离升序取 top limit。"""
        rows = (
            await db.execute(
                text(
                    f"SELECT chunk_id, document_id, content, parent_text, hierarchy_path, "
                    f"title, source_pages, has_table, ({column} <=> CAST(:qv AS vector)) AS dist "
                    f"FROM document_chunks "
                    f"WHERE kb_id = :kb AND deleted_at IS NULL "
                    f"AND {column} IS NOT NULL{filters_sql} "
                    f"ORDER BY dist LIMIT :lim"
                ).bindparams(
                    kb=kb_id,
                    qv=_vector_literal(query_vec),
                    lim=limit,
                    **filter_params,
                ),
            )
        ).all()
        return [
            {
                "chunk_id": r.chunk_id,
                "document_id": str(r.document_id),
                "content": r.content,
                "parent_text": r.parent_text,
                "hierarchy_path": r.hierarchy_path,
                "title": r.title,
                "source_pages": r.source_pages,
                "has_table": r.has_table,
                "_dist": float(r.dist),
            }
            for r in rows
        ]

    @staticmethod
    def _to_hit(hit: dict, score: float, keyword_matched: bool = False) -> SearchResult:
        """组装检索结果（移除内部距离字段）。"""
        return SearchResult(
            chunk_id=hit["chunk_id"],
            document_id=hit["document_id"],
            content=hit["content"],
            parent_text=hit.get("parent_text"),
            hierarchy_path=hit.get("hierarchy_path", ""),
            title=hit.get("title", ""),
            source_pages=hit.get("source_pages", []),
            has_table=bool(hit.get("has_table", False)),
            score=round(score, 6),
            keyword_matched=keyword_matched,
        )


retrieval_service = RetrievalService()
