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

    from app.services.extraction.retrieval.query_embedder import query_embedder

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
from app.core.exceptions import BusinessException
from app.services.embedding.embedding_service import embedding_service

logger = get_logger(__name__)

# 五维维度名称（与 vector_store.DIMENSIONS 一致）
_DIMENSIONS = ["path", "title", "content", "type", "structural"]


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
        cfg: Any = None,
        query_sources: list[dict] | None = None,
    ) -> dict[str, list[float]]:
        """编码五维 query 向量（Phase 2 类别检索 / Phase 3 类别内检索共用）。

        Args:
            feature: 项目大类名（如 "化学成分"）。
            items: 该 feature 的查询词组（prefixed fixed_query + 术语集值）。
            methods: 方法名列表（当前配置驱动下为空）。
            cfg: ExtractionDomainConfig（五维 query 编码参数，可为 None）。
            query_sources: 类别 Query 术语集配置
                （含 query_main_limit / query_refined_limit 条目上限，可为 None）。

        Returns:
            dict: 五维 query 向量，形如
                ``{"path": [1024], "title": [...], "content": [...], ...}``。
                每个值为 list[float]（长度 1024），已归一化。
        """
        items = items or []
        methods = methods or []
        params = self._query_params(cfg, query_sources)

        # 构造五维 query 文本
        texts = self._build_query_texts(feature, items, methods, params)

        # 1 次 embed 调用编码 5 个文本（return_sparse=False 跳过 sparse 计算）
        # max_length：path/title/type/structural 极短，content 按配置截断
        result = await embedding_service.embed(
            texts,
            return_sparse=False,
            max_length=params["embed_max_length"],
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
        cfg: Any = None,
    ) -> dict[str, list[float]]:
        """将单个文本编码为五维 query 向量（通用检索场景）。

        所有维度使用同一文本编码，适用于文档基本信息抽取等
        不依赖 feature/items/methods 的检索场景。

        Args:
            text: 查询文本。
            cfg: ExtractionDomainConfig（五维 query 编码参数，可为 None）。

        Returns:
            dict: 五维 query 向量。
        """
        result = await embedding_service.embed(
            [text] * 5,
            return_sparse=False,
            max_length=self._query_params(cfg)["embed_max_length"],
        )
        dense_vectors: np.ndarray = result["dense_vectors"]

        return {dim: vec.tolist() for dim, vec in zip(_DIMENSIONS, dense_vectors)}

    async def encode_batch(
        self,
        targets: list[Any],
        cfg: Any = None,
    ) -> list[dict[str, list[float]]]:
        """批量编码多个类别目标的五维 query 向量（Phase 2 并行优化）。

        将多个 feature 的 query 文本合并为一次 embed 调用，减少锁竞争。
        适用于 Phase 2 需要对全量 feature 编码的场景。

        Args:
            targets: 列表，每项为带 ``feature`` / ``query_terms`` / ``query_sources``
                属性的对象（如 ExtractionTarget）。
            cfg: ExtractionDomainConfig（五维 query 编码参数，可为 None）。

        Returns:
            list[dict]: 与 targets 等长的五维 query 向量字典列表。
        """
        if not targets:
            return []

        # 构造所有 feature 的五维文本（合并为一个大列表）
        all_texts: list[str] = []
        for t in targets:
            params = self._query_params(cfg, getattr(t, "query_sources", None))
            texts = self._build_query_texts(
                t.feature,
                t.query_terms or [],
                [],
                params,
            )
            all_texts.extend(texts)

        # 1 次 embed 调用编码全部文本
        result = await embedding_service.embed(
            all_texts,
            return_sparse=False,
            max_length=params["embed_max_length"],
        )
        dense_vectors: np.ndarray = result["dense_vectors"]

        # 按每个 feature 5 个维度切分
        batch_vectors: list[dict[str, list[float]]] = []
        for i in range(len(targets)):
            start = i * 5
            end = start + 5
            feature_vectors = dense_vectors[start:end]
            batch_vectors.append(
                {dim: vec.tolist() for dim, vec in zip(_DIMENSIONS, feature_vectors)}
            )

        logger.info(
            "批量五维 query 编码完成",
            extra={"feature_count": len(targets), "total_texts": len(all_texts)},
        )
        return batch_vectors

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    @staticmethod
    def _require_field(q: dict, key: str) -> Any:
        """读取全局配置字段，缺失即报错（不允许硬编码回退）。"""
        val = q.get(key)
        if val is None or val == "":
            raise BusinessException(f"未配置检索参数 retrieval.query_embed.{key}")
        return val

    @staticmethod
    def _query_limits(cfg: Any, query_sources: list[dict] | None) -> tuple[int | None, int | None]:
        """从类别 Query 术语集配置归纳条目上限。

        每个参与 Query 的术语集可配置 ``query_main_limit``（主查询维 content 上限）
        与 ``query_refined_limit``（精简维 path/title/structural 上限）。
        多个术语集时取最大值；类别未配置对应上限时返回 None（不截断，零硬编码默认，
        仅直接读取 Query 术语集配置）。

        Returns:
            (refined_limit, main_limit)：均为 ``int | None``，Query 术语集未配置对应
            上限时返回 None（调用方不截断，零硬编码默认）。
        """
        refined_limits: list[int] = []
        main_limits: list[int] = []
        for s in query_sources or []:
            if s.get("query_refined_limit"):
                refined_limits.append(int(s["query_refined_limit"]))
            if s.get("query_main_limit"):
                main_limits.append(int(s["query_main_limit"]))
        refined_limit = max(refined_limits) if refined_limits else None
        main_limit = max(main_limits) if main_limits else None
        return refined_limit, main_limit

    @staticmethod
    def _query_params(cfg: Any = None, query_sources: list[dict] | None = None) -> dict:
        """解析五维 query 编码参数（cfg.retrieval.query_embed + 术语集条目上限）。

        Returns:
            dict: 含 content_max_chars/main_limit/refined_limit/feature_repeat/
                embed_max_length/type_query。
        """
        q = cfg.query_embed() if cfg is not None else {}
        refined_limit, main_limit = QueryEmbedder._query_limits(cfg, query_sources)
        return {
            "content_max_chars": int(QueryEmbedder._require_field(q, "content_max_chars")),
            "main_limit": main_limit,
            "refined_limit": refined_limit,
            "feature_repeat": int(QueryEmbedder._require_field(q, "feature_repeat")),
            "embed_max_length": int(QueryEmbedder._require_field(q, "embed_max_length")),
            "type_query": QueryEmbedder._require_field(q, "type_query"),
            "dedupe_threshold": float(QueryEmbedder._require_field(q, "dedupe_similarity_threshold")),
        }

    @staticmethod
    def _build_query_texts(
        feature: str,
        items: list[str],
        methods: list[str],
        params: dict,
    ) -> list[str]:
        """构造五维 query 文本列表（顺序与 _DIMENSIONS 一致）。

        使用 **feature + 精简条目** 作为查询条件，提升召回准确率：
        - path/title/structural: feature + 精简条目前 refined_limit
        - content: feature 重复 feature_repeat 次 + 精简条目前 main_limit
          （主检索维度，feature 重复增强语义权重，避免大类元素符号淹没 feature 语义）
        - type: params["type_query"]（偏向表格块）

        Args:
            feature: 项目大类名。
            items: 查询词组（fixed_query 分词 + 术语集值）。
            methods: 方法名列表（当前配置驱动下为空）。
            params: query_embed 参数（main_limit/refined_limit/feature_repeat/
                type_query/content_max_chars）。

        Returns:
            list[str]: 五维 query 文本，顺序为 [path, title, content, type, structural]。
        """
        # 精简条目（去括号、去重；limit 为 None 时不截断）
        refined_short = QueryEmbedder._refine_items(items, limit=params.get("refined_limit"), threshold=params["dedupe_threshold"])
        refined_long = QueryEmbedder._refine_items(items, limit=params.get("main_limit"), threshold=params["dedupe_threshold"])

        # path/title/structural: feature + 精简条目前 refined_limit
        structural_query = f"{feature} {' '.join(refined_short)}".strip()

        # content: feature 重复 feature_repeat 次 + 精简条目前 main_limit
        # feature 重复增强语义权重，避免 item 符号（如化学元素 Sr/V/Be）淹没 feature 语义
        feature_part = " ".join([feature] * params["feature_repeat"])
        content_query = f"{feature_part} {' '.join(refined_long)}".strip()
        if len(content_query) > params["content_max_chars"]:
            content_query = content_query[: params["content_max_chars"]]

        return [
            structural_query,        # path
            structural_query,        # title
            content_query,           # content
            params["type_query"],    # type（偏向表格块）
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
    def _refine_items(items: list[str], limit: int, threshold: float = 0.85) -> list[str]:
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
                # 字符级相似度 >= threshold → 意思大致相同
                # （"室温拉伸" vs "高温拉伸" ratio≈0.75 不会被去重，保留差异大的）
                ratio = difflib.SequenceMatcher(None, refined, existing).ratio()
                if ratio >= threshold:
                    is_dup = True
                    break

            if is_dup:
                continue

            seen.add(refined)
            result.append(refined)
            if limit is not None and len(result) >= limit:
                break
        return result


# 模块级单例
query_embedder = QueryEmbedder()
