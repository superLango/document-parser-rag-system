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
from app.services.extraction.extraction_config import get_extraction_settings
from app.services.extraction.extraction_models import (
    ExtractionTarget,
    RetrievalContext,
)
from app.services.extraction.retrieval.context_assembler import context_assembler
from app.services.extraction.retrieval.hybrid_searcher import hybrid_searcher
from app.services.extraction.retrieval.reranker import retrieval_reranker
from app.services.extraction.query_embedder import query_embedder

logger = get_logger(__name__)


class RetrievalService:
    """Phase 3 检索服务。

    编排 hybrid_searcher → reranker → context_assembler，
    返回单个 feature 的 ``RetrievalContext``。
    """

    def __init__(self) -> None:
        self._settings = get_extraction_settings()

    async def retrieve(
        self,
        target: ExtractionTarget,
        doc_id: str,
        query_vectors: dict[str, list[float]] | None = None,
        kb_id: str | None = None,
    ) -> RetrievalContext:
        """执行单个 feature 的完整检索流程。

        Args:
            target: 该 feature 的抽取目标（含 items/methods）。
            doc_id: 文档 ID。
            query_vectors: 可选，复用 Phase 2 的五维 query 向量。
                为 None 时重新编码。
            kb_id: 知识库 ID，用于向量 Collection 隔离。

        Returns:
            RetrievalContext: 检索上下文（含拼接文本和白名单 prompt）。
        """
        start_time = time.time()

        # 1. 生成 query 向量（复用或重新编码）
        if query_vectors is None:
            query_vectors = await query_embedder.encode_category_query(
                feature=target.feature,
                items=target.item_names,
                methods=target.method_names,
            )

        # 2. hybrid_search 五维检索
        chunks = await hybrid_searcher.search(
            query_vectors=query_vectors,
            doc_id=doc_id,
            feature=target.feature,
            kb_id=kb_id,
        )

        # 3. 构建重排序用的 query 文本
        rerank_query = self._build_rerank_query(target)

        # 4. reranker 重排序（可选）
        reranked_chunks = await retrieval_reranker.rerank(
            query=rerank_query,
            chunks=chunks,
        )

        # 5. context_assembler 上下文拼接
        context_text = context_assembler.assemble(reranked_chunks)

        # 6. 构建动态白名单 prompt
        whitelist_prompt = self._build_whitelist_prompt(target)

        elapsed = time.time() - start_time

        context = RetrievalContext(
            feature=target.feature,
            text=context_text,
            chunks=reranked_chunks,
            whitelist_prompt=whitelist_prompt,
            rerank_scores=[c.score for c in reranked_chunks],
        )

        logger.info(
            "Phase 3 检索完成",
            extra={
                "feature": target.feature,
                "doc_id": doc_id,
                "chunks": len(chunks),
                "reranked": len(reranked_chunks),
                "context_chars": len(context_text),
                "elapsed_sec": round(elapsed, 2),
            },
        )
        return context

    async def retrieve_doc_info(
        self,
        doc_id: str,
        query_text: str = "标准名称 标准编号 文件编号",
        kb_id: str | None = None,
    ) -> RetrievalContext:
        """执行基础信息检索（第一部分，不依赖 feature）。

        Args:
            doc_id: 文档 ID。
            query_text: 检索文本，默认 "标准名称 标准编号 文件编号"。
                包含"文件编号"以覆盖企标文档（如 LSAM-JD01-0016）。
            kb_id: 知识库 ID，用于向量 Collection 隔离。

        Returns:
            RetrievalContext: 检索上下文。
        """
        # 基础信息用通用文本检索
        query_vectors = await query_embedder.encode_text_query(query_text)

        chunks = await hybrid_searcher.search(
            query_vectors=query_vectors,
            doc_id=doc_id,
            feature="doc_info",
            top_k=10,
            kb_id=kb_id,
        )

        # 基础信息不需要重排序（少量结果即可）
        context_text = context_assembler.assemble(chunks, max_tokens=5000)

        return RetrievalContext(
            feature="doc_info",
            text=context_text,
            chunks=chunks,
        )

    async def retrieve_heat_treatment(
        self,
        doc_id: str,
        features_list: list[str],
        kb_id: str | None = None,
    ) -> RetrievalContext:
        """执行热处理制度检索（第三部分）。

        用热处理专业关键词构建 query，而非 feature 列表（feature 列表会
        稀释"热处理制度"语义，导致召回检验方法章节而非热处理制度章节）。
        features_list 仅用于后续 prompt 的"项目大类"enum 约束，不参与检索。

        Args:
            doc_id: 文档 ID。
            features_list: feature 名列表（仅用于 prompt enum 约束，不参与检索）。
            kb_id: 知识库 ID，用于向量 Collection 隔离。

        Returns:
            RetrievalContext: 检索上下文。
        """
        # 用热处理专业关键词构建 query（重复"热处理制度"增强语义权重）
        query_text = (
            "热处理制度 热处理制度 固溶处理 时效处理 退火 淬火 "
            "保温温度 保温时间 升温速率 降温速率 出炉温度 "
            "冷却介质 空冷 水冷 油冷 炉冷 装炉温度"
        )
        query_vectors = await query_embedder.encode_text_query(query_text)

        chunks = await hybrid_searcher.search(
            query_vectors=query_vectors,
            doc_id=doc_id,
            feature="heat_treatment",
            top_k=30,
            kb_id=kb_id,
        )

        # 热处理制度重排序（用精简 query，增大 top_k 确保热处理内容不被剔除）
        # 热处理制度内容常被归到"交货状态"等章节，排名靠后，需更大 top_k
        rerank_query = "热处理制度 固溶 时效 保温 冷却"
        reranked = await retrieval_reranker.rerank(
            query=rerank_query,
            chunks=chunks,
            top_k=20,
        )

        context_text = context_assembler.assemble(reranked, max_tokens=20000)

        return RetrievalContext(
            feature="heat_treatment",
            text=context_text,
            chunks=reranked,
        )

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

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
            parts.append(" ".join(target.item_names[:20]))
        if target.method_names:
            parts.append(" ".join(target.method_names[:8]))
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

        # 试验方法白名单用标准编号（method_codes），fallback 到方法名称
        method_enum = target.method_codes or target.method_names
        if method_enum:
            lines.append("[方法白名单]")
            lines.append(f"试验方法必须从以下列表中选取（标准编号）：{'、'.join(method_enum)}")
            lines.append("有年代号的保留，无年代号的取列表中对应方法的最新年代号。")
            lines.append("")

        if not lines:
            return ""

        return "\n".join(lines)


# 模块级单例
retrieval_service = RetrievalService()
