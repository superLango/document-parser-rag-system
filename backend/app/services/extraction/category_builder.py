"""E3 类别构建：Schema 驱动 → term_base 展开 → 类别召回（零命中剔除）。"""

from __future__ import annotations

import re
import uuid

from sqlalchemy import text
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
                req_map = cat.get("special_requirements") or {}
                for name in names:
                    t = ExtractionTarget(**{**base.__dict__, "feature": name})
                    t.special_requirement = str(req_map.get(name) or "").strip()
                    targets.append(t)
            else:
                tb_name = term_bases.get(str(cat.get("name_term_base_id") or ""), "")
                base.feature = _category_display_name(cat, tb_name)
                req_map = cat.get("special_requirements") or {}
                base.special_requirement = str(req_map.get(base.feature) or "").strip()
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
    """固定 query + Query 术语集。

    dedupe 开启时只取语义去重后的精简集（refined_limit），不再叠加主查询全集，
    避免长 query 稀释检索语义；dedupe 关闭时回退主查询（main_limit）。
    group_field 按类别过滤。
    """
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
        # 精简查询优先：语义去重后的精简集即 query 全集（不再叠加主查询 30 个）
        if qs.get("dedupe") and refined_limit > 0:
            cache_key = (str(tb_id), field, group_field)
            refined = refined_cache.get(cache_key)
            if refined is None:
                refined = await _build_refined_terms(rows, field, refined_limit, dedupe_threshold)
                refined_cache[cache_key] = refined
            terms.extend(refined)
            if not refined:
                # 精简结果为空（嵌入异常等）时回退主查询，保证 query 非空
                terms.extend(distinct_field_values(rows, field, main_limit))
        else:
            values = distinct_field_values(rows, field, main_limit)
            terms.extend(values)
    return list(dict.fromkeys(terms))


# 文档全文缓存（按 document_id，避免每类别重复统计）
_doc_text_cache: dict[str, str] = {}
_CORE_PAREN_RE = re.compile(r"[（(].*?[）)]")


def _term_core(term: str) -> str:
    """术语核心词：去括号内容、去单位后缀（通用，不依赖领域）。"""
    t = _CORE_PAREN_RE.sub("", term or "")
    t = re.split(r"[/／]", t)[0]
    return t.strip()


async def _select_terms_by_doc_frequency(
    db: AsyncSession,
    kb_id,
    document_id,
    rows: list[dict],
    field: str,
    group_field: str,
    feature: str,
    top_n: int = 8,
) -> list[str]:
    """按「术语在文档中的出现频率」精选重排术语。

    步骤：核心词提取（去括号/单位）→ 文档频率统计 → 子串去重 → TopN。
    数据驱动、自适应文档：GB-T1220 中常见元素/项目名必然高频，
    术语集里的噪音项（罕见元素/复合项）自然落选。
    """
    doc_key = str(document_id)
    if doc_key not in _doc_text_cache:
        r = await db.execute(
            text(
                "select content from text_chunks where document_id=:doc and content is not null"
            ),
            {"doc": document_id},
        )
        _doc_text_cache[doc_key] = "\n".join(x[0] or "" for x in r.fetchall())
    doc_text = _doc_text_cache[doc_key]

    freq: dict[str, int] = {}
    for row in rows:
        if group_field:
            gv = str(_read(row, group_field) or "").strip()
            if gv and gv != feature:
                continue
        cw = _term_core(str(_read(row, field) or ""))
        if not cw or len(cw) > 20:
            continue
        cnt = doc_text.count(cw)
        if cnt == 0:
            continue
        freq[cw] = max(freq.get(cw, 0), cnt)
    ranked = sorted(freq.items(), key=lambda x: (-x[1], len(x[0])))
    kept: list[str] = []
    for w, _cnt in ranked:
        if any(w in k or k in w for k in kept):
            continue
        kept.append(w)
        if len(kept) >= top_n:
            break
    return kept


async def _build_rerank_query(
    cfg,
    db: AsyncSession,
    kb_id,
    target: ExtractionTarget,
) -> str:
    """重排专用 query：类型名 + 精选核心术语（文档频率 TopN）+ Schema 字段名。

    - 术语精选：核心词 + 当前文档出现频率 + 子串去重（自适应文档，过滤噪音）；
    - 字段名：提供输出结构语义，实测对相关性打分有增益；
    - 不使用 Prompt 抽取要求：全类别验证显示其会把无关内容全部打成正分，
      导致类别级过滤失效（无数据类别泄漏 100%）。
    """
    rer_cfg = (cfg.global_config.get("retrieval") or {}).get("reranker") or {}
    if not rer_cfg.get("rerank_query_enabled", True):
        # 关闭精选：回退「类型名 + query_terms」（旧行为）
        q = " ".join([target.feature or "", *target.query_terms]).strip() or target.feature
        return q
    parts: list[str] = [target.feature or ""]
    # 项目术语集（query_sources 中 in_query 的术语）按文档频率精选
    for qs in target.query_sources or []:
        if not qs.get("in_query", False):
            continue
        tb_id = qs.get("term_base_id")
        if not tb_id:
            continue
        rows = await load_term_base(db, kb_id, uuid.UUID(str(tb_id)))
        field = qs.get("value_field") or "term_name"
        group_field = (qs.get("group_field") or "").strip()
        sel = await _select_terms_by_doc_frequency(
            db, kb_id, target.document_id, rows, field, group_field, target.feature
        )
        parts.extend(sel)
    for f in target.fields or []:
        name = (f.get("name") or "").strip()
        if name:
            parts.append(name)
    query = " ".join(dict.fromkeys(prt for prt in parts if prt)).strip()
    return query or target.feature





async def _build_data_query(
    db: AsyncSession,
    kb_id,
    target: ExtractionTarget,
    cache: dict,
    dedupe_threshold: float,
    content_max_chars: int,
) -> str:
    """数据路检索 query：类别名 + 术语集（不含 fixed_query）。

    用于召回复核数据表（化学成分表/力学性能表等）；fixed_query 的字段名
    单独走元信息路，避免稀释术语集信号。
    """
    terms: list[str] = []
    for qs in target.query_sources or []:
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
        if qs.get("dedupe") and refined_limit > 0:
            cache_key = (str(tb_id), field, group_field)
            refined = cache.get(cache_key)
            if refined is None:
                refined = await _build_refined_terms(rows, field, refined_limit, dedupe_threshold)
                cache[cache_key] = refined
            terms.extend(refined)
            if not refined:
                terms.extend(distinct_field_values(rows, field, main_limit))
        else:
            terms.extend(distinct_field_values(rows, field, main_limit))
    query = " ".join([target.feature or "", *terms]).strip() or target.feature
    return query[:content_max_chars]


def _build_meta_query(target: ExtractionTarget, content_max_chars: int) -> str:
    """元信息路检索 query：类别名 + fixed_query（用户手动输入的字段词）。

    用于召回复核项目表/方法条款/取样正文等元信息块。
    """
    terms: list[str] = []
    if target.fixed_query:
        terms.extend(
            t.strip()
            for t in target.fixed_query.replace("，", " ").replace(",", " ").split()
            if t.strip()
        )
    query = " ".join([target.feature or "", *terms]).strip() or target.feature
    return query[:content_max_chars]


async def build(
    cfg,
    db: AsyncSession,
    *,
    kb_id,
    document_id,
    top_k: int | None = None,
) -> tuple[list[ExtractionTarget], list[SkippedFeature], dict]:
    """构建抽取目标并执行类别召回（零命中剔除；兼容旧调用，逐类别串行）。"""
    targets, skipped = await build_targets(cfg, db, kb_id=kb_id)
    kept: list[ExtractionTarget] = []
    refined_cache: dict = {}
    for t in targets:
        built, sk = await build_one(
            cfg, db, kb_id=kb_id, document_id=document_id, target=t,
            refined_cache=refined_cache, top_k=top_k,
        )
        if built is not None:
            kept.append(built)
        elif sk is not None:
            skipped.append(sk)
    schemas = {"categories": {t.feature: t.schema for t in kept}}
    return kept, skipped, schemas


async def build_targets(
    cfg, db: AsyncSession, *, kb_id
) -> tuple[list[ExtractionTarget], list[SkippedFeature]]:
    """仅展开抽取目标（不做检索），供流水线流式化使用。"""
    return await _build_targets(cfg, db, kb_id)


async def build_one(
    cfg,
    db: AsyncSession,
    *,
    kb_id,
    document_id,
    target: ExtractionTarget,
    refined_cache: dict | None = None,
    top_k: int | None = None,
) -> tuple[ExtractionTarget | None, SkippedFeature | None]:
    """单类别召回 + schema/术语数据补齐。

    返回 (target, None) 或 (None, skipped)；供流水线"检索完一个类别立即抽取"使用。
    """
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
    cache = refined_cache if refined_cache is not None else {}
    t = target
    t.document_id = str(document_id)
    t.query_terms = await _build_query_terms(db, kb_id, t, cache, dedupe_threshold)
    # 检索分两路：数据路（术语集召回数据表）+ 元信息路（fixed_query 字段词召回元信息）
    data_query = await _build_data_query(db, kb_id, t, cache, dedupe_threshold, content_max_chars)
    meta_query = _build_meta_query(t, content_max_chars)
    # 重排专用 query：类型名 + 文档频率精选核心词 + 字段名（不参与检索）
    rerank_query = await _build_rerank_query(cfg, db, kb_id, t)
    # 第一段：类别召回（category_recall.top_k / per_dim_top_k 生效）
    recall_hits = await retrieval_service.search(
        db,
        uuid.UUID(str(kb_id)),
        data_query,
        top_k=recall_top_k,
        per_dim_top_k=per_dim_top_k,
        filters=SearchFilters(document_id=uuid.UUID(str(document_id))),
        retrieval_config=global_retrieval,
        rerank_query=rerank_query,
    )
    if not recall_hits:
        if recall_mode == "off":
            # 第三版「关闭」：全部类别参与，零命中类别以空上下文进入抽取
            t.hits = []
        else:
            return None, SkippedFeature(feature=t.feature, reason="零命中（检索无结果）", score=0.0)
    else:
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
            return None, SkippedFeature(
                feature=t.feature,
                reason=f"置信度低于阈值（最高分 {t.hit_score:.3f} < {threshold}，词法命中 {kw_count} < {keyword_min_hits}）",
                score=t.hit_score,
            )
        # 第二段：抽取上下文检索分两路（数据路 + 元信息路），合并去重
        data_route_top_k = int(global_retrieval.get("data_route_top_k") or 10)
        meta_route_top_k = int(global_retrieval.get("meta_route_top_k") or 5)
        data_hits = await retrieval_service.search(
            db,
            uuid.UUID(str(kb_id)),
            data_query,
            top_k=min(data_route_top_k, t.top_k or default_top_k),
            filters=SearchFilters(document_id=uuid.UUID(str(document_id))),
            retrieval_config=global_retrieval,
            rerank_query=rerank_query,
        )
        meta_hits = await retrieval_service.search(
            db,
            uuid.UUID(str(kb_id)),
            meta_query,
            top_k=meta_route_top_k,
            filters=SearchFilters(document_id=uuid.UUID(str(document_id))),
            retrieval_config=global_retrieval,
            rerank_query=rerank_query,
        )
        # 合并去重：数据路优先（setdefault 保留先到）
        merged_hits: dict[str, SearchResult] = {}
        for h in list(data_hits) + list(meta_hits):
            merged_hits.setdefault(h.chunk_id, h)
        context_hits = list(merged_hits.values())
        t.hits = [{
            "chunk_id": h.chunk_id,
            "content": h.content,
            "parent_text": h.parent_text,
            "source_pages": h.source_pages,
            "score": h.score,
            "has_table": getattr(h, "has_table", False),
            # 重排分数（CrossEncoder 写回，供阈值过滤使用）
            "rerank_score": getattr(h, "rerank_score", None),
        } for h in context_hits]
        # 类别级过滤（第一部分）：非 always 类别按重排分数阈值剔除。
        # always 类别（标准信息/热处理制度）总是抽取，不参与剔除。
        if (t.extraction_strategy or "auto") != "always":
            reranker_cfg = global_retrieval.get("reranker") or {}
            if reranker_cfg.get("category_filter_enabled", True):
                rerank_threshold = float(reranker_cfg.get("threshold") or 0.0)
                max_rerank = max(
                    (h.get("rerank_score") for h in t.hits if h.get("rerank_score") is not None),
                    default=None,
                )
                if max_rerank is None or max_rerank < rerank_threshold:
                    return None, SkippedFeature(
                        feature=t.feature,
                        reason=f"重排分数低于阈值（最高 {max_rerank} < {rerank_threshold}）",
                        score=max_rerank,
                    )
    # 补全 schema 与 Query 术语集数据
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
            rows = await load_term_base(
                db, kb_id, uuid.UUID(str(tb_id))
            )
            # 术语集按 group_field 过滤：有则只保留当前类别的记录，
            # 无则展示全部（Prompt 中 ${label.field} 渲染与此一致）
            gf = (qs.get("group_field") or "").strip()
            if gf:
                rows = [
                    r for r in rows
                    if str(_read(r, gf) or "").strip() == target.feature
                ]
            t.term_data[label] = rows
    return t, None
