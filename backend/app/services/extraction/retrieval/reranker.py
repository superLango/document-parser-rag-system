"""检索结果重排序器（Phase 3，可选）。

调用 ``reranker_service``（bge-reranker-v2-m3 CrossEncoder）对 hybrid_search
结果做二次重排，提升检索精度。

重排流程：
1. 将 RetrievedChunk 列表转为 reranker_service 所需的 documents 格式
2. 调用 reranker_service.rerank(query, documents, top_k)
3. 将 RerankResult 转回 RetrievedChunk（更新 score 为 rerank_score）

可通过 ``EXTRACTION_V3_RETRIEVAL_RERANK_ENABLED=False`` 禁用。

使用示例::

    from app.services.extraction.retrieval.reranker import retrieval_reranker

    reranked = await retrieval_reranker.rerank(
        query="化学成分 C Si Mn",
        chunks=chunks,
        top_k=15,
    )
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.logging import get_logger
from app.services.extraction.extraction_config import get_extraction_settings
from app.services.extraction.extraction_models import RetrievedChunk
# TODO: reranker目录已删除，重排功能待重构
# from app.services.reranker.reranker_service import reranker_service
reranker_service = None

logger = get_logger(__name__)


class RetrievalReranker:
    """检索结果重排序器。

    封装 ``reranker_service``，将 ``RetrievedChunk`` 列表重排后返回。
    禁用或失败时优雅降级，返回原始 chunks（截断到 top_k）。
    """

    def __init__(self) -> None:
        self._settings = get_extraction_settings()

    async def rerank(
        self,
        query: str,
        chunks: list[RetrievedChunk],
        top_k: int | None = None,
    ) -> list[RetrievedChunk]:
        """对检索结果做 CrossEncoder 重排。

        Args:
            query: 查询文本（feature + items + methods 拼接）。
            chunks: hybrid_search 返回的 RetrievedChunk 列表。
            top_k: 重排后保留数，None 时使用配置项（默认 15）。

        Returns:
            list[RetrievedChunk]: 重排后的 chunks，按 rerank_score 降序。
                若重排禁用或失败，返回原始 chunks 截断到 top_k。
        """
        _top_k = top_k or self._settings.rerank_top_k

        # 禁用时直接截断返回
        if not self._settings.rerank_enabled or reranker_service is None:
            if reranker_service is None and self._settings.rerank_enabled:
                logger.warning("reranker_service不可用，跳过重排")
            return chunks[:_top_k]

        if not chunks:
            return []

        # 转换为 reranker_service 所需的 documents 格式
        documents: list[dict[str, Any]] = []
        for chunk in chunks:
            documents.append({
                "chunk_id": chunk.chunk_id,
                "document_id": "",
                "content": chunk.content,
                "score": chunk.score,
                "metadata": {
                    "hierarchy_path": chunk.hierarchy_path,
                    "title": chunk.title,
                    "has_table": chunk.has_table,
                    "source_pages": chunk.source_pages,
                },
            })

        try:
            rerank_results = await reranker_service.rerank(
                query=query,
                documents=documents,
                top_k=_top_k,
            )
        except Exception as err:
            logger.warning(
                "重排序失败，降级返回原始结果",
                extra={"error": str(err), "top_k": _top_k},
            )
            return chunks[:_top_k]

        # 将 RerankResult 转回 RetrievedChunk（更新 score）
        chunk_map: dict[str, RetrievedChunk] = {c.chunk_id: c for c in chunks}
        reranked: list[RetrievedChunk] = []
        for result in rerank_results:
            chunk = chunk_map.get(result.chunk_id)
            if chunk is None:
                # chunk_id 不匹配时，用 content 匹配
                for c in chunks:
                    if c.content == result.content:
                        chunk = c
                        break
            if chunk is not None:
                # 更新 score 为 rerank_score
                reranked.append(RetrievedChunk(
                    chunk_id=chunk.chunk_id,
                    score=result.rerank_score,
                    content=chunk.content,
                    parent_text=chunk.parent_text,
                    hierarchy_path=chunk.hierarchy_path,
                    title=chunk.title,
                    has_table=chunk.has_table,
                    source_pages=chunk.source_pages,
                    chunk_index=chunk.chunk_index,
                    level=chunk.level,
                ))

        logger.info(
            "重排序完成",
            extra={
                "query_len": len(query),
                "input_count": len(chunks),
                "output_count": len(reranked),
                "top_k": _top_k,
            },
        )
        return reranked


# 模块级单例
retrieval_reranker = RetrievalReranker()
