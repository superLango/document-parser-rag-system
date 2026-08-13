"""E3 类别构建：Schema 驱动 → term_base 展开 → 类别召回（零命中剔除）。"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.extraction.extraction_models import ExtractionTarget, SkippedFeature
from app.services.extraction.term_base_loader import (
    distinct_field_values,
    load_term_base,
)
from app.services.indexing.retrieval import SearchFilters, retrieval_service

EXPAND_LIMIT = 200  # term_base 展开实例数上限（后续版本可配置）


def _category_display_name(cat: dict, term_base_name: str) -> str:
    name = (cat.get("name") or "").strip()
    if name:
        return name
    if cat.get("name_source") == "term_base":
        return term_base_name or "术语类别"
    return "未命名类别"


async def _build_targets(cfg, db: AsyncSession, kb_id) -> tuple[list[ExtractionTarget], list[SkippedFeature]]:
    targets: list[ExtractionTarget] = []
    skipped: list[SkippedFeature] = []
    term_bases = {t["id"]: t["name"] for t in cfg.term_bases}
    for tpl in cfg.schema_templates:
        for cat in tpl.get("categories", []):
            if not cat.get("is_active", True):
                continue
            if cat.get("extraction_strategy") == "never":
                continue
            fields = cat.get("fields") or []
            base = ExtractionTarget(
                feature="",
                category_id=cat["id"],
                template_id=tpl["id"],
                description=cat.get("description") or "",
                return_type=cat.get("return_type") or "array",
                extraction_strategy=cat.get("extraction_strategy") or "auto",
                fixed_query=cat.get("fixed_query") or "",
                query_sources=cat.get("query_sources") or [],
                top_k=cat.get("top_k"),
                max_tokens=cat.get("max_tokens"),
                confidence_threshold=cat.get("confidence_threshold"),
                fields=fields,
            )
            if cat.get("name_source") == "term_base" and cat.get("name_term_base_id"):
                rows = await load_term_base(db, kb_id, uuid.UUID(str(cat["name_term_base_id"])))
                names = distinct_field_values(rows, cat.get("name_term_field") or "term_name", EXPAND_LIMIT)
                tb_name = term_bases.get(str(cat["name_term_base_id"]), "")
                if not names:
                    skipped.append(SkippedFeature(
                        feature=_category_display_name(cat, tb_name),
                        reason="术语集无可用名称，未展开",
                    ))
                    continue
                for name in names:
                    t = ExtractionTarget(**{**base.__dict__, "feature": name})
                    targets.append(t)
            else:
                tb_name = term_bases.get(str(cat.get("name_term_base_id") or ""), "")
                base.feature = _category_display_name(cat, tb_name)
                targets.append(base)
    return targets, skipped


async def _build_query_terms(db: AsyncSession, kb_id, target: ExtractionTarget) -> list[str]:
    """固定 query + Query 术语集（主/精简合并，去重）。"""
    terms: list[str] = []
    if target.fixed_query:
        terms.extend(t.strip() for t in target.fixed_query.replace("，", " ").replace(",", " ").split() if t.strip())
    for qs in target.query_sources:
        if not qs.get("in_query", False):
            continue
        tb_id = qs.get("term_base_id")
        if not tb_id:
            continue
        rows = await load_term_base(db, kb_id, uuid.UUID(str(tb_id)))
        values = distinct_field_values(rows, qs.get("value_field") or "term_name", int(qs.get("query_main_limit") or 30))
        terms.extend(values)
    return list(dict.fromkeys(terms))


async def build(
    cfg,
    db: AsyncSession,
    *,
    kb_id,
    document_id,
    top_k: int | None = None,
) -> tuple[list[ExtractionTarget], list[SkippedFeature], dict]:
    """构建抽取目标并执行类别召回（零命中剔除）。"""
    targets, skipped = await _build_targets(cfg, db, kb_id)
    global_retrieval = cfg.global_config.get("retrieval") or {}
    default_top_k = top_k or global_retrieval.get("top_k") or 10
    kept: list[ExtractionTarget] = []
    for t in targets:
        t.query_terms = await _build_query_terms(db, kb_id, t)
        query = " ".join([t.feature, *t.query_terms]).strip() or t.feature
        hits = await retrieval_service.search(
            db,
            uuid.UUID(str(kb_id)),
            query,
            top_k=t.top_k or default_top_k,
            filters=SearchFilters(document_id=uuid.UUID(str(document_id))),
        )
        if not hits:
            skipped.append(SkippedFeature(feature=t.feature, reason="零命中（检索无结果）"))
            continue
        t.hits = [{
            "chunk_id": h.chunk_id,
            "content": h.content,
            "parent_text": h.parent_text,
            "source_pages": h.source_pages,
            "score": h.score,
        } for h in hits]
        properties = {}
        for f in t.fields:
            prop: dict = {"type": f.get("type") or "string"}
            if f.get("required"):
                prop["required"] = True
            if f.get("description"):
                prop["description"] = f["description"]
            if f.get("example"):
                prop["example"] = f["example"]
            properties[f["name"]] = prop
        t.schema = {"type": t.return_type, "properties": properties}
        kept.append(t)
    schemas = {"categories": {t.feature: t.schema for t in kept}}
    return kept, skipped, schemas
