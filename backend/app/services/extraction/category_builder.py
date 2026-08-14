"""E3 类别构建：Schema 驱动 → term_base 展开 → 类别召回（零命中剔除）。"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.extraction.extraction_models import ExtractionTarget, SkippedFeature
from app.services.extraction.term_base_loader import (
    _read,
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


async def _build_refined_terms(
    rows: list[dict],
    field: str,
    limit: int,
    threshold: float,
) -> list[str]:
    """Query 术语集精简：语义去重（余弦 ≥ 阈值视为重复），保留 refined_limit 条。"""
    values = distinct_field_values(rows, field, 10000)
    if not values or limit <= 0:
        return []
    try:
        from app.services.embedding.embedding_service import embedding_service

        vecs = await embedding_service.embed(values)
    except Exception:  # noqa: BLE001
        # 嵌入不可用时回退精确去重（仍按精简上限截断）
        return list(dict.fromkeys(values))[:limit]
    kept: list[str] = []
    kept_vecs: list[list[float]] = []
    for v, vec in zip(values, vecs):
        dup = False
        for kv in kept_vecs:
            sim = sum(a * b for a, b in zip(vec, kv))
            if sim >= threshold:
                dup = True
                break
        if not dup:
            kept.append(v)
            kept_vecs.append(vec)
            if len(kept) >= limit:
                break
    return kept


async def _build_query_terms(
    db: AsyncSession,
    kb_id,
    target: ExtractionTarget,
    refined_cache: dict,
    dedupe_threshold: float,
) -> list[str]:
    """固定 query + Query 术语集（主/精简合并，去重；group_field 按类别过滤）。"""
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
        group_field = (qs.get("group_field") or "").strip()
        if group_field:
            rows = [
                r for r in rows
                if str(_read(r, group_field) or "").strip() == target.feature
            ]
        field = qs.get("value_field") or "term_name"
        main_limit = int(qs.get("query_main_limit") or 30)
        refined_limit = int(qs.get("query_refined_limit") or 8)
        values = distinct_field_values(rows, field, main_limit)
        terms.extend(values)
        # 精简查询：语义去重后与主查询合并
        if qs.get("dedupe") and refined_limit > 0:
            cache_key = (str(tb_id), field, group_field)
            refined = refined_cache.get(cache_key)
            if refined is None:
                refined = await _build_refined_terms(rows, field, refined_limit, dedupe_threshold)
                refined_cache[cache_key] = refined
            terms.extend(refined)
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
    category_recall = global_retrieval.get("category_recall") or {}
    recall_mode = category_recall.get("mode") or "loose"
    recall_top_k = int(category_recall.get("top_k") or 5)
    per_dim_top_k = int(category_recall.get("per_dim_top_k") or 10)
    default_threshold = float(global_retrieval.get("default_confidence_threshold") or 0.35)
    keyword_min_hits = int((global_retrieval.get("hybrid") or {}).get("keyword_min_hits") or 1)
    query_embed_cfg = global_retrieval.get("query_embed") or {}
    content_max_chars = int(query_embed_cfg.get("content_max_chars") or 2000)
    dedupe_threshold = float(query_embed_cfg.get("dedupe_similarity_threshold") or 0.85)
    refined_cache: dict = {}
    kept: list[ExtractionTarget] = []

    async def _finalize(t: ExtractionTarget) -> None:
        """补全 schema 与 Query 术语集数据（串行阶段完成，避免并发共享会话查询）。"""
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
        for qs in t.query_sources or []:
            label = (qs.get("label") or "").strip()
            tb_id = qs.get("term_base_id")
            if label and tb_id:
                t.term_data[label] = await load_term_base(
                    db, kb_id, uuid.UUID(str(tb_id))
                )
        kept.append(t)

    for t in targets:
        t.query_terms = await _build_query_terms(db, kb_id, t, refined_cache, dedupe_threshold)
        query = " ".join([t.feature, *t.query_terms]).strip() or t.feature
        query = query[:content_max_chars]  # query_embed.content_max_chars 生效
        # 第一段：类别召回（category_recall.top_k / per_dim_top_k 生效）
        recall_hits = await retrieval_service.search(
            db,
            uuid.UUID(str(kb_id)),
            query,
            top_k=recall_top_k,
            per_dim_top_k=per_dim_top_k,
            filters=SearchFilters(document_id=uuid.UUID(str(document_id))),
            retrieval_config=global_retrieval,
        )
        if not recall_hits:
            if recall_mode == "off":
                # 第三版「关闭」：全部类别参与，零命中类别以空上下文进入抽取
                t.hits = []
                await _finalize(t)
            else:
                skipped.append(SkippedFeature(feature=t.feature, reason="零命中（检索无结果）", score=0.0))
            continue
        t.hit_score = max(h.score for h in recall_hits)
        t.hit_count = len(recall_hits)
        kw_count = sum(1 for h in recall_hits if getattr(h, "keyword_matched", False))
        # 第二版/第三版：严格模式按阈值剔除（类别级覆盖优先），词法命中兜底
        threshold = (
            float(t.confidence_threshold)
            if t.confidence_threshold is not None
            else default_threshold
        )
        if recall_mode == "strict" and t.hit_score < threshold and kw_count < keyword_min_hits:
            skipped.append(SkippedFeature(
                feature=t.feature,
                reason=f"置信度低于阈值（最高分 {t.hit_score:.3f} < {threshold}，词法命中 {kw_count} < {keyword_min_hits}）",
                score=t.hit_score,
            ))
            continue
        # 第二段：抽取上下文检索（类别级/全局 top_k 生效）
        context_hits = await retrieval_service.search(
            db,
            uuid.UUID(str(kb_id)),
            query,
            top_k=t.top_k or default_top_k,
            filters=SearchFilters(document_id=uuid.UUID(str(document_id))),
            retrieval_config=global_retrieval,
        )
        t.hits = [{
            "chunk_id": h.chunk_id,
            "content": h.content,
            "parent_text": h.parent_text,
            "source_pages": h.source_pages,
            "score": h.score,
        } for h in context_hits]
        await _finalize(t)
    schemas = {"categories": {t.feature: t.schema for t in kept}}
    return kept, skipped, schemas
