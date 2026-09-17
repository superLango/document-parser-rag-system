"""抽取配置服务（M34/S2）：Schema 模板、Prompt、规则组、脚本。

权限由端点层控制（editor+ 写 / 成员读）；删除均为硬删（FK CASCADE）。
脚本调试：受限子进程执行（-I 隔离、10s 超时、输出上限），仅注入当前 KB 术语集只读数据。
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessException, ErrorCode
from app.core.logging import get_logger
from app.models.extraction import (
    KbExtractionConfig,
    KbScript,
    PromptContent,
    PromptTemplate,
    RuleGroup,
    RuleGroupItem,
    SchemaCategory,
    SchemaField,
    SchemaTemplate,
)
from app.models.glossary import TermBase
from app.services.extraction import script_tools

logger = get_logger(__name__)

SCRIPT_TIMEOUT = 60  # 脚本调试超时（秒）：首次嵌入需加载模型并编码术语集
SCRIPT_MAX_OUTPUT = 1024 * 1024  # 输出上限 1MB
SCRIPT_MAX_TERM_ROWS = 1000  # 注入术语集每库最大词条数

# ============================================================
# 全局配置（结构化抽取：retrieval / llm / kb_tool）
# ============================================================
DEFAULT_GLOBAL_CONFIG: dict = {
    "retrieval": {
        "top_k": 15,
        "candidate_mult": 2,
        "weights": {"title": 0.2, "content": 0.8},
        "default_confidence_threshold": 0.35,
        "context_top_k": 30,
        "context_max_tokens": 56000,
        "context": {
            "chars_per_token": 1.5,
            # 上下文排序：page=页码排序（主流程）/ rerank=重排分数降序
            "sort_mode": "page",
            # 类别抽取为 0 条时，自动改用重排排序再抽一次（附录类内容兜底）
            "retry_rerank_on_empty": True,
        },
        "category_recall": {"mode": "loose", "top_k": 8, "per_dim_top_k": 10},
        # 上下文检索分两路（2026-08）：数据路召回复核表（术语集），元信息路召回复核项目表/方法/取样（字段名）
        "data_route_top_k": 10,
        "meta_route_top_k": 5,
        "query_embed": {
            "content_max_chars": 2000,
            "dedupe_similarity_threshold": 0.85,
        },
        "hybrid": {"enabled": True, "rrf_k": 60.0, "dense_weight": 1.0, "keyword_weight": 1.2, "keyword_min_hits": 1},
        "reranker": {
            "enabled": False, "model": "", "top_n": 15,
            # 抽取过滤开关（2026-08 定稿）：
            # threshold：重排分数阈值（低于则类别/块被过滤）
            # category_filter_enabled：类别级过滤（非 always 类别按分数剔除）
            # block_filter_enabled：块级过滤（低分块不进入抽取上下文）
            # rerank_query_enabled：重排专用精选 query（类型名+文档频率核心词+字段名）
            "threshold": 0.0,
            "category_filter_enabled": True,
            "block_filter_enabled": True,
            "rerank_query_enabled": True,
        },
    },
    "llm": {
        # 引擎：默认 BaseExtract（自研直抽：一次拼接 + 分批不截断 + 全参数可配）；
        # LangExtractPkg（原包）保留可切换，但不再作为默认。
        "engine": "BaseExtract",
        "engines": {
            "BaseExtract": {
                "temperature": 0.0, "top_p": 0.1, "top_k": 20, "max_tokens": 200000,
                "timeout": 1800, "enable_thinking": False,
                "concurrency": {"max_concurrency": 32, "cross_category": 32, "within_category": 1},
                "batch": {"single_threshold": 200000, "batch_chars": 6000, "overlap": 500, "context_truncate": 120000},
            },
            "LangExtractPkg": {
                # 输出预算下调，输入预算自动放大（防 400/截断）
                "temperature": 0.0, "top_p": 0.1, "top_k": 20, "max_tokens": 200000,
                "timeout": 600, "enable_thinking": False,
                # 单轮抽取优先保证完整（多轮仅放大耗时，first-pass 已覆盖大多数）
                "format_type": "JSON", "fence_output": False, "max_examples": 3, "passes": 1,
                # 原包分块：单块字符上限（受模型窗口/输出预算钳制）+ 跨块共指窗口；
                # 12k 整表单块实测抽取退化，回退 6000 平衡整表上下文与抽取质量
                "max_char_buffer": 6000, "context_window_chars": 500,
                # 并行：batch×workers，建议与 vLLM --max-num-seqs 一致
                "batch_length": 8, "max_workers": 8,
                "concurrency": {"max_concurrency": 32, "cross_category": 32, "within_category": 32},
            },
        },
    },
    "kb_tool": {
        "embed_batch_size": 16,
        "search_concurrency": 10,
        "semantic_top_k": 5,
        "match_top_k": 1,
        "match_threshold": 0.9,
        "script_timeout": SCRIPT_TIMEOUT,
        "script_max_output_bytes": SCRIPT_MAX_OUTPUT,
        "script_max_term_rows": SCRIPT_MAX_TERM_ROWS,
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    """递归合并：override 显式覆盖 base；返回新 dict。"""
    out = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _default_global_config() -> dict:
    import copy

    return copy.deepcopy(DEFAULT_GLOBAL_CONFIG)


async def get_global_config(db, kb_id) -> dict:
    """读取 KB 全局配置：默认值 + 用户覆盖 deep merge（无记录时返回默认）。"""
    row = (
        await db.execute(
            select(KbExtractionConfig).where(KbExtractionConfig.kb_id == kb_id)
        )
    ).scalar_one_or_none()
    if row is None or not row.content:
        return {
            "enabled": True,
            "content": _default_global_config(),
            "version": 1,
        }
    merged = _deep_merge(_default_global_config(), row.content)
    return {"enabled": row.enabled, "content": merged, "version": row.version}


async def save_global_config(db, kb_id, data: dict) -> dict:
    """保存 KB 全局配置：存储“默认+覆盖”合并后的完整结构，version 自增。"""
    row = (
        await db.execute(
            select(KbExtractionConfig).where(KbExtractionConfig.kb_id == kb_id)
        )
    ).scalar_one_or_none()
    merged = _deep_merge(_default_global_config(), data.get("content") or {})
    if row is None:
        row = KbExtractionConfig(kb_id=kb_id, enabled=bool(data.get("enabled", True)), content=merged, version=2)
        db.add(row)
    else:
        row.enabled = bool(data.get("enabled", True))
        row.content = merged
        row.version = (row.version or 1) + 1
        row.updated_at = _now()
    await db.commit()
    await db.refresh(row)
    return {"enabled": row.enabled, "content": row.content, "version": row.version}


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ============================================================
# Schema 模板
# ============================================================
def _serialize_field(f: SchemaField) -> dict:
    return {
        "id": str(f.id),
        "name": f.name,
        "type": f.type,
        "description": f.description,
        "example": f.example,
        "required": f.required,
        "sort_order": f.sort_order,
    }


def _clean_special_requirements(raw) -> dict:
    """清洗特殊要求映射：仅保留 str 值、非空文本、长度上限。"""
    out: dict = {}
    for k, v in (raw or {}).items():
        if not isinstance(v, str) or not v.strip():
            continue
        out[str(k)[:128]] = v.strip()[:1000]
    return out


async def preview_prompt(
    db: AsyncSession,
    kb_id,
    *,
    schema_template_id: str | None = None,
    category_id: str | None = None,
    group_value: str | None = None,
    system_prompt: str | None = None,
    user_prompt: str | None = None,
) -> dict:
    """Prompt 预览渲染：与真实抽取共用 prompt_renderer，保证所见即所得。

    - 传入覆盖文本（编辑中未保存）优先，缺省时渲染空模板文本；
    - 术语集类别按 group_value 指定展开类别（含 special_requirement / term_data 过滤）；
    - context 用占位说明（预览不检索）。
    """
    from types import SimpleNamespace

    from app.services.extraction import prompt_renderer
    from app.services.extraction.extraction_models import ExtractionTarget
    from app.services.extraction.term_base_loader import _read, load_term_base

    system = system_prompt if system_prompt is not None else ""
    user = user_prompt if user_prompt is not None else ""
    target: ExtractionTarget | None = None
    if category_id and schema_template_id:
        tpl = await get_schema_template(db, kb_id, schema_template_id)
        cat = next(
            (c for c in tpl.get("categories") or [] if str(c.get("id")) == str(category_id)),
            None,
        )
        if cat is None:
            raise BusinessException(code=ErrorCode.BUSINESS_NOT_FOUND, message="类别不存在")
        if group_value and group_value.strip():
            feature = group_value.strip()
        elif cat.get("name_source") == "term_base" and cat.get("name_term_base_id"):
            tb_name = (
                await db.execute(
                    select(TermBase.name).where(
                        TermBase.id == uuid.UUID(str(cat["name_term_base_id"]))
                    )
                )
            ).scalar_one_or_none()
            feature = tb_name or "术语类别"
        else:
            feature = cat.get("name") or "未命名类别"
        target = ExtractionTarget(
            feature=feature,
            category_id=str(cat["id"]),
            template_id=str(tpl["id"]),
            description=cat.get("description") or "",
            return_type=cat.get("return_type") or "array",
            extraction_strategy=cat.get("extraction_strategy") or "auto",
            fields=cat.get("fields") or [],
            special_requirement=str((cat.get("special_requirements") or {}).get(feature) or "").strip(),
        )
        properties: dict = {}
        for f in target.fields:
            prop: dict = {"type": f.get("type") or "string"}
            if f.get("required"):
                prop["required"] = True
            if f.get("description"):
                prop["description"] = f["description"]
            if f.get("example"):
                prop["example"] = f["example"]
            properties[f["name"]] = prop
        target.schema = {"type": target.return_type, "properties": properties}
        for qs in cat.get("query_sources") or []:
            label = (qs.get("label") or "").strip()
            tb_id = qs.get("term_base_id")
            if label and tb_id:
                rows = await load_term_base(db, kb_id, uuid.UUID(str(tb_id)))
                gf = (qs.get("group_field") or "").strip()
                if gf:
                    rows = [
                        r for r in rows
                        if str(_read(r, gf) or "").strip() == feature
                    ]
                target.term_data[label] = rows
    else:
        # simple 模式/无类别：空 target 渲染（feature/schema 等占位符为空）
        target = ExtractionTarget(
            feature="",
            category_id=category_id or "",
            template_id=schema_template_id or "",
        )
    cfg = SimpleNamespace(prompt_templates=[{
        "schema_template_id": schema_template_id or "",
        "categories": [{
            "category_id": category_id or "",
            "system_prompt": system,
            "user_prompt": user,
        }],
    }])
    ctx = "（文档上下文将在实际抽取时注入）"
    rendered_system, rendered_user = prompt_renderer.render_category(cfg, target, ctx)
    return {"system": rendered_system, "user": rendered_user}


async def list_term_base_expanded_names(db, kb_id, term_base_id, field: str | None = None) -> list[str]:
    """按术语集 + 取值字段返回展开类别名（与 Schema 类别展开语义一致）。

    前端新建/编辑类别配置特殊要求时直接调用，避免依赖术语列表接口的字段序列化。
    """
    from app.services.extraction.term_base_loader import (
        distinct_field_values,
        load_term_base,
    )

    rows = await load_term_base(db, kb_id, uuid.UUID(str(term_base_id)))
    f = (field or "").strip() or "term_name"
    return distinct_field_values(rows, f, 200)


async def list_expanded_category_names(db, kb_id, template_id, category_id) -> list[str]:
    """返回类别展开后的全部类别名（供前端配置术语类别特殊要求）。

    name_source=term_base 时按名称字段从术语集取值（与类别展开上限一致）；
    手动类别返回自身名称（若填写）。
    """
    c = await _get_category(db, kb_id, template_id, category_id)
    if c.name_source != "term_base" or c.name_term_base_id is None:
        return [c.name] if c.name.strip() else []
    from app.services.extraction.term_base_loader import (
        distinct_field_values,
        load_term_base,
    )

    rows = await load_term_base(db, kb_id, c.name_term_base_id)
    return distinct_field_values(rows, c.name_term_field or "term_name", 200)


def _serialize_category(c: SchemaCategory, fields: list[SchemaField] | None = None) -> dict:
    return {
        "id": str(c.id),
        "template_id": str(c.template_id),
        "name": c.name,
        "description": c.description,
        "return_type": c.return_type,
        "extraction_strategy": c.extraction_strategy,
        "fixed_query": c.fixed_query,
        "confidence_threshold": c.confidence_threshold,
        "top_k": c.top_k,
        "rerank_top_k": c.rerank_top_k,
        "max_tokens": c.max_tokens,
        "name_source": c.name_source,
        "name_term_base_id": str(c.name_term_base_id) if c.name_term_base_id else None,
        "name_term_field": c.name_term_field,
        "query_sources": c.query_sources or [],
        "special_requirements": c.special_requirements or {},
        "is_active": c.is_active,
        "sort_order": c.sort_order,
        "fields": [_serialize_field(f) for f in (fields or [])],
    }


def _serialize_template(t: SchemaTemplate, categories: list[SchemaCategory] | dict | None = None) -> dict:
    if isinstance(categories, dict):
        cat_items = [categories]
    else:
        cat_items = categories or []
    return {
        "id": str(t.id),
        "name": t.name,
        "description": t.description,
        "is_active": t.is_active,
        "sort_order": t.sort_order,
        "created_at": t.created_at.isoformat(),
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
        "categories": [c if isinstance(c, dict) else _serialize_category(c) for c in cat_items],
    }


async def _get_template(db: AsyncSession, kb_id: uuid.UUID, template_id: uuid.UUID) -> SchemaTemplate:
    t = (
        await db.execute(
            select(SchemaTemplate).where(
                SchemaTemplate.id == template_id,
                SchemaTemplate.kb_id == kb_id,
            )
        )
    ).scalar_one_or_none()
    if t is None:
        raise BusinessException(code=ErrorCode.BUSINESS_NOT_FOUND, message="Schema 模板不存在")
    return t


async def _ensure_unique_template_name(db, kb_id, name, exclude_id=None) -> None:
    stmt = select(SchemaTemplate.id).where(SchemaTemplate.kb_id == kb_id, SchemaTemplate.name == name)
    if exclude_id is not None:
        stmt = stmt.where(SchemaTemplate.id != exclude_id)
    if (await db.execute(stmt)).scalar_one_or_none() is not None:
        raise BusinessException(code=ErrorCode.BUSINESS_CONFLICT, message="Schema 模板名称已存在", http_status=409)


async def list_schema_templates(db, kb_id) -> list[dict]:
    rows = (
        await db.execute(
            select(SchemaTemplate).where(SchemaTemplate.kb_id == kb_id).order_by(
                SchemaTemplate.sort_order, SchemaTemplate.created_at
            )
        )
    ).scalars().all()
    items = []
    for t in rows:
        cats = (
            await db.execute(
                select(SchemaCategory).where(SchemaCategory.template_id == t.id).order_by(
                    SchemaCategory.sort_order, SchemaCategory.created_at
                )
            )
        ).scalars().all()
        items.append(_serialize_template(t, cats))
    return items


async def get_schema_template(db, kb_id, template_id) -> dict:
    t = await _get_template(db, kb_id, template_id)
    cats = (
        await db.execute(
            select(SchemaCategory).where(SchemaCategory.template_id == t.id).order_by(
                SchemaCategory.sort_order, SchemaCategory.created_at
            )
        )
    ).scalars().all()
    fields_map: dict[uuid.UUID, list[SchemaField]] = {}
    if cats:
        fields = (
            await db.execute(
                select(SchemaField).where(SchemaField.category_id.in_([c.id for c in cats])).order_by(
                    SchemaField.sort_order, SchemaField.created_at
                )
            )
        ).scalars().all()
        for f in fields:
            fields_map.setdefault(f.category_id, []).append(f)
    return _serialize_template(t, [
        _serialize_category(c, fields_map.get(c.id, [])) for c in cats
    ])


async def create_schema_template(db, kb_id, user_id, data: dict) -> dict:
    name = (data.get("name") or "").strip()
    await _ensure_unique_template_name(db, kb_id, name)
    t = SchemaTemplate(
        kb_id=kb_id, name=name[:128], description=(data.get("description") or "")[:2000],
        is_active=bool(data.get("is_active", True)), sort_order=int(data.get("sort_order") or 0),
        created_by=user_id,
    )
    db.add(t)
    await db.commit()
    return _serialize_template(t)


async def update_schema_template(db, kb_id, template_id, data: dict) -> dict:
    t = await _get_template(db, kb_id, template_id)
    if "name" in data:
        name = (data["name"] or "").strip()
        if name != t.name:
            await _ensure_unique_template_name(db, kb_id, name, exclude_id=t.id)
        t.name = name[:128]
    if "description" in data:
        t.description = (data["description"] or "")[:2000]
    if "is_active" in data:
        t.is_active = bool(data["is_active"])
    if "sort_order" in data:
        t.sort_order = int(data["sort_order"] or 0)
    t.updated_at = _now()
    await db.commit()
    return _serialize_template(t)


async def delete_schema_template(db, kb_id, template_id) -> None:
    t = await _get_template(db, kb_id, template_id)
    await db.delete(t)
    await db.commit()


async def _get_category(db, kb_id, template_id, category_id) -> SchemaCategory:
    c = (
        await db.execute(
            select(SchemaCategory).where(
                SchemaCategory.id == category_id,
                SchemaCategory.template_id == template_id,
                SchemaCategory.kb_id == kb_id,
            )
        )
    ).scalar_one_or_none()
    if c is None:
        raise BusinessException(code=ErrorCode.BUSINESS_NOT_FOUND, message="Schema 类别不存在")
    return c


async def _validate_term_base_ref(db, kb_id, name_source, name_term_base_id, query_sources) -> None:
    """校验术语集引用属于当前 KB。"""
    ids: set[str] = set()
    if name_source == "term_base" and name_term_base_id:
        ids.add(str(name_term_base_id))
    for qs in query_sources or []:
        tb_id = qs.get("term_base_id") if isinstance(qs, dict) else getattr(qs, "term_base_id", None)
        if tb_id:
            ids.add(str(tb_id))
    if not ids:
        return
    rows = (
        await db.execute(
            select(TermBase.id).where(TermBase.kb_id == kb_id, TermBase.id.in_([uuid.UUID(i) for i in ids]))
        )
    ).scalars().all()
    found = {str(r) for r in rows}
    missing = ids - found
    if missing:
        raise BusinessException(code=ErrorCode.VALIDATION_ERROR, message="引用的术语集不属于当前知识库")


def _qs_to_dict(qs) -> dict:
    if isinstance(qs, dict):
        return qs
    return qs.model_dump() if hasattr(qs, "model_dump") else dict(qs)


async def create_schema_category(db, kb_id, template_id, data: dict) -> dict:
    await _get_template(db, kb_id, template_id)
    query_sources = [_qs_to_dict(q) for q in (data.get("query_sources") or [])]
    await _validate_term_base_ref(
        db, kb_id, data.get("name_source", "manual"), data.get("name_term_base_id"), query_sources
    )
    c = SchemaCategory(
        kb_id=kb_id, template_id=template_id,
        name=(data.get("name") or "")[:128],
        description=(data.get("description") or "")[:2000],
        return_type=data.get("return_type", "array"),
        extraction_strategy=data.get("extraction_strategy", "auto"),
        fixed_query=(data.get("fixed_query") or "")[:2000],
        confidence_threshold=data.get("confidence_threshold"),
        top_k=data.get("top_k"), rerank_top_k=data.get("rerank_top_k"), max_tokens=data.get("max_tokens"),
        name_source=data.get("name_source", "manual"),
        name_term_base_id=uuid.UUID(str(data["name_term_base_id"])) if data.get("name_term_base_id") else None,
        name_term_field=(data.get("name_term_field") or "")[:128],
        query_sources=query_sources,
        special_requirements=_clean_special_requirements(data.get("special_requirements")),
        is_active=bool(data.get("is_active", True)),
        sort_order=int(data.get("sort_order") or 0),
    )
    db.add(c)
    await db.commit()
    return _serialize_category(c)


async def update_schema_category(db, kb_id, template_id, category_id, data: dict) -> dict:
    c = await _get_category(db, kb_id, template_id, category_id)
    if "name" in data:
        c.name = (data.get("name") or "")[:128]
    if "description" in data:
        c.description = (data.get("description") or "")[:2000]
    for field in ("return_type", "extraction_strategy", "name_source", "name_term_field"):
        if field in data and data[field] is not None:
            setattr(c, field, data[field])
    if "fixed_query" in data and data["fixed_query"] is not None:
        c.fixed_query = (data["fixed_query"] or "")[:2000]
    for field in ("confidence_threshold", "top_k", "rerank_top_k", "max_tokens"):
        if field in data:
            setattr(c, field, data[field])
    if "name_term_base_id" in data:
        c.name_term_base_id = uuid.UUID(str(data["name_term_base_id"])) if data["name_term_base_id"] else None
    if "query_sources" in data and data["query_sources"] is not None:
        query_sources = [_qs_to_dict(q) for q in data["query_sources"]]
        await _validate_term_base_ref(db, kb_id, c.name_source, c.name_term_base_id, query_sources)
        c.query_sources = query_sources
    if "special_requirements" in data and data["special_requirements"] is not None:
        c.special_requirements = _clean_special_requirements(data["special_requirements"])
    if "is_active" in data:
        c.is_active = bool(data["is_active"])
    if "sort_order" in data:
        c.sort_order = int(data["sort_order"] or 0)
    c.updated_at = _now()
    await db.commit()
    return _serialize_category(c)


async def delete_schema_category(db, kb_id, template_id, category_id) -> None:
    c = await _get_category(db, kb_id, template_id, category_id)
    # 先删除该类别对应的 PromptContent 行：若依赖 FK ON DELETE SET NULL，
    # 会与 schema 模式的 system 行（category_id IS NULL）冲突，违反 uq_prompt_content_simple
    await db.execute(
        delete(PromptContent).where(
            PromptContent.kb_id == kb_id, PromptContent.category_id == category_id
        )
    )
    await db.delete(c)
    await db.commit()


async def _get_field(db, kb_id, category_id, field_id) -> SchemaField:
    f = (
        await db.execute(
            select(SchemaField).where(
                SchemaField.id == field_id,
                SchemaField.category_id == category_id,
                SchemaField.kb_id == kb_id,
            )
        )
    ).scalar_one_or_none()
    if f is None:
        raise BusinessException(code=ErrorCode.BUSINESS_NOT_FOUND, message="Schema 字段不存在")
    return f


async def _ensure_unique_field_name(db, category_id, name, exclude_id=None) -> None:
    stmt = select(SchemaField.id).where(SchemaField.category_id == category_id, SchemaField.name == name)
    if exclude_id is not None:
        stmt = stmt.where(SchemaField.id != exclude_id)
    if (await db.execute(stmt)).scalar_one_or_none() is not None:
        raise BusinessException(code=ErrorCode.BUSINESS_CONFLICT, message="同类别字段名称已存在", http_status=409)


async def create_schema_field(db, kb_id, template_id, category_id, data: dict) -> dict:
    await _get_category(db, kb_id, template_id, category_id)
    name = (data.get("name") or "").strip()
    await _ensure_unique_field_name(db, category_id, name)
    f = SchemaField(
        kb_id=kb_id, category_id=category_id, name=name[:128],
        type=data.get("type", "string"),
        description=(data.get("description") or "")[:2000],
        example=(data.get("example") or None),
        required=bool(data.get("required", True)),
        sort_order=int(data.get("sort_order") or 0),
    )
    db.add(f)
    await db.commit()
    return _serialize_field(f)


async def update_schema_field(db, kb_id, template_id, category_id, field_id, data: dict) -> dict:
    await _get_category(db, kb_id, template_id, category_id)
    f = await _get_field(db, kb_id, category_id, field_id)
    if "name" in data:
        name = (data["name"] or "").strip()
        if name != f.name:
            await _ensure_unique_field_name(db, category_id, name, exclude_id=f.id)
        f.name = name[:128]
    if data.get("type"):
        f.type = data["type"]
    if "description" in data:
        f.description = (data.get("description") or "")[:2000]
    if "example" in data:
        f.example = data.get("example") or None
    if "required" in data:
        f.required = bool(data["required"])
    if "sort_order" in data:
        f.sort_order = int(data["sort_order"] or 0)
    f.updated_at = _now()
    await db.commit()
    return _serialize_field(f)


async def delete_schema_field(db, kb_id, template_id, category_id, field_id) -> None:
    await _get_category(db, kb_id, template_id, category_id)
    f = await _get_field(db, kb_id, category_id, field_id)
    await db.delete(f)
    await db.commit()


# ============================================================
# Prompt 模板
# ============================================================
def _serialize_prompt(p: PromptTemplate, contents: list[PromptContent], category_names: dict[str, str] | None = None) -> dict:
    simple = next((c for c in contents if c.category_id is None), None)
    names = category_names or {}
    return {
        "id": str(p.id),
        "name": p.name,
        "description": p.description,
        "scope": p.scope,
        "schema_template_id": str(p.schema_template_id) if p.schema_template_id else None,
        "category_ids": p.category_ids or [],
        "is_active": p.is_active,
        "system_prompt": simple.system_prompt if simple else "",
        "user_prompt": simple.user_prompt if simple else "",
        "categories": [
            {
                "category_id": str(c.category_id),
                "category_name": names.get(str(c.category_id), ""),
                "user_prompt": c.user_prompt,
            }
            for c in contents if c.category_id is not None
        ],
        "created_at": p.created_at.isoformat(),
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


async def _prompt_category_names(db: AsyncSession, category_ids) -> dict[str, str]:
    """批量解析 Prompt 类别名（对齐原项目 get_prompt 返回 category_name）。"""
    ids = {uuid.UUID(str(i)) for i in category_ids if i}
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(SchemaCategory.id, SchemaCategory.name).where(SchemaCategory.id.in_(ids))
        )
    ).all()
    return {str(i): n for i, n in rows}


async def _get_prompt(db, kb_id, prompt_id) -> PromptTemplate:
    p = (
        await db.execute(
            select(PromptTemplate).where(PromptTemplate.id == prompt_id, PromptTemplate.kb_id == kb_id)
        )
    ).scalar_one_or_none()
    if p is None:
        raise BusinessException(code=ErrorCode.BUSINESS_NOT_FOUND, message="Prompt 模板不存在")
    return p


async def _ensure_unique_prompt_name(db, kb_id, name, exclude_id=None) -> None:
    stmt = select(PromptTemplate.id).where(PromptTemplate.kb_id == kb_id, PromptTemplate.name == name)
    if exclude_id is not None:
        stmt = stmt.where(PromptTemplate.id != exclude_id)
    if (await db.execute(stmt)).scalar_one_or_none() is not None:
        raise BusinessException(code=ErrorCode.BUSINESS_CONFLICT, message="Prompt 模板名称已存在", http_status=409)


async def list_prompts(db, kb_id) -> list[dict]:
    rows = (
        await db.execute(select(PromptTemplate).where(PromptTemplate.kb_id == kb_id).order_by(PromptTemplate.created_at))
    ).scalars().all()
    contents_by_prompt: dict[uuid.UUID, list[PromptContent]] = {}
    if rows:
        contents = (
            await db.execute(
                select(PromptContent).where(PromptContent.prompt_id.in_([p.id for p in rows]))
            )
        ).scalars().all()
        for c in contents:
            contents_by_prompt.setdefault(c.prompt_id, []).append(c)
    category_ids = [
        c.category_id for cs in contents_by_prompt.values() for c in cs if c.category_id is not None
    ]
    names = await _prompt_category_names(db, category_ids)
    return [
        _serialize_prompt(p, contents_by_prompt.get(p.id, []), names)
        for p in rows
    ]


async def get_prompt(db, kb_id, prompt_id) -> dict:
    p = await _get_prompt(db, kb_id, prompt_id)
    contents = (
        await db.execute(select(PromptContent).where(PromptContent.prompt_id == p.id))
    ).scalars().all()
    names = await _prompt_category_names(db, [c.category_id for c in contents if c.category_id is not None])
    return _serialize_prompt(p, contents, names)


async def create_prompt(db, kb_id, user_id, data: dict) -> dict:
    name = (data.get("name") or "").strip()
    await _ensure_unique_prompt_name(db, kb_id, name)
    scope = data.get("scope", "simple")
    schema_template_id = None
    category_ids = []
    if scope == "schema":
        schema_template_id = uuid.UUID(str(data["schema_template_id"])) if data.get("schema_template_id") else None
        if schema_template_id is None:
            raise BusinessException(code=ErrorCode.VALIDATION_ERROR, message="schema 模式必须绑定 Schema 模板")
        await _get_template(db, kb_id, schema_template_id)
        category_ids = [str(c) for c in (data.get("category_ids") or [])]
    p = PromptTemplate(
        kb_id=kb_id, name=name[:128], description=(data.get("description") or "")[:2000],
        scope=scope, schema_template_id=schema_template_id,
        category_ids=category_ids, is_active=bool(data.get("is_active", True)), created_by=user_id,
    )
    db.add(p)
    await db.flush()
    if scope == "simple":
        db.add(PromptContent(
            kb_id=kb_id, prompt_id=p.id, category_id=None,
            system_prompt=(data.get("system_prompt") or ""),
            user_prompt=(data.get("user_prompt") or ""),
        ))
    await db.commit()
    return _serialize_prompt(p, [])


async def update_prompt(db, kb_id, prompt_id, data: dict) -> dict:
    p = await _get_prompt(db, kb_id, prompt_id)
    if "name" in data:
        name = (data["name"] or "").strip()
        if name != p.name:
            await _ensure_unique_prompt_name(db, kb_id, name, exclude_id=p.id)
        p.name = name[:128]
    if "description" in data:
        p.description = (data.get("description") or "")[:2000]
    if "is_active" in data:
        p.is_active = bool(data["is_active"])
    p.updated_at = _now()
    await db.commit()
    contents = (
        await db.execute(select(PromptContent).where(PromptContent.prompt_id == p.id))
    ).scalars().all()
    names = await _prompt_category_names(db, [c.category_id for c in contents if c.category_id is not None])
    return _serialize_prompt(p, contents, names)


async def save_prompt_content(db, kb_id, prompt_id, data: dict) -> dict:
    """保存 Prompt 内容：simple 全量替换；schema 按类别 upsert。"""
    p = await _get_prompt(db, kb_id, prompt_id)
    system_prompt = (data.get("system_prompt") or "")[:20000]
    user_prompt = (data.get("user_prompt") or "")[:20000]
    categories = data.get("categories") or []

    if p.scope == "simple":
        existing = (
            await db.execute(
                select(PromptContent).where(
                    PromptContent.prompt_id == p.id, PromptContent.category_id.is_(None)
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            db.add(PromptContent(kb_id=kb_id, prompt_id=p.id, category_id=None,
                                 system_prompt=system_prompt, user_prompt=user_prompt))
        else:
            existing.system_prompt = system_prompt
            existing.user_prompt = user_prompt
            existing.updated_at = _now()
    else:
        allowed: set[str] = set()
        if p.schema_template_id:
            allowed = {str(r) for r in (
                await db.execute(select(SchemaCategory.id).where(SchemaCategory.template_id == p.schema_template_id))
            ).scalars().all()}
        await db.execute(delete(PromptContent).where(PromptContent.prompt_id == p.id))
        db.add(PromptContent(kb_id=kb_id, prompt_id=p.id, category_id=None,
                             system_prompt=system_prompt, user_prompt=""))
        for item in categories:
            cat_id = uuid.UUID(str(item.get("category_id")))
            if str(cat_id) not in allowed:
                raise BusinessException(code=ErrorCode.VALIDATION_ERROR, message="类别不属于绑定 Schema 模板")
            db.add(PromptContent(
                kb_id=kb_id, prompt_id=p.id, category_id=cat_id,
                system_prompt="", user_prompt=(item.get("user_prompt") or "")[:20000],
            ))
    if data.get("is_active") is not None:
        p.is_active = bool(data["is_active"])
    p.updated_at = _now()
    await db.commit()
    contents = (
        await db.execute(select(PromptContent).where(PromptContent.prompt_id == p.id))
    ).scalars().all()
    names = await _prompt_category_names(db, [c.category_id for c in contents if c.category_id is not None])
    return _serialize_prompt(p, contents, names)


async def delete_prompt(db, kb_id, prompt_id) -> None:
    p = await _get_prompt(db, kb_id, prompt_id)
    await db.delete(p)
    await db.commit()


# ============================================================
# 规则组
# ============================================================
def _serialize_group(g: RuleGroup, template_name: str = "", category_count: int = 0, item_count: int = 0) -> dict:
    return {
        "id": str(g.id),
        "name": g.name,
        "schema_template_id": str(g.schema_template_id) if g.schema_template_id else None,
        "schema_template_name": template_name,
        "description": g.description,
        "enabled": g.enabled,
        "category_count": category_count,
        "item_count": item_count,
        "created_at": g.created_at.isoformat(),
    }


async def _get_group(db, kb_id, group_id) -> RuleGroup:
    g = (
        await db.execute(select(RuleGroup).where(RuleGroup.id == group_id, RuleGroup.kb_id == kb_id))
    ).scalar_one_or_none()
    if g is None:
        raise BusinessException(code=ErrorCode.BUSINESS_NOT_FOUND, message="规则组不存在")
    return g


async def list_rule_groups(db, kb_id) -> list[dict]:
    rows = (
        await db.execute(select(RuleGroup).where(RuleGroup.kb_id == kb_id).order_by(RuleGroup.created_at))
    ).scalars().all()
    items = []
    for g in rows:
        tpl = None
        if g.schema_template_id:
            tpl = (
                await db.execute(select(SchemaTemplate.name).where(SchemaTemplate.id == g.schema_template_id))
            ).scalar_one_or_none()
        cat_count = 0
        if g.schema_template_id:
            cat_count = (
                await db.execute(
                    select(func.count()).select_from(SchemaCategory).where(
                        SchemaCategory.template_id == g.schema_template_id
                    )
                )
            ).scalar_one()
        item_count = (
            await db.execute(select(func.count()).select_from(RuleGroupItem).where(RuleGroupItem.group_id == g.id))
        ).scalar_one()
        items.append(_serialize_group(g, tpl or "", int(cat_count or 0), int(item_count or 0)))
    return items


async def create_rule_group(db, kb_id, data: dict) -> dict:
    tpl_id = uuid.UUID(str(data["schema_template_id"]))
    tpl = await _get_template(db, kb_id, tpl_id)
    exists = (
        await db.execute(select(RuleGroup.id).where(RuleGroup.kb_id == kb_id, RuleGroup.schema_template_id == tpl_id))
    ).scalar_one_or_none()
    if exists is not None:
        raise BusinessException(code=ErrorCode.BUSINESS_CONFLICT, message="该 Schema 模板已存在规则组", http_status=409)
    g = RuleGroup(
        kb_id=kb_id, name=((data.get("name") or "").strip() or tpl.name)[:128],
        schema_template_id=tpl_id, description=(data.get("description") or "")[:2000],
    )
    db.add(g)
    await db.commit()
    return {"id": str(g.id)}


async def get_rule_group(db, kb_id, group_id) -> dict:
    g = await _get_group(db, kb_id, group_id)
    tpl = await _get_template(db, kb_id, g.schema_template_id) if g.schema_template_id else None
    cats: list[SchemaCategory] = []
    if tpl:
        cats = (
            await db.execute(
                select(SchemaCategory).where(SchemaCategory.template_id == tpl.id).order_by(
                    SchemaCategory.sort_order, SchemaCategory.created_at
                )
            )
        ).scalars().all()
    # 批量解析 term_base 来源类别名：name 为空时回退术语集名称（对齐原项目）
    term_base_ids = {
        c.name_term_base_id
        for c in cats
        if c.name_source == "term_base" and not (c.name or "").strip() and c.name_term_base_id
    }
    term_names: dict[str, str] = {}
    if term_base_ids:
        term_rows = (
            await db.execute(
                select(TermBase.id, TermBase.name).where(
                    TermBase.kb_id == kb_id, TermBase.id.in_(list(term_base_ids))
                )
            )
        ).all()
        term_names = {str(t): n for t, n in term_rows}
    items = (
        await db.execute(
            select(RuleGroupItem).where(RuleGroupItem.group_id == g.id).order_by(
                RuleGroupItem.sort_order, RuleGroupItem.created_at
            )
        )
    ).scalars().all()
    script_map: dict[str, KbScript] = {}
    if items:
        script_ids = {it.script_id for it in items if it.script_id}
        if script_ids:
            scripts = (
                await db.execute(select(KbScript).where(KbScript.id.in_(list(script_ids))))
            ).scalars().all()
            script_map = {str(x.id): x for x in scripts}
    by_cat: dict[str, list[dict]] = {}
    for it in items:
        key = str(it.category_id) if it.category_id else ""
        sc = script_map.get(str(it.script_id)) if it.script_id else None
        by_cat.setdefault(key, []).append({
            "id": str(it.id),
            "category_id": str(it.category_id) if it.category_id else None,
            "category_name": it.category_name or "",
            "script_id": str(it.script_id) if it.script_id else None,
            "script_name": sc.name if sc else "",
            "script_description": sc.description if sc else "",
            "stage": it.stage,
            "sort_order": it.sort_order,
        })
    categories = []
    for c in cats:
        cat_name = c.name or ""
        if not cat_name.strip() and c.name_source == "term_base":
            cat_name = term_names.get(str(c.name_term_base_id)) or cat_name
        categories.append({"id": str(c.id), "name": cat_name, "rules": by_cat.get(str(c.id), [])})
    if "" in by_cat:
        categories.append({"id": "", "name": "全局", "rules": by_cat[""]})
    return {
        "id": str(g.id),
        "name": g.name,
        "schema_template_id": str(g.schema_template_id) if g.schema_template_id else None,
        "schema_template_name": tpl.name if tpl else "",
        "description": g.description,
        "categories": categories,
    }


async def save_rule_group_items(db, kb_id, group_id, data: dict) -> dict:
    """按类别全量替换规则项。"""
    g = await _get_group(db, kb_id, group_id)
    category_id = uuid.UUID(str(data["category_id"])) if data.get("category_id") else None
    if category_id is not None:
        exists = (
            await db.execute(
                select(SchemaCategory.id).where(
                    SchemaCategory.id == category_id,
                    SchemaCategory.kb_id == kb_id,
                )
            )
        ).scalar_one_or_none()
        if exists is None:
            raise BusinessException(code=ErrorCode.VALIDATION_ERROR, message="类别不属于当前知识库")
    stmt = delete(RuleGroupItem).where(RuleGroupItem.group_id == g.id)
    if category_id is None:
        stmt = stmt.where(RuleGroupItem.category_id.is_(None))
    else:
        stmt = stmt.where(RuleGroupItem.category_id == category_id)
    await db.execute(stmt)
    for idx, item in enumerate(data.get("items") or []):
        script_id = uuid.UUID(str(item["script_id"])) if item.get("script_id") else None
        if script_id is None:
            raise BusinessException(code=ErrorCode.VALIDATION_ERROR, message="规则项必须选择脚本")
        exists = (
            await db.execute(select(KbScript.id).where(KbScript.id == script_id, KbScript.kb_id == kb_id))
        ).scalar_one_or_none()
        if exists is None:
            raise BusinessException(code=ErrorCode.VALIDATION_ERROR, message="所选脚本不属于当前知识库")
        db.add(RuleGroupItem(
            kb_id=kb_id, group_id=g.id, category_id=category_id,
            category_name=(item.get("category_name") or "")[:128],
            script_id=script_id,
            stage=item.get("stage", "post"),
            params={},
            enabled=True,
            sort_order=int(item.get("sort_order") or idx),
        ))
    g.updated_at = _now()
    await db.commit()
    return {"message": "规则项已保存"}


async def delete_rule_group(db, kb_id, group_id) -> None:
    g = await _get_group(db, kb_id, group_id)
    await db.delete(g)
    await db.commit()


# ============================================================
# 脚本
# ============================================================
_TOOL_CATALOG = [
    {
        "name": "embed",
        "desc": "文本向量化：把文本转成 bge-m3 的 1024 维稠密向量（已归一化），是语义检索的第一步。",
        "params": [
            {"name": "texts", "type": "str | list[str]", "desc": "单个文本或文本列表"},
        ],
        "returns": "list[list[float]]（每个文本对应一个 1024 维向量，顺序与入参一致）",
        "usage": 'vecs = await kb_tools.embed("拉伸强度")\n# 或整批：vecs = await kb_tools.embed(["a", "b"])',
    },
    {
        "name": "semantic_search",
        "desc": "语义检索：在传入的记录列表内，用查询词与指定字段做相似度检索，返回最相似的 top_k 条（内部自动向量化）。",
        "params": [
            {"name": "records", "type": "list[dict]", "desc": "待检索的记录列表（通常来自 get_term_records）"},
            {"name": "query", "type": "str", "desc": "查询词"},
            {"name": "match_fields", "type": "str | list[str]", "desc": "参与匹配的字段名（可单个或多个）"},
            {"name": "top_k", "type": "int", "desc": "返回结果数，默认 5"},
            {"name": "return_fields", "type": "list[str] | None", "desc": "仅返回字段（可选），缺省返回全字段"},
        ],
        "returns": "list[dict]（按相似度降序，含 score 字段）",
        "usage": 'top = await kb_tools.semantic_search(rows, "Q235B", ["牌号"], top_k=1)',
    },
    {
        "name": "match_record",
        "desc": "单条匹配：对一条查询词做语义检索，相似度 ≥ 阈值判为命中；失败回退精确/编辑距离匹配。用于项目名、牌号等归一化。",
        "params": [
            {"name": "name", "type": "str", "desc": "待匹配的查询词"},
            {"name": "records", "type": "list[dict]", "desc": "候选记录列表（通常来自 get_term_records）"},
            {"name": "match_fields", "type": "str | list[str]", "desc": "参与匹配的字段名"},
            {"name": "threshold", "type": "float", "desc": "语义命中阈值，默认 0.90"},
        ],
        "returns": "{canonical(标准化名), score(置信度), type(匹配类型 vector/exact/edit_distance/unverified), record(命中的原始记录)}",
        "usage": 'hit = await kb_tools.match_record("Rp0.2", rows, ["项目名称"])\n# if hit["type"] != "unverified": r["项目名称"] = hit["canonical"]',
    },
    {
        "name": "get_term_records",
        "desc": "取术语集记录：按术语集名称读取当前知识库下该术语集的全部记录，返回对象列表（键为修改后的字段名）。",
        "params": [
            {"name": "name", "type": "str", "desc": "术语集名称（TermBase.name）"},
            {"name": "*fields", "type": "str", "desc": "需要的字段名（优先按新表头名，可传多个）"},
        ],
        "returns": "list[dict]（每条记录一个 dict，键为传入的字段名；术语集不存在返回空列表）",
        "usage": 'rows = await kb_tools.get_term_records("材料牌号", "牌号", "厂家")\n# rows = [{"牌号": "Q235B", "厂家": "宝钢"}, ...]',
    },
]

SCRIPT_IO_REGISTRY = {
    "post": {
        "input": [
            {"name": "records", "type": "list", "description": "抽取结果记录列表"},
            {"name": "category", "type": "string", "description": "当前类别"},
            {"name": "doc_id", "type": "string", "description": "文档 ID"},
        ],
        "output": [
            {"name": "records", "type": "list", "description": "处理后的记录"},
            {"name": "rejected", "type": "list", "description": "剔除的记录（可选）"},
        ],
        "tools": _TOOL_CATALOG,
    },
    "validation": {
        "input": [
            {"name": "records", "type": "list", "description": "待校验记录"},
            {"name": "category", "type": "string", "description": "当前类别"},
            {"name": "doc_id", "type": "string", "description": "文档 ID"},
        ],
        "output": [
            {"name": "records", "type": "list", "description": "校验通过的记录"},
            {"name": "rejected", "type": "list", "description": "校验失败记录"},
        ],
        "tools": _TOOL_CATALOG,
    },
}


def script_io_registry() -> dict:
    return {"folders": SCRIPT_IO_REGISTRY}


def _serialize_script(s: KbScript) -> dict:
    return {
        "id": str(s.id),
        "folder": s.folder,
        "name": s.name,
        "description": s.description,
        "enabled": s.enabled,
        "code": s.code,
        "created_at": s.created_at.isoformat(),
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }


async def _get_script(db, kb_id, script_id) -> KbScript:
    s = (
        await db.execute(select(KbScript).where(KbScript.id == script_id, KbScript.kb_id == kb_id))
    ).scalar_one_or_none()
    if s is None:
        raise BusinessException(code=ErrorCode.BUSINESS_NOT_FOUND, message="脚本不存在")
    return s


async def _ensure_unique_script(db, kb_id, folder, name, exclude_id=None) -> None:
    stmt = select(KbScript.id).where(KbScript.kb_id == kb_id, KbScript.folder == folder, KbScript.name == name)
    if exclude_id is not None:
        stmt = stmt.where(KbScript.id != exclude_id)
    if (await db.execute(stmt)).scalar_one_or_none() is not None:
        raise BusinessException(code=ErrorCode.BUSINESS_CONFLICT, message="同目录脚本名称已存在", http_status=409)


async def list_scripts(db, kb_id, folder: str | None = None) -> list[dict]:
    stmt = select(KbScript).where(KbScript.kb_id == kb_id)
    if folder:
        stmt = stmt.where(KbScript.folder == folder)
    rows = (await db.execute(stmt.order_by(KbScript.created_at))).scalars().all()
    return [_serialize_script(s) for s in rows]


async def create_script(db, kb_id, user_id, data: dict) -> dict:
    folder = data.get("folder", "post")
    name = (data.get("name") or "").strip()
    await _ensure_unique_script(db, kb_id, folder, name)
    s = KbScript(
        kb_id=kb_id, folder=folder, name=name[:128],
        description=(data.get("description") or "")[:2000],
        enabled=bool(data.get("enabled", True)),
        code=data.get("code") or "", created_by=user_id,
    )
    db.add(s)
    await db.commit()
    return {"id": str(s.id)}


async def update_script(db, kb_id, script_id, data: dict) -> dict:
    s = await _get_script(db, kb_id, script_id)
    if data.get("folder"):
        s.folder = data["folder"]
    if "name" in data:
        name = (data["name"] or "").strip()
        await _ensure_unique_script(db, kb_id, s.folder, name, exclude_id=s.id)
        s.name = name[:128]
    if "description" in data:
        s.description = (data.get("description") or "")[:2000]
    if "enabled" in data:
        s.enabled = bool(data["enabled"])
    if "code" in data:
        s.code = data["code"] or ""
    s.updated_at = _now()
    await db.commit()
    return {"message": "脚本已更新"}


async def delete_script(db, kb_id, script_id) -> None:
    s = await _get_script(db, kb_id, script_id)
    await db.delete(s)
    await db.commit()


async def _load_term_data(db, kb_id, max_rows: int | None = None) -> dict:
    """按术语集名称构建 {名称: [记录 dict]}（active 词条，上限保护）。"""
    limit = max_rows or SCRIPT_MAX_TERM_ROWS
    return await script_tools.load_term_data(db, kb_id, max_rows=limit)


async def run_script(db, kb_id, data: dict) -> dict:
    """受限子进程执行脚本（-I 隔离、超时/输出上限、注入术语集只读数据 + 真实 kb_tools）。"""
    code = (data.get("code") or "").strip()
    if not code and data.get("script_id"):
        script = await _get_script(db, kb_id, uuid.UUID(str(data["script_id"])))
        code = script.code
    if not code.strip():
        raise BusinessException(code=ErrorCode.VALIDATION_ERROR, message="脚本代码不能为空")
    if "def run(args):" not in code:
        raise BusinessException(code=ErrorCode.VALIDATION_ERROR, message="脚本需定义 def run(args): 并返回 dict")
    # 全局配置优先（kb_tool），缺省回退常量
    gcfg = await get_global_config(db, kb_id)
    kb_tool = gcfg["content"].get("kb_tool") or {}
    timeout = int(kb_tool.get("script_timeout") or SCRIPT_TIMEOUT)
    max_output = int(kb_tool.get("script_max_output_bytes") or SCRIPT_MAX_OUTPUT)
    max_term_rows = int(kb_tool.get("script_max_term_rows") or SCRIPT_MAX_TERM_ROWS)
    term_data = await _load_term_data(db, kb_id, max_rows=max_term_rows)
    token = script_tools.issue_embed_token(kb_id)
    try:
        payload = script_tools.build_script_code(code)
        stdin = json.dumps(
            {
                "args": data.get("args") or {},
                "term_data": term_data,
                "embed": {"url": script_tools.embed_endpoint_url(kb_id), "token": token},
            },
            ensure_ascii=False,
        )
        try:
            proc = await asyncio.to_thread(
                subprocess.run,
                [sys.executable, "-I", "-c", payload],
                input=stdin,
                capture_output=True, text=True, timeout=timeout, check=False,
            )
        except subprocess.TimeoutExpired:
            logger.warning("脚本调试超时", kb_id=str(kb_id))
            return {"ok": False, "error": f"脚本执行超时（{timeout}s）"}
        stdout = (proc.stdout or "")[:max_output]
        stderr = (proc.stderr or "")[:max_output]
        if proc.returncode != 0:
            return {"ok": False, "error": stderr.strip() or "脚本执行失败"}
        try:
            result = json.loads(stdout.strip().splitlines()[-1] if stdout.strip() else "null")
        except (ValueError, IndexError):
            return {"ok": False, "error": stderr.strip() or "脚本未返回合法 JSON"}
        return {"ok": True, "result": result}
    finally:
        script_tools.revoke_embed_token(token)
