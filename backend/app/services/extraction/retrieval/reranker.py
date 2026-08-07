"""检索结果重排序器（Phase 3，可选）。

对 hybrid_search 结果用 ``bge-reranker-v2-m3``（FlagReranker CrossEncoder）
做二次重排，提升检索精度。

重排流程：
1. 懒加载 FlagReranker 模型（路径来自配置，失败时优雅降级）
2. 对每对 (query, chunk.content) 计算重排分数
3. 按分数降序保留 top_k，更新 chunk.score 为 rerank_score

配置驱动：
- 开关：``cfg.retrieval.reranker.enabled``（无 cfg 时回退 settings.rerank_enabled）
- 模型路径：``cfg.retrieval.reranker.model``（为空时回退 settings.RERANKER_MODEL_DIR）
- 保留数：``top_k`` 参数 → ``cfg.retrieval.reranker.top_n`` → settings.rerank_top_k

任何环节失败（模型未加载 / 推理异常）都优雅降级，返回原始 chunks 截断到 top_k。

使用示例::

    from app.services.extraction.retrieval.reranker import retrieval_reranker

    reranked = await retrieval_reranker.rerank(
        query="化学成分 C Si Mn",
        chunks=chunks,
        top_k=15,
        cfg=cfg,
    )
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.core.logging import get_logger
from app.core.exceptions import BusinessException
from app.services.extraction.extraction_models import RetrievedChunk

logger = get_logger(__name__)


class RetrievalReranker:
    """检索结果重排序器。

    封装 ``FlagReranker``，将 ``RetrievedChunk`` 列表重排后返回。
    模型懒加载；禁用、未加载或推理失败时优雅降级返回原始 chunks。
    """

    def __init__(self) -> None:
        self._reranker: Any = None  # FlagReranker 实例
        self._load_error: str | None = None

    def _load(self, model_path: str) -> Any:
        """懒加载 FlagReranker 模型（线程安全由调用方保证）。

        Args:
            model_path: 模型路径（本地目录）。

        Returns:
            FlagReranker 实例；加载失败返回 None。
        """
        if self._reranker is not None:
            return None if self._reranker is False else self._reranker
        try:
            from FlagEmbedding import FlagReranker

            self._reranker = FlagReranker(model_path, use_fp16=True)
            self._load_error = None
            logger.info(
                "bge-reranker 重排模型加载完成",
                extra={"model": model_path},
            )
        except Exception as err:
            self._load_error = str(err)
            self._reranker = False
            logger.error(
                "bge-reranker 重排模型加载失败",
                extra={"model": model_path, "error": str(err)},
            )
        return None if self._reranker is False else self._reranker

    async def rerank(
        self,
        query: str,
        chunks: list[RetrievedChunk],
        top_k: int | None = None,
        cfg: Any = None,
    ) -> list[RetrievedChunk]:
        """对检索结果做 CrossEncoder 重排。

        Args:
            query: 查询文本（feature + items + methods 拼接）。
            chunks: hybrid_search 返回的 RetrievedChunk 列表。
            top_k: 重排后保留数，None 时使用配置项。
            cfg: ExtractionDomainConfig（重排配置，可为 None）。

        Returns:
            list[RetrievedChunk]: 重排后的 chunks，按 rerank_score 降序。
                禁用 / 模型未加载 / 推理失败时返回原始 chunks 截断到 top_k。
        """
        reranker_cfg = cfg.get("retrieval", "reranker") if cfg is not None else {}
        # 保留数：调用方 top_k（类别级 rerank_top_k）→ 全局 reranker.top_n（类别→全局分层）
        _top_k = top_k or reranker_cfg.get("top_n")
        if _top_k is None:
            raise BusinessException("未配置重排保留数 retrieval.reranker.top_n")
        _top_k = int(_top_k)

        # 重排开关（配置驱动，缺失即报错，无 env 兜底）
        enabled = reranker_cfg.get("enabled")
        if enabled is None:
            raise BusinessException("未配置重排开关 retrieval.reranker.enabled")

        if not enabled:
            return chunks[:_top_k]
        if not chunks:
            return []

        # 模型路径（配置驱动；开启时必须配置，缺失即报错，不静默降级）
        model_path = reranker_cfg.get("model")
        if not model_path:
            raise BusinessException("重排已开启但未配置模型路径 retrieval.reranker.model")
        model = self._load(model_path)
        if model is None:
            raise BusinessException(f"重排模型不可用：{self._load_error}")

        # 计算 (query, content) 重排分数（同步推理，用 to_thread 避免阻塞事件循环）
        pairs = [[query, c.content] for c in chunks]
        try:
            scores = await asyncio.to_thread(model.compute_score, pairs)
        except Exception as err:
            logger.warning(
                "重排推理失败，降级返回原始结果",
                extra={"error": str(err)},
            )
            return chunks[:_top_k]

        # scores 可能是标量（单条）或列表
        if isinstance(scores, (int, float)):
            scores = [scores] * len(chunks)

        # 按分数降序取 top_k，更新 score 为 rerank_score
        scored = sorted(zip(chunks, scores), key=lambda x: float(x[1]), reverse=True)
        reranked: list[RetrievedChunk] = []
        for chunk, score in scored[:_top_k]:
            reranked.append(RetrievedChunk(
                chunk_id=chunk.chunk_id,
                score=float(score),
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