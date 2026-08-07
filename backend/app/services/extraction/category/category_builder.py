"""Phase 2 类别构建主流程（配置驱动）。

从配置中心的 Schema 模板加载类别（配置驱动，由术语集承载），
用类别名 + Query 术语集作为 query 检索 doc_five_dim，有召回且置信度达标则保留。

配置驱动要点：
- 类别来源：``cfg.schema_templates`` 中 is_active=True 的类别节点。
- 名称展开：``name_source=term_base`` 的类别按术语集字段值循环生成多个类别实例。
- 字段值：从术语绑定（term/dataset）解析可选值，供 schema 构建与白名单注入。
- Query 词组：由 ``fixed_query`` + ``query_sources``（Query 术语集）组装。
- 置信度阈值 / top_k：类别级覆盖全局默认。

使用示例::

    from app.services.extraction.category.category_builder import category_builder

    targets, skipped, schemas = await category_builder.build(
        doc_id, kb_id=kb_id, cfg=cfg, db=db
    )
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from app.core.logging import get_logger
from app.core.exceptions import BusinessException
from app.services.extraction.extraction_models import (
    ExtractionTarget,
    SkippedFeature,
)
from app.services.extraction.category.feature_filter import feature_filter
from app.services.extraction.query_embedder import query_embedder
from app.services.extraction.schema_builder import schema_builder
from app.services.extraction.rule_engine.term_base_loader import term_base_loader
from app.services.vector.five_dim_vector_store import five_dim_vector_store

logger = get_logger(__name__)


class CategoryBuilder:
    """Phase 2 类别构建器（Schema 模板驱动）。

    编排 Schema 模板加载 → 类别展开 → 术语集取值 → 批量 query 编码 →
    并发检索 → 过滤 → schema 构建。
    """

    def __init__(self) -> None:
        pass

    async def build(
        self,
        doc_id: str,
        kb_id: str | None = None,
        cfg: Any = None,
        db: Any = None,
    ) -> tuple[list[ExtractionTarget], list[SkippedFeature], dict[str, Any]]:
        """构建抽取目标（Phase 2 主入口，配置驱动）。

        Args:
            doc_id: 文档 ID（用于 hybrid_search 的 doc_id 过滤）。
            kb_id: 知识库 ID，用于向量 Collection 隔离。
            cfg: ExtractionDomainConfig（由 pipeline 解析后传入）。
            db: 数据库会话（用于术语集取值）。

        Returns:
            tuple: (targets, skipped_features, schemas)
                - targets: 保留的 ExtractionTarget 列表（含 fields/query_terms/schema）
                - skipped_features: 被剔除的 category 列表
                - schemas: dict，含 "categories" 键
        """
        start_time = time.time()

        # 1. 从 Schema 模板加载类别并展开为目标
        targets, expanded_count = await self._build_targets(cfg, db, kb_id)
        logger.info(
            "Phase 2 开始：加载 Schema 类别",
            extra={
                "doc_id": doc_id,
                "target_count": len(targets),
                "expanded_count": expanded_count,
            },
        )

        # 2. 批量编码五维 query 向量（feature + query_terms）
        query_vectors_list = await query_embedder.encode_batch(
            targets,
            cfg=cfg,
        )
        query_vectors_map: dict[str, dict[str, list[float]]] = {
            t.feature: qv for t, qv in zip(targets, query_vectors_list)
        }

        # 3. 并发执行 hybrid_search（每个类别一次，top_k=5）
        feature_hits = await self._search_all_features(
            doc_id, targets, query_vectors_map, cfg, kb_id=kb_id
        )

        # 4. 置信度过滤（全局默认阈值过滤，类别级阈值在保留阶段覆盖）
        global_threshold = None
        if cfg is not None:
            global_threshold = cfg.retrieval.get("default_confidence_threshold")
        kept_features, skipped = feature_filter.filter(
            feature_hits, threshold=global_threshold
        )

        # 5. 构建 retained ExtractionTarget（保留的类别，类别级阈值覆盖全局）
        retained: list[ExtractionTarget] = []
        for t in targets:
            if t.feature not in kept_features:
                continue
            confidence = feature_filter.get_confidence(t.feature)
            category_threshold = t.confidence_threshold
            if category_threshold is not None and confidence < category_threshold:
                skipped.append(SkippedFeature(
                    feature=t.feature,
                    reason=f"类别级置信度过低（{confidence:.4f} < {category_threshold}）",
                    confidence=confidence,
                ))
                continue
            t.confidence = confidence
            retained.append(t)

        # 6. 构建类别 schema（从配置字段）
        category_schemas = schema_builder.build_category_schemas(retained)

        schemas = {"categories": category_schemas}

        elapsed = time.time() - start_time
        logger.info(
            "Phase 2 完成",
            extra={
                "doc_id": doc_id,
                "total_targets": len(targets),
                "kept_features": len(retained),
                "skipped_features": len(skipped),
                "elapsed_sec": round(elapsed, 2),
            },
        )

        return retained, skipped, schemas

    # ------------------------------------------------------------------
    # 目标构建
    # ------------------------------------------------------------------
    async def _build_targets(
        self,
        cfg: Any,
        db: Any,
        kb_id: str | None,
    ) -> tuple[list[ExtractionTarget], int]:
        """从 Schema 模板构建原始目标列表（含 term_base 名称展开与字段取值）。

        Returns:
            (targets, expanded_count)：展开后的目标数与因 term_base 展开产生的增量数。
        """
        targets: list[ExtractionTarget] = []
        expanded = 0

        if cfg is None:
            logger.warning("未传入抽取配置，Phase 2 无类别可构建")
            return targets, expanded

        for template in cfg.schema_templates:
            for cat in template.get("categories", []):
                if not cat.get("is_active", True):
                    continue
                if cat.get("extraction_strategy") == "never":
                    continue

                base_fields = await self._enrich_fields(cfg, db, kb_id, cat)

                if cat.get("name_source") == "term_base":
                    names = await self._expand_names(cfg, db, kb_id, cat)
                    if not names:
                        logger.warning(
                            "名称术语集为空，跳过类别",
                            extra={"category": cat.get("name", "")},
                        )
                        continue
                    expanded += len(names) - 1
                    for name in names:
                        targets.append(self._make_target(cat, name, base_fields, cfg))
                else:
                    targets.append(self._make_target(cat, cat.get("name", ""), base_fields, cfg))

        return targets, expanded

    def _make_target(
        self,
        cat: dict,
        feature: str,
        fields: list[dict],
        cfg: Any = None,
    ) -> ExtractionTarget:
        """由类别节点构造单个 ExtractionTarget。"""
        query_terms = self._build_query_terms(cat, cfg)
        # 类别名作为首个 query 词，保证空配置时仍有检索语义
        if feature and feature not in query_terms:
            query_terms.insert(0, feature)
        return ExtractionTarget(
            feature=feature,
            category_id=cat.get("id"),
            template_id=cat.get("template_id"),
            name_source=cat.get("name_source", "manual"),
            name_term_base_id=cat.get("name_term_base_id"),
            query_mode=cat.get("query_mode", "fixed"),
            fixed_query=cat.get("fixed_query"),
            query_sources=cat.get("query_sources") or [],
            confidence_threshold=cat.get("confidence_threshold"),
            top_k=cat.get("top_k"),
            rerank_top_k=cat.get("rerank_top_k"),
            max_tokens=cat.get("max_tokens"),
            return_type=cat.get("return_type", "array"),
            fields=fields or [],
            query_terms=query_terms,
        )

    def _build_query_terms(self, cat: dict, cfg: Any = None) -> list[str]:
        """组装检索查询词组（fixed_query + query_sources 预置值）。

        实际术语集值在检索时按需加载（见 query_terms 的运行时补充），
        此处先收集 fixed_query 的分词与类别描述。
        """
        terms: list[str] = []
        fixed = cat.get("fixed_query")
        if fixed:
            for tok in fixed.replace("，", " ").replace(",", " ").split():
                tok = tok.strip()
                if tok and tok not in terms:
                    terms.append(tok)
        # 术语集去重后保留条数上限：读取类别 Query 术语集配置的精简上限
        #（类别未配置时回退全局 retrieval.query_embed.query_refined_limit）
        refined_limit, _ = query_embedder._query_limits(cfg, cat.get("query_sources"))
        if len(terms) > refined_limit:
            terms = terms[:refined_limit]
        return terms

    async def _expand_names(
        self,
        cfg: Any,
        db: Any,
        kb_id: str | None,
        cat: dict,
    ) -> list[str]:
        """按名称术语集字段值展开类别名。"""
        term_base_id = cat.get("name_term_base_id")
        field = cat.get("name_term_field")
        if not term_base_id or not field or db is None:
            return []
        data = await term_base_loader.load_term_base(db, str(kb_id), str(term_base_id))
        if data is None:
            return []
        return term_base_loader.get_group_values(data, field)

    async def _enrich_fields(
        self,
        cfg: Any,
        db: Any,
        kb_id: str | None,
        cat: dict,
    ) -> list[dict]:
        """为类别字段富化可选值（从术语绑定 term 解析）。

        Returns:
            list[dict]: 字段列表，每项含 name/description/type/required/example/values。
        """
        category_id = cat.get("id")
        enriched: list[dict] = []
        for f in cat.get("fields", []):
            f = dict(f)
            binding = None
            if cfg is not None and category_id:
                binding = cfg.term_bindings.get((category_id, f.get("name")))
            f["values"] = await self._resolve_binding_values(cfg, db, kb_id, binding)
            enriched.append(f)
        return enriched

    async def _resolve_binding_values(
        self,
        cfg: Any,
        db: Any,
        kb_id: str | None,
        binding: dict | None,
    ) -> list[str]:
        """从术语绑定解析字段可选值（异步加载术语集）。"""
        if not binding:
            return []
        # term 绑定：从术语集字段值加载（系统无数据集概念，仅术语集）
        term_base_id = binding.get("term_base_id")
        if not term_base_id or db is None:
            return []
        value_field = (binding.get("config") or {}).get("value_field", "term_name")
        data = await term_base_loader.load_term_base(
            db, str(kb_id), str(term_base_id)
        )
        if data is None:
            return []
        return term_base_loader.get_group_values(data, value_field)

    # ------------------------------------------------------------------
    # 检索与过滤
    # ------------------------------------------------------------------
    async def _search_all_features(
        self,
        doc_id: str,
        targets: list[ExtractionTarget],
        query_vectors_map: dict[str, dict[str, list[float]]],
        cfg: Any,
        kb_id: str | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        """并发执行所有类别的 hybrid_search。"""
        if cfg is None:
            raise BusinessException("类别构建缺少抽取配置（cfg）")
        weights = cfg.retrieval.get("weights")
        if not weights:
            raise BusinessException("未配置检索权重 retrieval.weights")

        # Phase 2 类别召回参数（cfg.retrieval.phase2，缺失即报错，无硬编码回退）
        phase2 = cfg.phase2_retrieval() if cfg is not None else {}
        if phase2.get("top_k") is None or phase2.get("per_dim_top_k") is None:
            raise BusinessException("未配置检索参数 retrieval.phase2.top_k / per_dim_top_k")
        phase2_top_k = int(phase2["top_k"])
        phase2_per_dim_top_k = int(phase2["per_dim_top_k"])

        async def search_one(target: ExtractionTarget) -> tuple[str, list[dict[str, Any]]]:
            query_vectors = query_vectors_map.get(target.feature)
            if not query_vectors:
                return target.feature, []
            try:
                hits = await five_dim_vector_store.hybrid_search(
                    query_vectors=query_vectors,
                    doc_id=doc_id,
                    top_k=phase2_top_k,
                    per_dim_top_k=phase2_per_dim_top_k,
                    weights=weights,
                    kb_id=kb_id,
                )
                return target.feature, hits
            except Exception as err:
                logger.warning(
                    "hybrid_search 失败",
                    extra={"feature": target.feature, "error": str(err)},
                )
                return target.feature, []

        results = await asyncio.gather(
            *[search_one(t) for t in targets],
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