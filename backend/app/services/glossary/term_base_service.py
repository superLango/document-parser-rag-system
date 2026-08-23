"""术语集业务服务（S8/S2）：CRUD、外部源同步、导入与 cron 扫描。"""

from __future__ import annotations

import re
import uuid
from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import BusinessException, ErrorCode
from app.core.logging import get_logger
from app.models.glossary import (
    SOURCE_TYPE_API,
    SOURCE_TYPE_DB,
    SOURCE_TYPE_MANUAL,
    TERM_STATUS_ACTIVE,
    Term,
    TermBase,
)

from . import source_api, source_db
from .security import (
    encrypt_secrets,
    mask_secrets,
    validate_api_url,
    validate_source_host,
)

logger = get_logger(__name__)

_IMPORT_LIMIT = settings.TERM_SYNC_IMPORT_LIMIT


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clean_cron(expr: str) -> str:
    """清洗 cron 表达式：空白/注释去除，返回标准表达式。"""
    expr = (expr or "").strip().strip("@").strip()
    if not expr:
        return ""
    if len(expr) > 64:
        raise BusinessException(code=ErrorCode.VALIDATION_ERROR, message="cron 表达式过长（≤64 字符）")
    validate_cron(expr)
    return expr


def validate_cron(expr: str) -> dict:
    """校验 cron 表达式并返回下次执行时间（croniter）。"""
    from croniter import croniter

    try:
        it = croniter(expr, datetime.now(timezone.utc))
        nxt = it.get_next(datetime)
    except (ValueError, KeyError) as exc:
        raise BusinessException(
            code=ErrorCode.VALIDATION_ERROR, message=f"无效的 cron 表达式：{exc}"
        ) from exc
    return {"cron": expr, "next_run_at": nxt.isoformat()}


def _compute_next_run(expr: str, base_time: datetime | None = None) -> datetime:
    from croniter import croniter

    it = croniter(expr, base_time or datetime.now(timezone.utc))
    return it.get_next(datetime)


def _validate_source_config(source_type: str, config: dict) -> None:
    """创建/更新时提前校验外部源地址（SSRF 防护前置，失败转 400）。"""
    if not config:
        return
    try:
        if source_type == SOURCE_TYPE_API and config.get("url"):
            validate_api_url(str(config["url"]))
        elif source_type == SOURCE_TYPE_DB and config.get("host"):
            validate_source_host(str(config["host"]))
    except ValueError as exc:
        raise BusinessException(
            code=ErrorCode.VALIDATION_ERROR, message=str(exc)
        ) from exc


def _serialize_base(base: TermBase, term_count: int = 0, masked: bool = True) -> dict:
    """术语集序列化（凭据默认掩码）。"""
    cfg = base.source_config or {}
    return {
        "id": str(base.id),
        "kb_id": str(base.kb_id),
        "name": base.name,
        "description": base.description,
        "source_type": base.source_type,
        "source_config": mask_secrets(cfg) if masked else cfg,
        "columns": base.columns or [],
        "column_aliases": base.column_aliases or {},
        "sync_enabled": base.sync_enabled,
        "sync_cron": base.sync_cron,
        "sync_next_run_at": base.sync_next_run_at.isoformat() if base.sync_next_run_at else None,
        "sync_status": base.sync_status,
        "sync_last_error": base.sync_last_error,
        "last_synced_at": base.last_synced_at.isoformat() if base.last_synced_at else None,
        "status": base.status,
        "term_count": term_count,
        "created_at": base.created_at.isoformat(),
        "updated_at": base.updated_at.isoformat() if base.updated_at else None,
    }


async def list_term_bases(
    db: AsyncSession, kb_id: uuid.UUID, keyword: str | None, page: int, page_size: int
) -> tuple[list[dict], int]:
    base = select(TermBase).where(TermBase.kb_id == kb_id, TermBase.deleted_at.is_(None))
    count_base = (
        select(func.count())
        .select_from(TermBase)
        .where(TermBase.kb_id == kb_id, TermBase.deleted_at.is_(None))
    )
    if keyword:
        like = f"%{keyword}%"
        cond = or_(TermBase.name.ilike(like), TermBase.description.ilike(like))
        base = base.where(cond)
        count_base = count_base.where(cond)
    total = (await db.execute(count_base)).scalar_one()
    rows = (
        await db.execute(
            base.order_by(TermBase.created_at.desc())
            .offset((page - 1) * page_size).limit(page_size)
        )
    ).scalars().all()
    counts = {}
    if rows:
        base_ids = [r.id for r in rows]
        cnt = (
            await db.execute(
                select(Term.term_base_id, func.count())
                .where(
                    Term.term_base_id.in_(base_ids),
                    Term.deleted_at.is_(None),
                )
                .group_by(Term.term_base_id)
            )
        ).all()
        counts = {str(bid): c for bid, c in cnt}
    items = [_serialize_base(r, counts.get(str(r.id), 0)) for r in rows]
    return items, total


async def _ensure_unique_name(db: AsyncSession, kb_id: uuid.UUID, name: str) -> None:
    exists = (
        await db.execute(
            select(TermBase.id).where(
                TermBase.kb_id == kb_id,
                TermBase.name == name,
                TermBase.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if exists is not None:
        raise BusinessException(code=ErrorCode.BUSINESS_CONFLICT, message="术语集名称已存在", http_status=409)


async def create_term_base(
    db: AsyncSession,
    kb_id: uuid.UUID,
    user_id: uuid.UUID | None,
    data: dict,
) -> dict:
    """创建术语集；auto_import 时导入 import_data（manual 词条 active）。"""
    name = (data.get("name") or "").strip()
    if not name:
        raise BusinessException(code=ErrorCode.VALIDATION_ERROR, message="术语集名称不能为空")
    if len(name) > 128:
        raise BusinessException(code=ErrorCode.VALIDATION_ERROR, message="术语集名称过长")
    source_type = data.get("source_type") or SOURCE_TYPE_MANUAL
    if source_type not in (SOURCE_TYPE_MANUAL, SOURCE_TYPE_API, SOURCE_TYPE_DB):
        raise BusinessException(code=ErrorCode.VALIDATION_ERROR, message="无效的数据源类型")
    # 咨询锁串行化同 KB 同名词条创建，避免并发穿透唯一预检查
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
        {"key": f"term-base:{kb_id}:{name}"},
    )
    await _ensure_unique_name(db, kb_id, name)
    _validate_source_config(source_type, data.get("source_config") or {})

    base = TermBase(
        kb_id=kb_id,
        name=name,
        description=(data.get("description") or "")[:2000],
        source_type=source_type,
        source_config=encrypt_secrets(data.get("source_config") or {}),
        columns=data.get("columns") or [],
        column_aliases=data.get("column_aliases") or {},
        sync_enabled=bool(data.get("sync_enabled")),
        sync_cron=_clean_cron(data.get("sync_cron") or ""),
        created_by=user_id,
    )
    db.add(base)
    await db.flush()
    imported = 0
    if data.get("auto_import"):
        imported = await import_terms(
            db, kb_id, base.id, user_id,
            data.get("import_data") or [], source_type=SOURCE_TYPE_MANUAL,
        )
    await db.commit()
    return {**_serialize_base(base, imported), "imported": imported}


async def get_term_base(db: AsyncSession, kb_id: uuid.UUID, base_id: uuid.UUID) -> TermBase:
    base = (
        await db.execute(
            select(TermBase).where(
                TermBase.id == base_id,
                TermBase.kb_id == kb_id,
                TermBase.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if base is None:
        raise BusinessException(code=ErrorCode.BUSINESS_NOT_FOUND, message="术语集不存在")
    return base


async def get_term_base_detail(
    db: AsyncSession, kb_id: uuid.UUID, base_id: uuid.UUID
) -> dict:
    base = await get_term_base(db, kb_id, base_id)
    count = (
        await db.execute(
            select(func.count()).select_from(Term).where(
                Term.term_base_id == base.id,
                Term.deleted_at.is_(None),
            )
        )
    ).scalar_one()
    return _serialize_base(base, count)


async def update_term_base(
    db: AsyncSession, kb_id: uuid.UUID, base_id: uuid.UUID, data: dict
) -> dict:
    base = await get_term_base(db, kb_id, base_id)
    if "name" in data:
        name = (data["name"] or "").strip()
        if not name:
            raise BusinessException(code=ErrorCode.VALIDATION_ERROR, message="术语集名称不能为空")
        if name != base.name:
            await _ensure_unique_name(db, kb_id, name)
        base.name = name[:128]
    if "description" in data:
        base.description = (data["description"] or "")[:2000]
    if "source_config" in data:
        # 合并更新（保留未提交的既有加密字段）
        _validate_source_config(base.source_type, data["source_config"] or {})
        merged = {**(base.source_config or {}), **encrypt_secrets(data["source_config"] or {})}
        base.source_config = merged
    if "columns" in data:
        base.columns = data["columns"] or []
    if "column_aliases" in data:
        base.column_aliases = data["column_aliases"] or {}
    if "sync_enabled" in data:
        base.sync_enabled = bool(data["sync_enabled"])
    if "sync_cron" in data and data["sync_cron"] is not None:
        expr = _clean_cron(str(data["sync_cron"]))
        if expr:
            # 合法 cron 才保存，并立即计算下次执行时间
            base.sync_cron = expr
            base.sync_next_run_at = _compute_next_run(expr)
        else:
            base.sync_cron = ""
            base.sync_next_run_at = None
    await db.commit()
    return _serialize_base(base)


async def delete_term_base(db: AsyncSession, kb_id: uuid.UUID, base_id: uuid.UUID) -> None:
    """硬删术语集及其词条（对齐原项目，FK CASCADE 级联删除）。"""
    base = await get_term_base(db, kb_id, base_id)
    await db.delete(base)
    await db.commit()


async def import_terms(
    db: AsyncSession,
    kb_id: uuid.UUID,
    base_id: uuid.UUID,
    user_id: uuid.UUID | None,
    items: list[dict],
    source_type: str = SOURCE_TYPE_MANUAL,
) -> int:
    """幂等导入词条：按 (kb, base, term_name) upsert。

    手动导入 status=active；外部同步由调用方传 PENDING。
    """
    if len(items) > _IMPORT_LIMIT:
        raise BusinessException(
            code=ErrorCode.VALIDATION_ERROR,
            message=f"单次导入不能超过 {_IMPORT_LIMIT} 条",
        )
    # 对齐原项目：manual 与外部同步词条均 active（api/db 只读，无审核入口）
    status = TERM_STATUS_ACTIVE
    # 批内同名聚合：后到条目补充字段（避免统一 flush 前互相不可见触发唯一冲突）
    merged_items: dict[str, dict] = {}
    for raw in items:
        name = str(raw.get("term") or raw.get("term_name") or "").strip()
        if not name:
            continue
        name = name[:256]
        if name in merged_items:
            merged_items[name].update(raw)
            continue
        merged_items[name] = raw

    imported = 0
    for name, raw in merged_items.items():
        existing = (
            await db.execute(
                select(Term).where(
                    Term.kb_id == kb_id,
                    Term.term_base_id == base_id,
                    Term.term_name == name,
                    Term.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            existing.standard_name = str(raw.get("standard_name") or existing.standard_name or "")[:256]
            existing.english_term = str(raw.get("english_term") or existing.english_term or "")[:256]
            existing.definition = str(raw.get("definition") or existing.definition or "")[:2000]
            existing.category = str(raw.get("category") or existing.category or "")[:128]
            existing.standard_number = str(raw.get("standard_number") or existing.standard_number or "")[:128]
            if raw.get("synonyms"):
                existing.synonyms = list(raw["synonyms"])[:50]
            if raw.get("aliases"):
                existing.aliases = list(raw["aliases"])[:50]
            existing.extras = {**(existing.extras or {}), **(raw.get("extras") or {})}
            existing.updated_at = _now()
        else:
            db.add(Term(
                kb_id=kb_id,
                term_base_id=base_id,
                term_name=name,
                standard_name=str(raw.get("standard_name") or "")[:256],
                english_term=str(raw.get("english_term") or "")[:256],
                definition=str(raw.get("definition") or "")[:2000],
                category=str(raw.get("category") or "")[:128],
                standard_number=str(raw.get("standard_number") or "")[:128],
                synonyms=list(raw.get("synonyms") or [])[:50],
                aliases=list(raw.get("aliases") or [])[:50],
                extras=raw.get("extras") or {},
                status=status,
                created_by=user_id,
            ))
        imported += 1
    await db.flush()
    return imported


_NAME_COLUMN_CANDIDATES = (
    "term_name", "term", "name", "value", "名称", "术语名称", "词汇", "关键词",
)


def _json_safe_value(value: Any) -> Any:
    """外部源行值 → JSONB 可安全存储的类型。"""
    if value is None:
        return ""
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (bytes, bytearray)):
        try:
            return value.decode("utf-8", errors="replace")
        except UnicodeDecodeError:
            return repr(value)
    return value


def _split_list(value: Any) -> list[str]:
    """同义词/别名：数组原样清洗，字符串按 | 、 换行拆分。"""
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [
        part.strip()
        for part in re.split(r"[|、\n]+", str(value or ""))
        if part.strip()
    ]


# column_aliases 特殊键：显式指定术语名称列（字段配置 UI 写入）
NAME_COLUMN_KEY = "__name_column__"


def _map_source_row(row: dict, aliases: dict, columns: list | None = None) -> dict | None:
    """外部源行 → import_terms 词条（对齐原项目 _rows_to_terms）。

    - column_aliases 将原始列名映射到内置字段（term/standard_name/...）；
    - 特殊键 ``__name_column__`` 显式指定术语名称列；
    - 名称列识别：白名单（term_name/term/name/value/名称…）优先，
      未命中时**回退第一列**（columns[0] 或行首列），与列值非空才导入；
    - 所有原始字段保留进 extras（供动态列展示）。
    """
    item: dict = {}
    extras: dict = {}
    name_column = aliases.get(NAME_COLUMN_KEY)
    for key, value in row.items():
        raw_key = str(key)
        safe = _json_safe_value(value)
        extras[raw_key] = safe
        target = str(aliases.get(raw_key, raw_key))
        if raw_key == name_column or target in ("term", "term_name"):
            item["term"] = safe
        elif target in ("standard_name", "english_term", "definition", "category", "standard_number"):
            item[target] = safe
        elif target in ("synonyms", "aliases"):
            item[target] = _split_list(safe)
    if "term" not in item:
        for cand in _NAME_COLUMN_CANDIDATES:
            v = extras.get(cand)
            if v is not None and str(v).strip():
                item["term"] = v
                break
    if "term" not in item:
        # 第一列兜底（对齐原项目：columns[0] → 行首列）
        fallback = None
        if columns and columns[0].get("name"):
            fallback = extras.get(str(columns[0]["name"]))
        if fallback is None or not str(fallback).strip():
            fallback = next(
                (v for v in extras.values() if v is not None and str(v).strip()),
                None,
            )
        if fallback is None:
            return None
        item["term"] = fallback
    if "external_id" not in extras:
        ext_id = row.get("id") or row.get("external_id")
        if ext_id is not None and str(ext_id).strip():
            extras["external_id"] = str(ext_id)
    item["extras"] = extras
    return item


async def sync_term_base(
    db: AsyncSession,
    kb_id: uuid.UUID,
    base_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
    api_client=None,
) -> dict:
    """从外部源拉取并幂等同步词条（外部同步词条默认 pending）。"""
    base = await get_term_base(db, kb_id, base_id)
    if base.source_type not in (SOURCE_TYPE_API, SOURCE_TYPE_DB):
        raise BusinessException(code=ErrorCode.BUSINESS_INVALID_STATE, message="手动术语集不支持同步")
    cfg = base.source_config or {}
    try:
        if base.source_type == SOURCE_TYPE_API:
            result = await source_api.fetch_rows(cfg, limit=_IMPORT_LIMIT, client=api_client)
        else:
            result = await source_db.fetch_rows(cfg, limit=_IMPORT_LIMIT)
    except (ValueError, RuntimeError) as exc:
        raise BusinessException(
            code=ErrorCode.VALIDATION_ERROR, message=str(exc)
        ) from exc
    rows = result["rows"]
    # 列映射：column_aliases 映射内置字段；所有原始字段保留进 extras
    aliases = base.column_aliases or {}
    raw_rows = [row for row in rows if isinstance(row, dict)]
    mapped = [
        m for m in (_map_source_row(row, aliases, base.columns) for row in raw_rows) if m is not None
    ]
    # 对齐原项目：同步为“清空重导”（硬删现有词条后导入新词条）
    now = _now()
    await db.execute(
        delete(Term).where(
            Term.term_base_id == base_id,
            Term.kb_id == kb_id,
        )
    )
    count = await import_terms(db, kb_id, base_id, user_id, mapped, source_type=base.source_type)
    base.last_synced_at = now
    base.sync_status = "success"
    base.sync_last_error = ""
    if base.sync_cron:
        base.sync_next_run_at = _compute_next_run(base.sync_cron)
    await db.commit()
    return {
        "imported": count,
        "total": len(raw_rows),
        "skipped": len(raw_rows) - len(mapped),
    }


async def list_syncable_bases(db: AsyncSession, limit: int) -> list[TermBase]:
    """扫描 sync_enabled 且配置了 cron 的术语集（按 cron 定时同步用）。"""
    rows = (
        await db.execute(
            select(TermBase).where(
                TermBase.sync_enabled.is_(True),
                TermBase.sync_cron != "",
                TermBase.status == "active",
                TermBase.deleted_at.is_(None),
            )
            .order_by(TermBase.created_at.asc())
            .limit(limit)
        )
    ).scalars().all()
    return list(rows)


async def mark_sync_failed(db: AsyncSession, kb_id: uuid.UUID, base_id: uuid.UUID, error: str) -> None:
    """定时同步失败回写状态（失败不自动重试，等下次 cron）。"""
    base = await get_term_base(db, kb_id, base_id)
    base.sync_status = "failed"
    base.sync_last_error = (error or "")[:500]
    await db.commit()
