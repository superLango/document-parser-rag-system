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
from .reranker import passthrough_reranker

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
    ) -> list[SearchResult]:
        """执行混合检索。

        Args:
            db: 数据库会话（已激活 KB RLS 上下文）。
            kb_id: 知识库 ID。
            query: 查询文本。
            top_k: 返回数量（默认配置）。
            filters: 可选过滤（文档/表格/层级）。

        Returns:
            按 RRF 分数降序的命中列表。
        """
        query = (query or "").strip()
        if not query:
            return []
        top_k = top_k or settings.RETRIEVAL_TOP_K
        candidate_k = max(top_k * settings.RETRIEVAL_CANDIDATE_MULT, top_k)
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

        # 3) BM25 词法路（同样应用过滤条件）
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
            score = (
                settings.RETRIEVAL_TITLE_WEIGHT * t
                + settings.RETRIEVAL_CONTENT_WEIGHT * c
            )
            dense_list.append((cid, score, hit))
        dense_list.sort(key=lambda x: x[1], reverse=True)

        # 5) RRF 融合
        top = self._rrf_fuse(dense_list, keyword_hits, top_k)

        # 6) rerank 占位（本期直通）
        chunk_map: dict[str, dict] = {cid: h for cid, _, h in dense_list}
        for h in keyword_hits:
            chunk_map.setdefault(h["chunk_id"], h)
        kw_set = {h["chunk_id"] for h in keyword_hits}
        raw_hits = [self._to_hit(chunk_map[cid], score, cid in kw_set) for cid, score in top]
        reranked = await passthrough_reranker.rerank(query, raw_hits, top_k)
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
    ) -> list[tuple[str, float]]:
        """RRF 融合：dense 排名（已按加权分排序）与 BM25 排名加权求和。"""
        rrf_k = settings.RETRIEVAL_RRF_K
        dense_w = settings.RETRIEVAL_DENSE_WEIGHT
        kw_w = settings.RETRIEVAL_KEYWORD_WEIGHT
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
