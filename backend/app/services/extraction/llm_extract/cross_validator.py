"""跨类校验器（Phase 4 后处理）。

对抽取记录的"项目名称"字段做跨类校验，剔除跨类混入的记录。

校验流程：
1. 将记录的"项目名称"向量化（bge-m3）
2. 调用 base_data_store.search 全表检索 top-1
3. top-1.feature == 当前 feature → 保留
4. top-1.feature != 当前 feature → 标记跨类混入，剔除
5. score < 阈值 → 标记 _unverified，保留
6. 无检索结果 → fallback 到 item 白名单校验：
   项目名不在当前 feature 的 item 列表（含别名）中则剔除

使用示例::

    from app.services.extraction.llm_extract.cross_validator import cross_validator

    kept, rejected = await cross_validator.validate(records, target)
"""

from __future__ import annotations

import asyncio
import difflib
import logging
from typing import Any

import numpy as np

from app.core.logging import get_logger
from app.services.base_data.store import base_data_store
from app.services.embedding.embedding_service import embedding_service
from app.services.extraction.extraction_config import get_extraction_settings
from app.services.extraction.extraction_models import ExtractedRecord, ExtractionTarget

logger = get_logger(__name__)

# 批量向量化的批次大小
_BATCH_SIZE = 32

# item 白名单 fallback 校验的相似度阈值
# 提高到 0.90：蠕变/持久等项目名高度相似时，0.75 阈值过于宽松导致跨类混入
_WHITELIST_SIMILARITY_THRESHOLD = 0.90


class CrossValidator:
    """跨类校验器。

    通过 base_data_store 向量检索判断项目名是否属于当前 feature。
    当向量库无数据时，fallback 到 item 白名单校验。
    """

    def __init__(self) -> None:
        self._settings = get_extraction_settings()

    async def validate(
        self,
        records: list[ExtractedRecord],
        target: ExtractionTarget,
    ) -> tuple[list[ExtractedRecord], list[ExtractedRecord]]:
        """对记录做跨类校验。

        Args:
            records: 待校验的记录列表。
            target: 抽取目标（含 items 白名单用于 fallback 校验）。

        Returns:
            tuple: (kept_records, rejected_records)
                - kept_records: 通过校验的记录（含 _unverified 标记的）
                - rejected_records: 被剔除的记录（跨类混入）
        """
        if not records:
            return [], []

        feature = target.feature

        # 提取项目名
        item_names = [r.data.get("项目名称", "") for r in records]
        valid_indices = [i for i, name in enumerate(item_names) if name]

        if not valid_indices:
            # 无项目名字段，全部保留
            return records, []

        # 构建 item 白名单集合（含别名），用于 fallback 校验
        whitelist = self._build_item_whitelist(target)

        # 批量向量化项目名
        valid_names = [item_names[i] for i in valid_indices]
        vectors = await self._embed_batch(valid_names)

        # 并发检索 base_data_store
        search_results = await self._search_batch(vectors)

        # 校验每条记录
        kept: list[ExtractedRecord] = []
        rejected: list[ExtractedRecord] = []

        for idx, record in enumerate(records):
            if idx not in valid_indices:
                # 无项目名，保留
                kept.append(record)
                continue

            search_idx = valid_indices.index(idx)
            hits = search_results[search_idx] if search_idx < len(search_results) else []

            if not hits:
                # 无检索结果，fallback 到 item 白名单校验
                item_name = record.data.get("项目名称", "")
                if self._is_in_whitelist(item_name, whitelist):
                    # 在白名单中，保留但标记 unverified
                    record._unverified = True
                    record._reject_reason = "跨类校验无检索结果（白名单通过）"
                    kept.append(record)
                else:
                    # 不在白名单中，说明是跨类混入，剔除
                    record._reject_reason = (
                        f"跨类混入（{item_name} 不属于 {feature}，白名单校验失败）"
                    )
                    rejected.append(record)
                continue

            top1 = hits[0]
            top1_feature = top1.get("feature", "")
            top1_score = top1.get("score", 0.0)

            if top1_score < self._settings.cross_validate_threshold:
                # 置信度过低，标记 unverified 保留
                record._unverified = True
                record._reject_reason = f"跨类校验置信度低（{top1_score:.4f}）"
                kept.append(record)
            elif top1_feature and top1_feature != feature:
                # 跨类混入，剔除
                record._reject_reason = f"跨类混入（{top1_feature} ≠ {feature}）"
                rejected.append(record)
            else:
                # 通过校验
                kept.append(record)

        logger.info(
            "跨类校验完成",
            extra={
                "feature": feature,
                "total": len(records),
                "kept": len(kept),
                "rejected": len(rejected),
                "unverified": sum(1 for r in kept if r._unverified),
            },
        )
        return kept, rejected

    @staticmethod
    def _build_item_whitelist(target: ExtractionTarget) -> set[str]:
        """构建 item 白名单集合（含标准名和别名）。

        Args:
            target: 抽取目标。

        Returns:
            set[str]: 白名单集合。
        """
        whitelist: set[str] = set()
        for item in target.items:
            if item.name:
                whitelist.add(item.name)
            for alias in item.aliases:
                whitelist.add(alias)
        return whitelist

    @staticmethod
    def _is_in_whitelist(item_name: str, whitelist: set[str]) -> bool:
        """检查项目名是否在白名单中（严格匹配）。

        匹配规则：
        1. 精确匹配
        2. 字符级相似度 >= 0.90（高阈值，避免蠕变/持久等相似项目跨类混入）

        **已移除子串匹配**：子串匹配（item_name in w 或 w in item_name）过于宽松，
        例如"持久时间"包含"持久"会导致蠕变类别的"持久时间"项目通过持久类别校验，
        反之亦然。移除后仅允许精确匹配或高相似度匹配。

        Args:
            item_name: 待检查的项目名。
            whitelist: 白名单集合。

        Returns:
            bool: 是否在白名单中。
        """
        if not item_name or not whitelist:
            return False

        # 精确匹配
        if item_name in whitelist:
            return True

        # 高阈值相似度匹配（0.90，避免相似项目跨类混入）
        for w in whitelist:
            ratio = difflib.SequenceMatcher(None, item_name, w).ratio()
            if ratio >= _WHITELIST_SIMILARITY_THRESHOLD:
                return True

        return False

    async def _embed_batch(self, texts: list[str]) -> list[np.ndarray]:
        """批量向量化文本。

        Args:
            texts: 文本列表。

        Returns:
            list[np.ndarray]: 向量列表。
        """
        all_vectors: list[np.ndarray] = []
        for i in range(0, len(texts), _BATCH_SIZE):
            batch = texts[i : i + _BATCH_SIZE]
            result = await embedding_service.embed(batch, return_sparse=False, max_length=512)
            for v in result["dense_vectors"]:
                all_vectors.append(v)
        return all_vectors

    async def _search_batch(
        self,
        vectors: list[np.ndarray],
    ) -> list[list[dict[str, Any]]]:
        """批量检索 base_data_store。

        Args:
            vectors: 查询向量列表。

        Returns:
            list[list[dict]]: 每个向量的检索结果列表。
        """
        async def search_one(vec: np.ndarray) -> list[dict[str, Any]]:
            try:
                return await base_data_store.search(query_vector=vec, top_k=1)
            except Exception as err:
                logger.warning("base_data_store 检索失败", extra={"error": str(err)})
                return []

        # 限制并发数
        semaphore = asyncio.Semaphore(10)

        async def search_with_sem(vec: np.ndarray) -> list[dict[str, Any]]:
            async with semaphore:
                return await search_one(vec)

        return await asyncio.gather(*[search_with_sem(v) for v in vectors])


# 模块级单例
cross_validator = CrossValidator()
