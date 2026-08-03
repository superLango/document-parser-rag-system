"""Phase 2 类别构建主流程。

从 sm_feature 全量出发，用每个 feature 的 item+method 作为 query 检索
doc_five_dim，有召回且置信度达标则保留该 feature。

流程：
1. base_data.loader 加载全量 features + 每个 feature 的 items/methods
2. query_embedder 批量编码五维 query 向量（1 次 embed 调用）
3. 并发执行 hybrid_search（每个 feature 一次，top_k=5 快速检索）
4. feature_filter 置信度过滤
5. schema_builder 构建三类 schema（基础信息/类别列表/热处理制度）
6. 返回 (targets, skipped_features, schemas)

性能：
- 批量编码：所有 feature 的五维 query 通过 1 次 embed 调用完成
- 并发检索：feature 间并发 hybrid_search（通过 asyncio.gather）
- 目标耗时：< 10s

使用示例::

    from app.services.extraction.category.category_builder import category_builder

    targets, skipped, schemas = await category_builder.build(doc_id)
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from app.core.logging import get_logger
from app.services.base_data.loader import base_table_loader
from app.services.extraction.extraction_config import get_extraction_settings
from app.services.extraction.extraction_models import (
    ExtractionTarget,
    ItemInfo,
    MethodInfo,
    SkippedFeature,
)
from app.services.extraction.category.feature_filter import feature_filter
from app.services.extraction.query_embedder import query_embedder
from app.services.extraction.schema_builder import schema_builder
from app.services.vector.five_dim_vector_store import five_dim_vector_store

logger = get_logger(__name__)

# Phase 2 类别检索的 top_k（只需判断有无召回，取少量结果即可）
_PHASE2_TOP_K = 5


class CategoryBuilder:
    """Phase 2 类别构建器。

    编排三表加载 → 批量 query 编码 → 并发检索 → 过滤 → schema 构建。
    """

    def __init__(self) -> None:
        self._settings = get_extraction_settings()

    async def build(
        self,
        doc_id: str,
        kb_id: str | None = None,
    ) -> tuple[list[ExtractionTarget], list[SkippedFeature], dict[str, Any]]:
        """构建抽取目标（Phase 2 主入口）。

        Args:
            doc_id: 文档 ID（用于 hybrid_search 的 doc_id 过滤）。
            kb_id: 知识库 ID，用于向量 Collection 隔离。

        Returns:
            tuple: (targets, skipped_features, schemas)
                - targets: 保留的 ExtractionTarget 列表（含 items/methods/schema/confidence）
                - skipped_features: 被剔除的 feature 列表
                - schemas: dict，含 "doc_info" / "heat_treatment" 两个 schema
        """
        start_time = time.time()

        # 1. 加载全量 features
        features = await base_table_loader.load_all_features()
        feature_names = [f.name for f in features if f.name]
        logger.info(
            "Phase 2 开始：加载 features",
            extra={"doc_id": doc_id, "feature_count": len(feature_names)},
        )

        # 2. 加载每个 feature 的 items 和 methods（并发）
        items_map, methods_map = await self._load_items_and_methods(feature_names)

        # 3. 批量编码五维 query 向量
        query_texts: list[tuple[str, list[str], list[str]]] = []
        for feature_name in feature_names:
            item_names = [it.name for it in items_map.get(feature_name, [])]
            method_names = [m.name for m in methods_map.get(feature_name, [])]
            query_texts.append((feature_name, item_names, method_names))

        query_vectors_list = await query_embedder.encode_batch(query_texts)
        query_vectors_map: dict[str, dict[str, list[float]]] = {
            fn: qv for fn, qv in zip(feature_names, query_vectors_list)
        }

        # 4. 并发执行 hybrid_search（每个 feature 一次，top_k=5）
        feature_hits = await self._search_all_features(
            doc_id, feature_names, query_vectors_map, kb_id=kb_id
        )

        # 5. 置信度过滤
        kept_features, skipped = feature_filter.filter(feature_hits)

        # 6. 构建 ExtractionTarget（保留的 feature）
        targets: list[ExtractionTarget] = []
        for feature_name in kept_features:
            target = ExtractionTarget(
                feature=feature_name,
                items=items_map.get(feature_name, []),
                methods=methods_map.get(feature_name, []),
                confidence=feature_filter.get_confidence(feature_name),
            )
            targets.append(target)

        # 7. 构建三类 schema
        doc_info_schema = schema_builder.build_doc_info_schema()
        category_schemas = schema_builder.build_category_schemas(targets)
        heat_treatment_schema = schema_builder.build_heat_treatment_schema(feature_names)

        schemas = {
            "doc_info": doc_info_schema,
            "categories": category_schemas,
            "heat_treatment": heat_treatment_schema,
        }

        elapsed = time.time() - start_time
        logger.info(
            "Phase 2 完成",
            extra={
                "doc_id": doc_id,
                "total_features": len(feature_names),
                "kept_features": len(targets),
                "skipped_features": len(skipped),
                "elapsed_sec": round(elapsed, 2),
            },
        )

        return targets, skipped, schemas

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    async def _load_items_and_methods(
        self,
        feature_names: list[str],
    ) -> tuple[dict[str, list[ItemInfo]], dict[str, list[MethodInfo]]]:
        """并发加载所有 feature 的 items 和 methods。

        Args:
            feature_names: feature 名列表。

        Returns:
            tuple: (items_map, methods_map)
                - items_map: feature 名 → ItemInfo 列表
                - methods_map: feature 名 → MethodInfo 列表
        """

        async def load_one(feature_name: str) -> tuple[str, list[ItemInfo], list[MethodInfo]]:
            items_orm = await base_table_loader.load_items_by_feature(feature_name)
            methods_orm = await base_table_loader.load_methods_by_feature(feature_name)
            items = [ItemInfo.from_orm(it) for it in items_orm]
            methods = [MethodInfo.from_orm(m) for m in methods_orm]
            return feature_name, items, methods

        # 限制并发数，避免对 PG 造成过大压力
        semaphore = asyncio.Semaphore(10)
        results = await asyncio.gather(
            *[self._load_with_semaphore(semaphore, load_one, fn) for fn in feature_names],
            return_exceptions=True,
        )

        items_map: dict[str, list[ItemInfo]] = {}
        methods_map: dict[str, list[MethodInfo]] = {}
        for result in results:
            if isinstance(result, Exception):
                logger.warning("加载 feature items/methods 失败", extra={"error": str(result)})
                continue
            feature_name, items, methods = result
            items_map[feature_name] = items
            methods_map[feature_name] = methods

        return items_map, methods_map

    @staticmethod
    async def _load_with_semaphore(
        semaphore: asyncio.Semaphore,
        func: Any,
        *args: Any,
    ) -> Any:
        """通过信号量限制并发执行的协程。"""
        async with semaphore:
            return await func(*args)

    async def _search_all_features(
        self,
        doc_id: str,
        feature_names: list[str],
        query_vectors_map: dict[str, dict[str, list[float]]],
        kb_id: str | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        """并发执行所有 feature 的 hybrid_search。

        Args:
            doc_id: 文档 ID。
            feature_names: feature 名列表。
            query_vectors_map: feature 名 → 五维 query 向量。
            kb_id: 知识库 ID。

        Returns:
            dict: feature 名 → hits 列表。
        """
        weights = self._settings.hybrid_search_weights

        async def search_one(feature_name: str) -> tuple[str, list[dict[str, Any]]]:
            query_vectors = query_vectors_map.get(feature_name)
            if not query_vectors:
                return feature_name, []
            try:
                hits = await five_dim_vector_store.hybrid_search(
                    query_vectors=query_vectors,
                    doc_id=doc_id,
                    top_k=_PHASE2_TOP_K,
                    per_dim_top_k=_PHASE2_TOP_K * 2,
                    weights=weights,
                    kb_id=kb_id,
                )
                return feature_name, hits
            except Exception as err:
                logger.warning(
                    "hybrid_search 失败",
                    extra={"feature": feature_name, "error": str(err)},
                )
                return feature_name, []

        results = await asyncio.gather(
            *[search_one(fn) for fn in feature_names],
            return_exceptions=True,
        )

        feature_hits: dict[str, list[dict[str, Any]]] = {}
        for result in results:
            if isinstance(result, Exception):
                logger.warning("hybrid_search 异常", extra={"error": str(result)})
                continue
            feature_name, hits = result
            feature_hits[feature_name] = hits

        return feature_hits


# 模块级单例
category_builder = CategoryBuilder()
