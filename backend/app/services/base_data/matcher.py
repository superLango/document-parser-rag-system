"""项目名归一化匹配器（v3 新建）。

用于抽取后处理阶段，将 LLM 输出的项目名归一化到基础表标准项目名，
避免因符号格式问题（如 Rp0.2 vs Rp0.2 vs Rp0．2）导致匹配不到。

匹配优先级（用户要求向量匹配优先，避免符号匹配的语义歧义）：
1. **向量匹配**：bge-m3 相似度 >= 0.90（调用 base_data_store.search_by_feature）
   —— 同一符号（如 Rp0.2）在 sm_item 表中可能对应多个语义不同的项目，
      字面匹配（精确/别名/编辑距离）无法区分，需通过语义向量匹配。
2. **精确匹配**：name == item.name（向量匹配失败时的 fallback）
3. **别名匹配**：name in item.aliases
4. **编辑距离匹配**：相似度 > 0.85（处理符号格式差异）
5. **无匹配**：返回原值，标记 unverified

使用示例::

    from app.services.base_data import item_matcher

    # 向量优先匹配（推荐，需提供 query_vector + feature）
    canonical, score, match_type = await item_matcher.match_vector_first(
        name="Rp0.2", query_vector=vec, feature="室温拉伸", items=items
    )

    # 纯轻量匹配（无需向量，仅 fallback 场景）
    canonical, score, match_type = item_matcher.match("Rp0.2", items)

    # 纯向量匹配（需要 query_vector）
    hits = await item_matcher.match_by_vector(query_vector, feature="室温拉伸")
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from app.services.base_data.store import base_data_store

logger = logging.getLogger(__name__)

# 匹配阈值
_EDIT_DISTANCE_THRESHOLD = 0.85  # 编辑距离相似度阈值
_VECTOR_SIM_THRESHOLD = 0.90  # 向量相似度阈值


class ItemMatcher:
    """项目名归一化匹配器。

    提供三级匹配能力：
    - **向量优先匹配**（match_vector_first）：向量匹配优先，失败 fallback 到轻量匹配
      —— 推荐入口，解决符号匹配的语义歧义（同符号对应多语义项目）
    - **轻量匹配**（match）：精确 + 别名 + 编辑距离，无需向量，速度快
    - **向量匹配**（match_by_vector）：调用 Milvus 检索，处理语义相似但字面差异大的情况

    匹配优先级：向量 > 精确 > 别名 > 编辑距离 > 无匹配。
    """

    async def match_vector_first(
        self,
        name: str,
        query_vector: np.ndarray,
        feature: str,
        items: list[dict[str, Any]],
        top_k: int = 1,
    ) -> tuple[str, float, str]:
        """向量优先匹配：先向量匹配，失败则 fallback 到轻量匹配。

        用户要求优先使用向量匹配，因为符号匹配（精确/别名/编辑距离）
        存在语义歧义问题——拉伸中同一符号可能对应 sm_item 表中多个
        语义不同的项目，字面匹配无法区分，需通过语义向量匹配。

        匹配优先级：
        1. 向量匹配：bge-m3 相似度 >= 0.90（调用 base_data_store.search_by_feature）
        2. 精确匹配：name == item.name
        3. 别名匹配：name in item.aliases
        4. 编辑距离匹配：相似度 > 0.85
        5. 无匹配：返回原值，标记 unverified

        Args:
            name: 待匹配的项目名（LLM 输出）。
            query_vector: name 的 bge-m3 向量 (1024,)，已归一化。
            feature: 限定向量检索的项目大类。
            items: 该 feature 的 sm_item 字典列表（fallback 轻量匹配用）。
            top_k: 向量检索返回数。

        Returns:
            tuple: (canonical_name, score, match_type)
                match_type: "vector" / "exact" / "alias" / "edit_distance" / "unverified"
        """
        if not name or not name.strip():
            return name, 0.0, "unverified"

        name_clean = name.strip()

        # 1. 向量匹配（优先）
        try:
            hits = await self.match_by_vector(
                query_vector=query_vector,
                feature=feature,
                top_k=top_k,
            )
        except Exception as err:
            logger.warning(
                "向量匹配异常，fallback 到轻量匹配",
                extra={"name": name_clean, "feature": feature, "error": str(err)},
            )
            hits = []

        if hits:
            top1 = hits[0]
            if top1.get("matched") and top1.get("canonical_name"):
                return top1["canonical_name"], float(top1["score"]), "vector"

        # 2. fallback 到轻量匹配
        return self.match(name_clean, items)

    def match(
        self,
        name: str,
        items: list[dict[str, Any]],
    ) -> tuple[str, float, str]:
        """轻量匹配：精确 + 别名 + 编辑距离。

        Args:
            name: 待匹配的项目名（LLM 输出）。
            items: 该 feature 的 sm_item 字典列表，每项含
                name/canonical_name/aliases/unit。

        Returns:
            tuple: (canonical_name, score, match_type)
                - canonical_name: 匹配到的标准项目名（无匹配返回原值）
                - score: 匹配置信度（0.0-1.0）
                - match_type: "exact" / "alias" / "edit_distance" / "unverified"
        """
        if not name or not name.strip():
            return name, 0.0, "unverified"

        name_clean = name.strip()

        # 1. 精确匹配
        for item in items:
            canonical = item.get("canonical_name") or item.get("name", "")
            if canonical and canonical == name_clean:
                return canonical, 1.0, "exact"

        # 2. 别名匹配
        for item in items:
            aliases = item.get("aliases", []) or []
            canonical = item.get("canonical_name") or item.get("name", "")
            if name_clean in aliases:
                return canonical, 0.95, "alias"

        # 3. 编辑距离匹配
        best_name = name_clean
        best_score = 0.0
        for item in items:
            canonical = item.get("canonical_name") or item.get("name", "")
            if not canonical:
                continue
            sim = self._edit_similarity(name_clean, canonical)
            if sim > best_score:
                best_score = sim
                best_name = canonical
            # 也检查别名
            for alias in item.get("aliases", []) or []:
                sim = self._edit_similarity(name_clean, alias)
                if sim > best_score:
                    best_score = sim
                    best_name = canonical

        if best_score >= _EDIT_DISTANCE_THRESHOLD:
            return best_name, best_score, "edit_distance"

        # 4. 无匹配
        return name_clean, best_score, "unverified"

    async def match_by_vector(
        self,
        query_vector: np.ndarray,
        feature: str,
        top_k: int = 1,
    ) -> list[dict[str, Any]]:
        """向量匹配：调用 base_data_store 在指定 feature 内检索。

        用于处理语义相似但字面差异大的情况（如 "规定非比例延伸强度" vs "Rp0.2"）。

        Args:
            query_vector: 待匹配项目名的 bge-m3 向量 (1024,)。
            feature: 限定检索的项目大类。
            top_k: 返回结果数。

        Returns:
            list[dict]: 匹配结果列表，每项含
                canonical_name/feature/aliases/unit/score。
                score >= _VECTOR_SIM_THRESHOLD 视为匹配成功。
        """
        hits = await base_data_store.search_by_feature(
            query_vector=query_vector,
            feature=feature,
            top_k=top_k,
        )
        # 标记是否达到向量匹配阈值
        for hit in hits:
            hit["matched"] = hit["score"] >= _VECTOR_SIM_THRESHOLD
        return hits

    # ------------------------------------------------------------------
    # 编辑距离计算
    # ------------------------------------------------------------------

    @staticmethod
    def _edit_similarity(s1: str, s2: str) -> float:
        """计算编辑距离相似度（1 - distance/max_len）。

        Args:
            s1: 字符串 1。
            s2: 字符串 2。

        Returns:
            float: 相似度（0.0-1.0），1.0 表示完全相同。
        """
        if not s1 and not s2:
            return 1.0
        if not s1 or not s2:
            return 0.0

        # 归一化：去除空格、统一大小写、统一全角半角
        s1_norm = ItemMatcher._normalize_str(s1)
        s2_norm = ItemMatcher._normalize_str(s2)

        if s1_norm == s2_norm:
            return 1.0

        max_len = max(len(s1_norm), len(s2_norm))
        distance = ItemMatcher._levenshtein(s1_norm, s2_norm)
        return 1.0 - distance / max_len

    @staticmethod
    def _levenshtein(s1: str, s2: str) -> int:
        """计算 Levenshtein 编辑距离。"""
        if len(s1) < len(s2):
            return ItemMatcher._levenshtein(s2, s1)
        if len(s2) == 0:
            return len(s1)

        previous_row = range(len(s2) + 1)
        for i, c1 in enumerate(s1):
            current_row = [i + 1]
            for j, c2 in enumerate(s2):
                # 插入、删除、替换
                insertions = previous_row[j + 1] + 1
                deletions = current_row[j] + 1
                substitutions = previous_row[j] + (c1 != c2)
                current_row.append(min(insertions, deletions, substitutions))
            previous_row = current_row

        return previous_row[-1]

    @staticmethod
    def _normalize_str(s: str) -> str:
        """归一化字符串：去除空格、统一大小写、统一全角半角。"""
        # 全角→半角
        result = []
        for c in s:
            code = ord(c)
            if code == 0x3000:  # 全角空格
                result.append(" ")
            elif 0xFF01 <= code <= 0xFF5E:  # 全角字符
                result.append(chr(code - 0xFEE0))
            else:
                result.append(c)
        # 去除空格、统一小写
        return "".join(result).replace(" ", "").lower()


# 模块级单例
item_matcher = ItemMatcher()
