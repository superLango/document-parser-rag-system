"""五维 query 向量编码器（Phase 2/3 共用）。

将 feature（项目大类）及其 items/methods 编码为五维 query 向量，
供 ``FiveDimVectorStore.hybrid_search`` 多路召回使用。

五维 query 文本构造（**feature + 精简 item + 精简 method 作为查询条件**，提升召回准确率）：
- **path**：feature + 精简 items 前 8 + 精简 methods 前 3（匹配层级路径）
- **title**：feature + 精简 items 前 8 + 精简 methods 前 3（匹配章节标题）
- **content**：feature + 精简 items 前 30 + methods 前 8（主检索维度，
  截断 2000 字符避免过长）
- **type**："表格 数据结构 行列"（偏向表格块，材料标准文档以表格为主）
- **structural**：feature + 精简 items 前 8 + 精简 methods 前 3（匹配结构位置）

精简规则（``_refine_item_name``）：去括号符号（"抗拉强度(Rm)"→"抗拉强度"）、
去方法后缀（"晶间腐蚀-方法A"→"晶间腐蚀"）、过滤纯代号（"Z35"），保留核心语义。

性能优化：5 个维度文本通过 1 次 ``embedding_service.embed`` 调用批量编码，
利用 bge-m3 批量推理加速。``return_sparse=False`` 跳过 sparse 计算。

使用示例::

    from app.services.extraction.query_embedder import query_embedder

    # Phase 2 类别检索
    query_vectors = await query_embedder.encode_category_query(
        feature="化学成分",
        items=["C", "Si", "Mn", "P", "S", ...],
        methods=["GB/T 223.7-2002", ...],
    )
    hits = await five_dim_vector_store.hybrid_search(query_vectors, doc_id, top_k=5)

    # Phase 3 类别内检索（复用同一 query，增大 top_k）
    hits = await five_dim_vector_store.hybrid_search(query_vectors, doc_id, top_k=20)
"""

from __future__ import annotations

import logging
import re
from typing import Any

import numpy as np

from app.core.logging import get_logger
from app.services.embedding.embedding_service import embedding_service

logger = get_logger(__name__)

# 五维维度名称（与 vector_store.DIMENSIONS 一致）
_DIMENSIONS = ["path", "title", "content", "type", "structural"]

# content 维度 query 截断长度（避免 items+methods 过长导致 embed 耗时）
_CONTENT_QUERY_MAX_CHARS = 2000

# content 维度 query 中 items 和 methods 的截取数量
# items 限制 15 个：避免化学成分等大类（137 个元素符号）淹没 feature 语义
_MAX_ITEMS_IN_QUERY = 15
_MAX_METHODS_IN_QUERY = 5

# path/title/structural 维度 query 中精简 items 的截取数量（核心语义）
_MAX_ITEMS_IN_PATH_QUERY = 8
# path/title/structural 维度 query 中精简 methods 的截取数量
_MAX_METHODS_IN_PATH_QUERY = 3

# content query 中 feature 名重复次数（增强 feature 语义权重，避免被 item 符号淹没）
_FEATURE_REPEAT_IN_CONTENT = 2


class QueryEmbedder:
    """五维 query 向量编码器。

    所有方法均为异步，通过 ``embedding_service.embed`` 批量编码。
    5 个维度文本通过 1 次 embed 调用完成，减少锁竞争。
    """

    async def encode_category_query(
        self,
        feature: str,
        items: list[str] | None = None,
        methods: list[str] | None = None,
    ) -> dict[str, list[float]]:
        """编码五维 query 向量（Phase 2 类别检索 / Phase 3 类别内检索共用）。

        Args:
            feature: 项目大类名（如 "化学成分"）。
            items: 该 feature 的标准项目名列表（取前 30 个拼入 content query）。
            methods: 该 feature 的方法名列表（取前 8 个拼入 content query）。

        Returns:
            dict: 五维 query 向量，形如
                ``{"path": [1024], "title": [...], "content": [...], ...}``。
                每个值为 list[float]（长度 1024），已归一化。
        """
        items = items or []
        methods = methods or []

        # 构造五维 query 文本
        texts = self._build_query_texts(feature, items, methods)

        # 1 次 embed 调用编码 5 个文本（return_sparse=False 跳过 sparse 计算）
        # max_length=2048：path/title/type/structural 极短，content 截断 2000 字符
        result = await embedding_service.embed(
            texts,
            return_sparse=False,
            max_length=2048,
        )
        dense_vectors: np.ndarray = result["dense_vectors"]  # (5, 1024)

        # 组装为维度→向量字典
        query_vectors: dict[str, list[float]] = {}
        for dim, vec in zip(_DIMENSIONS, dense_vectors):
            query_vectors[dim] = vec.tolist()

        logger.debug(
            "五维 query 编码完成",
            extra={
                "feature": feature,
                "items_count": len(items),
                "methods_count": len(methods),
            },
        )
        return query_vectors

    async def encode_text_query(
        self,
        text: str,
    ) -> dict[str, list[float]]:
        """将单个文本编码为五维 query 向量（通用检索场景）。

        所有维度使用同一文本编码，适用于文档基本信息抽取等
        不依赖 feature/items/methods 的检索场景。

        Args:
            text: 查询文本。

        Returns:
            dict: 五维 query 向量。
        """
        result = await embedding_service.embed(
            [text] * 5,
            return_sparse=False,
            max_length=2048,
        )
        dense_vectors: np.ndarray = result["dense_vectors"]

        return {dim: vec.tolist() for dim, vec in zip(_DIMENSIONS, dense_vectors)}

    async def encode_batch(
        self,
        queries: list[tuple[str, list[str], list[str]]],
    ) -> list[dict[str, list[float]]]:
        """批量编码多个 feature 的五维 query 向量（Phase 2 并行优化）。

        将多个 feature 的 query 文本合并为一次 embed 调用，减少锁竞争。
        适用于 Phase 2 需要对全量 feature 编码的场景。

        Args:
            queries: 列表，每项为 (feature, items, methods) 元组。

        Returns:
            list[dict]: 每个元素为一个 feature 的五维 query 向量字典。
        """
        if not queries:
            return []

        # 构造所有 feature 的五维文本（合并为一个大列表）
        all_texts: list[str] = []
        for feature, items, methods in queries:
            texts = self._build_query_texts(feature, items or [], methods or [])
            all_texts.extend(texts)

        # 1 次 embed 调用编码全部文本
        result = await embedding_service.embed(
            all_texts,
            return_sparse=False,
            max_length=2048,
        )
        dense_vectors: np.ndarray = result["dense_vectors"]

        # 按每个 feature 5 个维度切分
        batch_vectors: list[dict[str, list[float]]] = []
        for i in range(len(queries)):
            start = i * 5
            end = start + 5
            feature_vectors = dense_vectors[start:end]
            batch_vectors.append(
                {dim: vec.tolist() for dim, vec in zip(_DIMENSIONS, feature_vectors)}
            )

        logger.info(
            "批量五维 query 编码完成",
            extra={"feature_count": len(queries), "total_texts": len(all_texts)},
        )
        return batch_vectors

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    @staticmethod
    def _build_query_texts(
        feature: str,
        items: list[str],
        methods: list[str],
    ) -> list[str]:
        """构造五维 query 文本列表（顺序与 _DIMENSIONS 一致）。

        使用 **feature + 精简 item + 精简 method** 作为查询条件，提升召回准确率：
        - path/title/structural: feature + 精简 items 前 8 + 精简 methods 前 3
        - content: feature 重复2次 + 精简 items 前 15 + methods 前 5（主检索维度）
          feature 重复增强语义权重，避免化学成分等大类的元素符号淹没 feature 语义
        - type: "表格 数据结构 行列"（偏向表格块）

        Args:
            feature: 项目大类名。
            items: 标准项目名列表。
            methods: 方法名列表。

        Returns:
            list[str]: 五维 query 文本，顺序为 [path, title, content, type, structural]。
        """
        # 精简 items（去括号符号、去方法后缀、过滤纯代号、去重）
        refined_items_short = QueryEmbedder._refine_items(items, limit=_MAX_ITEMS_IN_PATH_QUERY)
        refined_items_long = QueryEmbedder._refine_items(items, limit=_MAX_ITEMS_IN_QUERY)

        # 精简 methods（去括号，取前 N 个，去重）
        refined_methods_short = QueryEmbedder._refine_methods(methods, limit=_MAX_METHODS_IN_PATH_QUERY)
        refined_methods_long = QueryEmbedder._refine_methods(methods, limit=_MAX_METHODS_IN_QUERY)

        # path/title/structural: feature + 精简 items 前 8 + 精简 methods 前 3
        structural_query = f"{feature} {' '.join(refined_items_short)} {' '.join(refined_methods_short)}".strip()

        # content: feature 重复2次 + 精简 items 前 15 + methods 前 5（主检索维度）
        # feature 重复增强语义权重，避免 item 符号（如化学元素 Sr/V/Be）淹没 feature 语义
        feature_part = " ".join([feature] * _FEATURE_REPEAT_IN_CONTENT)
        content_query = f"{feature_part} {' '.join(refined_items_long)} {' '.join(refined_methods_long)}".strip()
        if len(content_query) > _CONTENT_QUERY_MAX_CHARS:
            content_query = content_query[:_CONTENT_QUERY_MAX_CHARS]

        return [
            structural_query,        # path
            structural_query,        # title
            content_query,           # content
            "表格 数据结构 行列",     # type（偏向表格块）
            structural_query,        # structural
        ]

    @staticmethod
    def _refine_item_name(name: str) -> str:
        """精简 item 名称，去掉符号/编号/括号，保留核心语义。

        规则：
        1. 去掉中文/英文括号及内容（如 "(Rm)"、"(Rp0.2)"、"(lateral expansion)"）
        2. 去掉 "-方法X" 后缀（如 "晶间腐蚀-方法A" → "晶间腐蚀"）
        3. strip 空白

        Args:
            name: 原始 item 名称。

        Returns:
            str: 精简后的 item 名称。
        """
        if not name:
            return ""
        # 去括号及内容
        refined = re.sub(r"[（(].*?[）)]", "", name)
        # 去 -方法X 后缀
        refined = re.sub(r"-方法[A-Za-z]$", "", refined)
        return refined.strip()

    @staticmethod
    def _refine_items(items: list[str], limit: int) -> list[str]:
        """精简 item 列表：精简名称 + 过滤代号 + 精确去重 + 语义相似度去重 + 取前 limit 个。

        语义去重规则（保留意思差异大的，去除意思大致相同的）：
        1. 精确去重：精简后名称完全相同
        2. 包含去重：A 是 B 的子串（如 "非金属夹杂" ⊂ "非金属夹杂物"），保留较长的
        3. 相似度去重：字符级相似度 >= 0.85（如 "布氏硬度值" vs "布氏硬度"）
           使用 difflib.SequenceMatcher，避免 O(n²) embedding 计算

        Args:
            items: 原始 item 名称列表。
            limit: 最多保留的 item 数量。

        Returns:
            list[str]: 精简后的 item 名称列表。
        """
        import difflib

        seen: set[str] = set()
        result: list[str] = []
        for name in items:
            refined = QueryEmbedder._refine_item_name(name)
            if not refined:
                continue
            # 过滤纯代号（如 Z35、Z25，非核心语义）
            if re.match(r"^[A-Z]\d+", refined):
                continue
            if refined in seen:
                continue

            # 语义相似度去重：检查是否与已保留的 item 高度相似
            is_dup = False
            for existing in result:
                # 包含关系：短的是长的子串 → 意思大致相同
                if refined in existing or existing in refined:
                    is_dup = True
                    break
                # 字符级相似度 >= 0.85 → 意思大致相同
                # （"室温拉伸" vs "高温拉伸" ratio≈0.75 不会被去重，保留差异大的）
                ratio = difflib.SequenceMatcher(None, refined, existing).ratio()
                if ratio >= 0.85:
                    is_dup = True
                    break

            if is_dup:
                continue

            seen.add(refined)
            result.append(refined)
            if len(result) >= limit:
                break
        return result

    @staticmethod
    def _refine_methods(methods: list[str], limit: int) -> list[str]:
        """精简 method 列表：去括号 + 精确去重 + 语义相似度去重 + 取前 limit 个。

        复用 ``_refine_item_name`` 去括号（method 也可能含括号，如
        "火花放电原子发射光谱法（常规法）" → "火花放电原子发射光谱法"）。
        同时做语义相似度去重，避免意思相同的方法重复占据 query 权重。

        Args:
            methods: 原始 method 名称列表。
            limit: 最多保留的 method 数量。

        Returns:
            list[str]: 精简后的 method 名称列表。
        """
        import difflib

        seen: set[str] = set()
        result: list[str] = []
        for name in methods:
            refined = QueryEmbedder._refine_item_name(name)
            if not refined:
                continue
            if refined in seen:
                continue

            # 语义相似度去重
            is_dup = False
            for existing in result:
                if refined in existing or existing in refined:
                    is_dup = True
                    break
                ratio = difflib.SequenceMatcher(None, refined, existing).ratio()
                if ratio >= 0.85:
                    is_dup = True
                    break

            if is_dup:
                continue

            seen.add(refined)
            result.append(refined)
            if len(result) >= limit:
                break
        return result


# 模块级单例
query_embedder = QueryEmbedder()
