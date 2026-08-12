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
    KbScript,
    PromptContent,
    PromptTemplate,
    RuleGroup,
    RuleGroupItem,
    SchemaCategory,
    SchemaField,
    SchemaTemplate,
)
from app.models.glossary import TERM_STATUS_ACTIVE, Term, TermBase

logger = get_logger(__name__)

SCRIPT_TIMEOUT = 10  # 脚本调试超时（秒）
SCRIPT_MAX_OUTPUT = 1024 * 1024  # 输出上限 1MB
SCRIPT_MAX_TERM_ROWS = 1000  # 注入术语集每库最大词条数


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
    if "is_active" in data:
        c.is_active = bool(data["is_active"])
    if "sort_order" in data:
        c.sort_order = int(data["sort_order"] or 0)
    c.updated_at = _now()
    await db.commit()
    return _serialize_category(c)


async def delete_schema_category(db, kb_id, template_id, category_id) -> None:
    c = await _get_category(db, kb_id, template_id, category_id)
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
def _serialize_prompt(p: PromptTemplate, contents: list[PromptContent]) -> dict:
    simple = next((c for c in contents if c.category_id is None), None)
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
            {"category_id": str(c.category_id), "user_prompt": c.user_prompt}
            for c in contents if c.category_id is not None
        ],
        "created_at": p.created_at.isoformat(),
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


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
    items = []
    for p in rows:
        contents = (
            await db.execute(select(PromptContent).where(PromptContent.prompt_id == p.id))
        ).scalars().all()
        items.append(_serialize_prompt(p, contents))
    return items


async def get_prompt(db, kb_id, prompt_id) -> dict:
    p = await _get_prompt(db, kb_id, prompt_id)
    contents = (
        await db.execute(select(PromptContent).where(PromptContent.prompt_id == p.id))
    ).scalars().all()
    return _serialize_prompt(p, contents)


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
    return _serialize_prompt(p, contents)


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
    return _serialize_prompt(p, contents)


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
    items = (
        await db.execute(
            select(RuleGroupItem).where(RuleGroupItem.group_id == g.id).order_by(
                RuleGroupItem.sort_order, RuleGroupItem.created_at
            )
        )
    ).scalars().all()
    by_cat: dict[str, list[dict]] = {}
    for it in items:
        key = str(it.category_id) if it.category_id else ""
        by_cat.setdefault(key, []).append({
            "id": str(it.id),
            "category_id": str(it.category_id) if it.category_id else None,
            "script_name": it.script_name,
            "params": it.params or {},
            "enabled": it.enabled,
            "sort_order": it.sort_order,
        })
    categories = [
        {"id": str(c.id), "name": c.name or "", "rules": by_cat.get(str(c.id), [])}
        for c in cats
    ]
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
        db.add(RuleGroupItem(
            kb_id=kb_id, group_id=g.id, category_id=category_id,
            script_name=(item.get("script_name") or "").strip()[:128],
            params=item.get("params") or {},
            enabled=bool(item.get("enabled", True)),
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
        "tools": [
            "kb_tools.get_term_records(术语集名称, 字段名)",
            "kb_tools.embed(text)",
            "kb_tools.semantic_search(query, top_k)",
            "kb_tools.match_record(query, rows, fields)",
        ],
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
        "tools": [
            "kb_tools.get_term_records(术语集名称, 字段名)",
            "kb_tools.embed(text)",
            "kb_tools.semantic_search(query, top_k)",
            "kb_tools.match_record(query, rows, fields)",
        ],
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


async def _load_term_data(db, kb_id) -> dict:
    """按术语集名称构建 {名称: {字段: [值]}} 只读数据（active 词条，上限保护）。"""
    bases = (
        await db.execute(select(TermBase).where(TermBase.kb_id == kb_id).order_by(TermBase.created_at))
    ).scalars().all()
    data: dict[str, dict[str, list[str]]] = {}
    for b in bases:
        terms = (
            await db.execute(
                select(Term).where(
                    Term.kb_id == kb_id,
                    Term.term_base_id == b.id,
                    Term.status == TERM_STATUS_ACTIVE,
                ).limit(SCRIPT_MAX_TERM_ROWS)
            )
        ).scalars().all()
        bucket: dict[str, list[str]] = {}
        for t in terms:
            for field, value in (
                ("term_name", t.term_name),
                ("standard_name", t.standard_name),
                ("english_term", t.english_term),
                ("definition", t.definition),
                ("category", t.category),
                ("standard_number", t.standard_number),
            ):
                if value:
                    bucket.setdefault(field, []).append(value)
            for alias in (t.aliases or []):
                if alias:
                    bucket.setdefault("aliases", []).append(alias)
            for synonym in (t.synonyms or []):
                if synonym:
                    bucket.setdefault("synonyms", []).append(synonym)
            for k, v in (t.extras or {}).items():
                if v is not None:
                    bucket.setdefault(str(k), []).append(str(v))
        data[b.name] = bucket
    return data


_RUN_TEMPLATE = """import asyncio
import json
import sys

TERM_DATA = {term_data}

class _KbTools:
    async def get_term_records(self, name, field):
        return TERM_DATA.get(name, {{}}).get(field, [])
    async def embed(self, text):
        return {{"text": text, "vector": []}}
    async def semantic_search(self, query, top_k=5):
        return []
    async def match_record(self, query, rows, fields):
        return []

kb_tools = _KbTools()

{code}

async def _main():
    args = json.loads(sys.stdin.read())
    result = run(args)
    if asyncio.iscoroutine(result):
        result = await result
    sys.stdout.write(json.dumps(result, ensure_ascii=False, default=str))

asyncio.run(_main())
"""


async def run_script(db, kb_id, data: dict) -> dict:
    """受限子进程执行脚本（-I 隔离、10s 超时、1MB 输出上限、注入术语集只读数据）。"""
    code = (data.get("code") or "").strip()
    if not code and data.get("script_id"):
        script = await _get_script(db, kb_id, uuid.UUID(str(data["script_id"])))
        code = script.code
    if not code.strip():
        raise BusinessException(code=ErrorCode.VALIDATION_ERROR, message="脚本代码不能为空")
    if "def run(args):" not in code:
        raise BusinessException(code=ErrorCode.VALIDATION_ERROR, message="脚本需定义 def run(args): 并返回 dict")
    term_data = await _load_term_data(db, kb_id)
    payload = _RUN_TEMPLATE.format(term_data=json.dumps(term_data, ensure_ascii=False), code=code)
    try:
        proc = await asyncio.to_thread(
            subprocess.run,
            [sys.executable, "-I", "-c", payload],
            input=json.dumps(data.get("args") or {}, ensure_ascii=False),
            capture_output=True, text=True, timeout=SCRIPT_TIMEOUT, check=False,
        )
    except subprocess.TimeoutExpired:
        logger.warning("脚本调试超时", kb_id=str(kb_id))
        return {"ok": False, "error": f"脚本执行超时（{SCRIPT_TIMEOUT}s）"}
    stdout = (proc.stdout or "")[:SCRIPT_MAX_OUTPUT]
    stderr = (proc.stderr or "")[:SCRIPT_MAX_OUTPUT]
    if proc.returncode != 0:
        return {"ok": False, "error": stderr.strip() or "脚本执行失败"}
    try:
        result = json.loads(stdout.strip().splitlines()[-1] if stdout.strip() else "null")
    except (ValueError, IndexError):
        return {"ok": False, "error": stderr.strip() or "脚本未返回合法 JSON"}
    return {"ok": True, "result": result}
