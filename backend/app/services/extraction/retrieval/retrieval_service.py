"""Phase 3 检索服务（编排 searcher → reranker → assembler）。

为每个保留的 feature 执行完整的检索流程：
1. 生成五维 query 向量（复用 query_embedder）
2. hybrid_search 五维检索（top_k=20）
3. reranker 重排序（可选，top_k=15）
4. context_assembler 上下文拼接（max_tokens=28000）
5. 构建动态白名单 prompt（items + methods 列表）

返回 ``RetrievalContext``，供 Phase 4 LLM 抽取使用。

使用示例::

    from app.services.extraction.retrieval.retrieval_service import retrieval_service

    context = await retrieval_service.retrieve(target, doc_id, query_vectors)
"""

from __future__ import annotations

import logging
import time
from typing import Any

from app.core.logging import get_logger
from app.core.exceptions import BusinessException
from app.services.extraction.extraction_models import (
    ExtractionTarget,
    RetrievalContext,
)
from app.services.extraction.retrieval.context_assembler import context_assembler
from app.services.extraction.retrieval.hybrid_searcher import hybrid_searcher
from app.services.extraction.retrieval.reranker import retrieval_reranker
from app.services.extraction.retrieval.query_embedder import query_embedder

logger = get_logger(__name__)


class RetrievalService:
    """Phase 3 检索服务。

    编排 hybrid_searcher → reranker → context_assembler，
    返回单个 feature 的 ``RetrievalContext``。
    """

    def __init__(self) -> None:
        pass

    async def retrieve(
        self,
        target: ExtractionTarget,
        doc_id: str,
        query_vectors: dict[str, list[float]] | None = None,
        kb_id: str | None = None,
        cfg: Any = None,
    ) -> RetrievalContext:
        """执行单个 feature 的完整检索流程（配置驱动）。

        Args:
            target: 该 feature 的抽取目标（含 query_terms/fields）。
            doc_id: 文档 ID。
            query_vectors: 可选，复用 Phase 2 的五维 query 向量。
                为 None 时按 target.query_terms 重新编码。
            kb_id: 知识库 ID，用于向量 Collection 隔离。
            cfg: 抽取领域配置（全局检索参数）。

        Returns:
            RetrievalContext: 检索上下文（含拼接文本和白名单 prompt）。
        """
        start_time = time.time()

        # 全局检索参数（retrieval 区块，缺失即报错，不允许 settings/env 兜底）
        if cfg is None:
            raise BusinessException("检索缺少抽取配置（cfg）")
        retrieval_cfg = cfg.retrieval or {}
        per_dim_top_k = retrieval_cfg.get("per_dim_top_k")
        if per_dim_top_k is None:
            raise BusinessException("未配置检索参数 retrieval.per_dim_top_k")
        weights = retrieval_cfg.get("weights")
        if not weights:
            raise BusinessException("未配置检索权重 retrieval.weights")
        context_max_tokens = retrieval_cfg.get("context_max_tokens")
        if context_max_tokens is None:
            raise BusinessException("未配置上下文最大 token 数 retrieval.context_max_tokens")
        reranker_cfg = retrieval_cfg.get("reranker") or {}
        # 混合检索配置（稠密 + 稀疏 BM25；表格感知加分）
        hybrid_cfg = retrieval_cfg.get("hybrid") or {}
        # 类别级 top_k 覆盖全局（类别→全局层级回退，均缺失即报错）
        top_k = target.top_k or retrieval_cfg.get("top_k")
        if top_k is None:
            raise BusinessException("未配置检索 top_k（retrieval.top_k 或类别级 top_k）")
        # 类别级重排序 top_n 覆盖全局（未填用全局 reranker.top_n）
        rerank_top_n = target.rerank_top_k or reranker_cfg.get("top_n") or retrieval_cfg.get("rerank_top_k")

        # 【调试】Phase 3 进入：打印检索所用全部配置项
        logger.info(
            "【Phase 3·进入】类别检索所用配置与参数",
            extra={
                "feature": target.feature,
                "top_k": top_k,
                "per_dim_top_k": per_dim_top_k,
                "weights": weights,
                "context_max_tokens": context_max_tokens,
                "reranker": reranker_cfg,
                "rerank_top_n": rerank_top_n,
                "hybrid": hybrid_cfg,
                "query_terms": target.query_terms,
            },
        )

        # 1. 生成 query 向量（复用或按 query_terms 重新编码）
        if query_vectors is None:
            query_vectors = await query_embedder.encode_category_query(
                feature=target.feature,
                items=target.query_terms,
                methods=[],
                cfg=cfg,
                query_sources=target.query_sources,
            )

        # 2. 构建稀疏 query（BM25 词法路，RRF 混合检索用）
        sparse_query = self._build_sparse_query(target, hybrid_cfg, kb_id)

        # 3. 混合检索（稠密五维 + 稀疏 BM25，RRF 融合）
        chunks = await hybrid_searcher.search(
            query_vectors=query_vectors,
            doc_id=doc_id,
            feature=target.feature,
            top_k=top_k,
            per_dim_top_k=per_dim_top_k,
            weights=weights,
            kb_id=kb_id,
            sparse_query=sparse_query,
            hybrid_cfg=hybrid_cfg,
        )

        # 4. 构建重排序用的 query 文本
        rerank_query = self._build_rerank_query(target)

        # 5. reranker 重排序（可选，按配置；禁用时直接透传）
        reranked_chunks = await retrieval_reranker.rerank(
            query=rerank_query,
            chunks=chunks,
            top_k=rerank_top_n,
            cfg=cfg,
        )

        # 6. context_assembler 上下文拼接
        context_text = context_assembler.assemble(reranked_chunks, max_tokens=context_max_tokens, cfg=cfg)

        # 7. 构建动态白名单 prompt
        whitelist_prompt = self._build_whitelist_prompt(target)

        elapsed = time.time() - start_time

        context = RetrievalContext(
            feature=target.feature,
            text=context_text,
            chunks=reranked_chunks,
            whitelist_prompt=whitelist_prompt,
            rerank_scores=[c.score for c in reranked_chunks],
        )

        # 【调试】Phase 3 输出：检索/重排/上下文结果
        logger.info(
            "【Phase 3·输出】类别检索-重排-上下文结果",
            extra={
                "feature": target.feature,
                "chunks_count": len(chunks),
                "reranked_count": len(reranked_chunks),
                "rerank_scores": [round(c.score, 4) for c in reranked_chunks],
                "chunks": [
                    {
                        "score": round(c.score, 4),
                        "path": str(c.path)[:120] if getattr(c, "path", None) else None,
                        "text_preview": (c.content or "")[:300],
                    }
                    for c in reranked_chunks[:10]
                ],
                "context_text_len": len(context_text),
                "context_text_preview": context_text[:600],
                "whitelist_prompt": whitelist_prompt,
            },
        )

        logger.info(
            "Phase 3 检索完成",
            extra={
                "feature": target.feature,
                "doc_id": doc_id,
                "top_k": top_k,
                "chunks": len(chunks),
                "reranked": len(reranked_chunks),
                "context_chars": len(context_text),
                "elapsed_sec": round(elapsed, 2),
            },
        )
        return context

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    @staticmethod
    def _build_sparse_query(
        target: ExtractionTarget,
        hybrid_cfg: dict,
        kb_id: str | None,
    ) -> dict[int, float] | None:
        """构建稀疏（BM25）查询向量用于 RRF 混合检索。

        仅当混合检索开启、KB 有已拟合的 BM25 模型、且类别有 query_terms 时
        才返回非空稀疏向量；否则返回 None（退化为纯稠密路）。

        Returns:
            dict[int, float] | None: 稀疏查询向量；未启用时为 None。
        """
        if not hybrid_cfg.get("enabled"):
            return None
        if not kb_id or not target.query_terms:
            return None
        from app.services.vector.bm25_sparse import get_kb_bm25
        kb_bm25 = get_kb_bm25(kb_id)
        if kb_bm25 is None:
            return None
        sparse_query = kb_bm25.encode_query(" ".join(target.query_terms))
        if not sparse_query:
            return None
        return sparse_query

    @staticmethod
    def _build_rerank_query(target: ExtractionTarget) -> str:
        """构建重排序 query 文本。

        将 feature + items + methods 拼接为 query 文本，
        供 CrossEncoder 重排序使用。

        Args:
            target: 抽取目标。

        Returns:
            str: query 文本。
        """
        parts = [target.feature]
        if target.item_names:
            parts.append(" ".join(target.item_names))
        return " ".join(parts)

    @staticmethod
    def _build_whitelist_prompt(target: ExtractionTarget) -> str:
        """构建动态白名单 prompt（注入 LLM prompt 约束类别边界）。

        Args:
            target: 抽取目标。

        Returns:
            str: 白名单 prompt 文本。
        """
        lines: list[str] = []

        if target.item_names:
            lines.append("[项目白名单]")
            lines.append(f"项目名称必须从以下列表中选取：{'、'.join(target.item_names)}")
            lines.append("")

        if not lines:
            return ""

        return "\n".join(lines)


# 模块级单例
retrieval_service = RetrievalService()
