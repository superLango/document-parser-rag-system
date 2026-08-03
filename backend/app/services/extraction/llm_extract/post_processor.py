"""后处理器（Phase 4 后处理）。

对 LLM 抽取的记录做后处理：
1. **项目名归一化**：向量匹配优先（bge-m3 语义匹配，解决符号歧义），
   失败 fallback 到轻量匹配（精确+别名+编辑距离）
2. **方法年代号处理**：有年代号保留，无年代号从方法列表取最新
3. **温度分类修正**：高温/低温拉伸中剔除温度不匹配的记录
4. **跨类校验**：调用 cross_validator 剔除跨类混入
5. **去重**：精确去重（字段哈希）+ 模糊去重（向量相似度）

使用示例::

    from app.services.extraction.llm_extract.post_processor import post_processor

    kept, rejected = await post_processor.process(records, target)
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from typing import Any

import numpy as np

from app.core.logging import get_logger
from app.services.base_data.matcher import item_matcher
from app.services.embedding.embedding_service import embedding_service
from app.services.extraction.extraction_config import get_extraction_settings
from app.services.extraction.extraction_models import (
    ExtractionTarget,
    ExtractedRecord,
)
from app.services.extraction.llm_extract.cross_validator import cross_validator

logger = get_logger(__name__)

# 需要温度过滤的类别（试验温度是区分类别的关键字段）
_TEMP_SENSITIVE_FEATURES = {"高温拉伸", "低温拉伸"}

# 室温关键词（匹配到则为室温，不属于高温/低温）
_ROOM_TEMP_KEYWORDS = {"室温", "常温", "room", "rt", "20℃", "23℃", "25℃"}

# 项目名归一化：批量向量化的批次大小
_NORMALIZE_BATCH_SIZE = 32
# 项目名归一化：向量检索并发数
_NORMALIZE_SEARCH_CONCURRENCY = 10


class PostProcessor:
    """后处理器。

    编排归一化 → 年代号处理 → 温度修正 → 跨类校验 → 去重。
    """

    def __init__(self) -> None:
        self._settings = get_extraction_settings()

    async def process(
        self,
        records: list[ExtractedRecord],
        target: ExtractionTarget,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """完整的后处理流程。

        Args:
            records: LLM 抽取的原始记录列表。
            target: 抽取目标（含 items/methods）。

        Returns:
            tuple: (kept_dicts, rejected_dicts)
                - kept_dicts: 通过后处理的记录字典列表
                - rejected_dicts: 被剔除的记录字典列表
        """
        if not records:
            return [], []

        # 1. 项目名归一化（向量匹配优先，失败 fallback 到轻量匹配）
        await self._normalize_item_names_batch(records, target)

        # 2. 方法年代号处理
        for record in records:
            self._normalize_method_year(record, target)

        # 3. 温度分类修正（高温/低温拉伸剔除温度不匹配的记录）
        records, temp_rejected = self._filter_by_temperature(records, target)

        # 4. 跨类校验（传入 target 用于 fallback 白名单校验）
        kept_records, rejected_records = await cross_validator.validate(records, target)

        # 5. 去重
        kept_records = self._dedup(kept_records)

        # 转为输出字典
        kept_dicts = [r.to_dict() for r in kept_records]
        rejected_dicts = [r.to_dict() for r in rejected_records + temp_rejected]

        logger.info(
            "后处理完成",
            extra={
                "feature": target.feature,
                "input": len(records) + len(temp_rejected),
                "kept": len(kept_dicts),
                "rejected": len(rejected_dicts),
                "temp_rejected": len(temp_rejected),
            },
        )
        return kept_dicts, rejected_dicts

    def _filter_by_temperature(
        self,
        records: list[ExtractedRecord],
        target: ExtractionTarget,
    ) -> tuple[list[ExtractedRecord], list[ExtractedRecord]]:
        """温度分类修正：根据试验温度剔除不匹配类别的记录。

        规则（用户要求）：
        - 高温拉伸：剔除试验温度为室温/空/无法识别的记录
        - 低温拉伸：剔除试验温度为室温/空/无法识别的记录
        - 室温拉伸：试验温度为空的记录设为"室温"
        - 其他类别：不做温度过滤

        无法识别温度或文章中未提及温度的全部按室温处理。

        Args:
            records: 待过滤的记录列表。
            target: 抽取目标。

        Returns:
            tuple: (kept_records, rejected_records)
        """
        feature = target.feature

        # 室温拉伸：温度为空的设为"室温"
        if feature == "室温拉伸":
            for record in records:
                temp = record.data.get("试验温度", "").strip()
                if not temp:
                    record.data["试验温度"] = "室温"
            return records, []

        # 非温度敏感类别：不过滤
        if feature not in _TEMP_SENSITIVE_FEATURES:
            return records, []

        # 高温/低温拉伸：剔除温度不匹配的记录
        kept: list[ExtractedRecord] = []
        rejected: list[ExtractedRecord] = []

        for record in records:
            temp = record.data.get("试验温度", "").strip()

            # 温度为空 → 按室温处理，不属于高温/低温
            if not temp:
                record._reject_reason = f"温度为空，按室温处理，不属于{feature}"
                rejected.append(record)
                continue

            # 温度匹配室温关键词 → 不属于高温/低温
            temp_lower = temp.lower()
            if any(kw in temp_lower for kw in _ROOM_TEMP_KEYWORDS):
                record._reject_reason = f"温度为室温（{temp}），不属于{feature}"
                rejected.append(record)
                continue

            # 提取温度数值，判断属于高温还是低温
            temp_match = re.search(r"-?\d+", temp)
            if temp_match:
                temp_val = int(temp_match.group())
                if feature == "高温拉伸" and temp_val > 100:
                    # 高温（>100℃）→ 保留在高温拉伸
                    kept.append(record)
                elif feature == "低温拉伸" and temp_val < 0:
                    # 低温（<0℃）→ 保留在低温拉伸
                    kept.append(record)
                else:
                    record._reject_reason = (
                        f"温度{temp}不匹配{feature}（数值{temp_val}不在范围）"
                    )
                    rejected.append(record)
            else:
                # 无法提取温度数值 → 按室温处理，不属于高温/低温
                record._reject_reason = f"温度无法识别（{temp}），按室温处理，不属于{feature}"
                rejected.append(record)

        if rejected:
            logger.info(
                "温度分类修正",
                extra={
                    "feature": feature,
                    "input": len(records),
                    "kept": len(kept),
                    "rejected": len(rejected),
                },
            )

        return kept, rejected

    async def _normalize_item_names_batch(
        self,
        records: list[ExtractedRecord],
        target: ExtractionTarget,
    ) -> None:
        """批量项目名归一化（向量匹配优先，轻量匹配 fallback）。

        用户要求优先使用向量匹配：同一符号（如 Rp0.2）在 sm_item 表中可能
        对应多个语义不同的项目，字面匹配（精确/别名/编辑距离）无法区分，
        需通过语义向量匹配在限定 feature 内确定最合适的标准项目名。

        流程：
        1. 收集所有非空项目名，批量向量化（bge-m3）
        2. 批量在当前 feature 内向量检索（base_data_store.search_by_feature）
        3. 向量匹配 score >= 阈值 → 用 canonical_name 归一化（标记 vector）
        4. 向量匹配失败 → fallback 到轻量匹配（精确+别名+编辑距离）

        Args:
            records: 待处理的记录列表（原地修改 data["项目名称"]）。
            target: 抽取目标（含 items 用于 fallback 轻量匹配）。
        """
        feature = target.feature
        items_dicts = [it.to_dict() for it in target.items]

        # 收集所有非空项目名
        names_to_embed: list[str] = []
        name_indices: list[int] = []
        for idx, record in enumerate(records):
            name = record.data.get("项目名称", "")
            if name and name.strip():
                names_to_embed.append(name.strip())
                name_indices.append(idx)

        if not names_to_embed:
            return

        # 批量向量化项目名
        vectors = await self._embed_item_names(names_to_embed)

        # 批量在当前 feature 内向量检索
        search_results = await self._search_items_by_feature(vectors, feature)

        # 对每条记录做归一化：向量匹配优先，失败 fallback 到轻量匹配
        vector_matched = 0
        fallback_matched = 0
        for i, idx in enumerate(name_indices):
            record = records[idx]
            hits = search_results[i] if i < len(search_results) else []

            # 向量匹配优先
            if hits:
                top1 = hits[0]
                if top1.get("matched") and top1.get("canonical_name"):
                    record.data["项目名称"] = top1["canonical_name"]
                    record.data["_normalize_score"] = round(float(top1["score"]), 4)
                    record.data["_normalize_type"] = "vector"
                    vector_matched += 1
                    continue

            # fallback 到轻量匹配（精确 + 别名 + 编辑距离）
            name = record.data.get("项目名称", "")
            canonical, score, match_type = item_matcher.match(name, items_dicts)
            if match_type != "unverified":
                record.data["项目名称"] = canonical
                record.data["_normalize_score"] = round(score, 4)
                record.data["_normalize_type"] = match_type
                fallback_matched += 1

        logger.info(
            "项目名归一化完成",
            extra={
                "feature": feature,
                "total": len(names_to_embed),
                "vector_matched": vector_matched,
                "fallback_matched": fallback_matched,
            },
        )

    async def _embed_item_names(
        self,
        names: list[str],
    ) -> list[np.ndarray]:
        """批量向量化项目名（bge-m3）。

        Args:
            names: 项目名文本列表。

        Returns:
            list[np.ndarray]: 归一化后的 dense 向量列表 (1024,)。
        """
        all_vectors: list[np.ndarray] = []
        for i in range(0, len(names), _NORMALIZE_BATCH_SIZE):
            batch = names[i : i + _NORMALIZE_BATCH_SIZE]
            result = await embedding_service.embed(
                batch, return_sparse=False, max_length=512
            )
            for v in result["dense_vectors"]:
                all_vectors.append(v)
        return all_vectors

    async def _search_items_by_feature(
        self,
        vectors: list[np.ndarray],
        feature: str,
    ) -> list[list[dict[str, Any]]]:
        """批量在指定 feature 内向量检索标准项目（用于归一化）。

        通过 item_matcher.match_by_vector 调用 base_data_store.search_by_feature，
        限定在当前 feature 内检索，避免跨类误匹配。

        Args:
            vectors: 项目名向量列表。
            feature: 限定检索的项目大类。

        Returns:
            list[list[dict]]: 每个向量的检索结果列表（含 matched 标记）。
        """
        async def search_one(vec: np.ndarray) -> list[dict[str, Any]]:
            try:
                return await item_matcher.match_by_vector(
                    query_vector=vec,
                    feature=feature,
                    top_k=1,
                )
            except Exception as err:
                logger.warning(
                    "项目名向量检索失败",
                    extra={"error": str(err), "feature": feature},
                )
                return []

        semaphore = asyncio.Semaphore(_NORMALIZE_SEARCH_CONCURRENCY)

        async def search_with_sem(vec: np.ndarray) -> list[dict[str, Any]]:
            async with semaphore:
                return await search_one(vec)

        return await asyncio.gather(*[search_with_sem(v) for v in vectors])

    def _normalize_method_year(
        self,
        record: ExtractedRecord,
        target: ExtractionTarget,
    ) -> None:
        """方法年代号处理。

        规则：
        1. 有年代号（如 "GB/T 228.1-2010"）→ 直接保留
        2. 无年代号（如 "GB/T 228.1"）→ 在 target.methods 找同前缀最新年代号
        3. 无匹配 → 保留原值

        Args:
            record: 待处理的记录。
            target: 抽取目标。
        """
        method = record.data.get("试验方法", "")
        if not method:
            return

        # 检查是否有年代号（四位数字）
        import re
        year_match = re.search(r"[-:](\d{4})$", method)
        if year_match:
            # 有年代号，直接保留
            return

        # 无年代号，从方法列表找同前缀最新年代号
        best_method = self._find_latest_method(method, target.method_codes)
        if best_method:
            record.data["试验方法"] = best_method
            record.data["_method_year_filled"] = True

    @staticmethod
    def _find_latest_method(
        method: str,
        method_codes: list[str],
    ) -> str | None:
        """从方法列表中找同前缀的最新年代号方法。

        Args:
            method: 原始方法名（无年代号）。
            method_codes: 方法标准号列表。

        Returns:
            str | None: 最新年代号方法，无匹配返回 None。
        """
        import re

        # 提取方法前缀（去掉年代号部分）
        method_prefix = re.sub(r"[-:]\d{4}$", "", method).strip()
        if not method_prefix:
            return None

        # 在方法列表中找同前缀的
        candidates: list[str] = []
        for code in method_codes:
            code_prefix = re.sub(r"[-:]\d{4}$", "", code).strip()
            if code_prefix == method_prefix:
                candidates.append(code)

        if not candidates:
            return None

        # 按年代号排序，取最新
        def extract_year(s: str) -> int:
            match = re.search(r"[-:](\d{4})$", s)
            return int(match.group(1)) if match else 0

        candidates.sort(key=extract_year, reverse=True)
        return candidates[0]

    def _dedup(
        self,
        records: list[ExtractedRecord],
    ) -> list[ExtractedRecord]:
        """去重（精确去重 + 模糊去重）。

        精确去重：字段排序后 json.dumps 的 sha256 相同视为重复。
        模糊去重：暂不实现（需要批量向量化，性能开销大）。

        Args:
            records: 待去重的记录列表。

        Returns:
            list[ExtractedRecord]: 去重后的记录列表。
        """
        seen_hashes: set[str] = set()
        deduped: list[ExtractedRecord] = []

        for record in records:
            # 构建去重键（排除内部字段和元数据）
            dedup_data = {
                k: v for k, v in record.data.items()
                if not k.startswith("_")
            }
            dedup_str = json.dumps(dedup_data, sort_keys=True, ensure_ascii=False)
            dedup_hash = hashlib.sha256(dedup_str.encode("utf-8")).hexdigest()

            if dedup_hash in seen_hashes:
                record._reject_reason = "重复记录"
                continue

            seen_hashes.add(dedup_hash)
            deduped.append(record)

        if len(deduped) < len(records):
            logger.info(
                "去重完成",
                extra={
                    "input": len(records),
                    "output": len(deduped),
                    "removed": len(records) - len(deduped),
                },
            )

        return deduped


# 模块级单例
post_processor = PostProcessor()
