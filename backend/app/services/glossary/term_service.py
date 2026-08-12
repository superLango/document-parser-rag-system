"""术语条目服务（S8/S3）：CRUD、批量导入、审核、导出、分类。"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime, timezone

from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import BusinessException, ErrorCode
from app.core.logging import get_logger
from app.models.glossary import (
    SOURCE_TYPE_MANUAL,
    TERM_STATUS_ACTIVE,
    TERM_STATUS_REJECTED,
    Term,
    TermBase,
)

from .term_base_service import get_term_base, import_terms

logger = get_logger(__name__)

_IMPORT_LIMIT = settings.TERM_SYNC_IMPORT_LIMIT


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _serialize_term(t: Term, base_name: str = "") -> dict:
    """术语序列化。"""
    return {
        "id": str(t.id),
        "term_base_id": str(t.term_base_id),
        "term_base_name": base_name,
        "term_name": t.term_name,
        "standard_name": t.standard_name,
        "english_term": t.english_term,
        "definition": t.definition,
        "category": t.category,
        "standard_number": t.standard_number,
        "synonyms": t.synonyms or [],
        "aliases": t.aliases or [],
        "extras": t.extras or {},
        "status": t.status,
        "reviewed_by": str(t.reviewed_by) if t.reviewed_by else None,
        "reviewed_at": t.reviewed_at.isoformat() if t.reviewed_at else None,
        "created_at": t.created_at.isoformat(),
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
    }


_NAME_SEARCH_FIELDS = frozenset({
    "term", "term_name", "name", "value", "名称", "术语名称", "词汇", "关键词",
})

_MANUAL_SEARCH_FIELDS: dict[str, object] = {
    "term": Term.term_name,
    "term_name": Term.term_name,
    "name": Term.term_name,
    "standard_name": Term.standard_name,
    "english_term": Term.english_term,
    "definition": Term.definition,
    "category": Term.category,
    "standard_number": Term.standard_number,
    "aliases": cast(Term.aliases, String),
    "synonyms": cast(Term.synonyms, String),
}


async def list_terms(
    db: AsyncSession,
    kb_id: uuid.UUID,
    page: int,
    page_size: int,
    term_base_id: uuid.UUID | None = None,
    category: str | None = None,
    status: str | None = None,
    keyword: str | None = None,
    search_field: str | None = None,
) -> tuple[list[dict], int]:
    """分页查询术语（支持过滤与字段级搜索）。"""
    base = select(Term).where(Term.kb_id == kb_id, Term.deleted_at.is_(None))
    count_base = (
        select(func.count())
        .select_from(Term)
        .where(Term.kb_id == kb_id, Term.deleted_at.is_(None))
    )
    base_info = None
    if term_base_id is not None:
        base = base.where(Term.term_base_id == term_base_id)
        count_base = count_base.where(Term.term_base_id == term_base_id)
        base_info = (
            await db.execute(
                select(TermBase.source_type, TermBase.columns).where(
                    TermBase.id == term_base_id,
                    TermBase.deleted_at.is_(None),
                )
            )
        ).first()
    if category:
        base = base.where(Term.category == category)
        count_base = count_base.where(Term.category == category)
    if status:
        base = base.where(Term.status == status)
        count_base = count_base.where(Term.status == status)
    if keyword:
        like = f"%{keyword}%"

        def _extras_ilike(field: str):
            return func.coalesce(
                cast(Term.extras.op('->>')(field), String), ''
            ).ilike(like)

        is_manual = base_info is None or base_info[0] == SOURCE_TYPE_MANUAL
        if search_field:
            if is_manual:
                col = _MANUAL_SEARCH_FIELDS.get(search_field)
                if col is not None:
                    cond = col.ilike(like)
                else:
                    cond = _extras_ilike(search_field)
            elif search_field in _NAME_SEARCH_FIELDS:
                cond = Term.term_name.ilike(like)
            else:
                cond = _extras_ilike(search_field)
        else:
            if is_manual:
                cond = or_(
                    Term.term_name.ilike(like),
                    Term.standard_name.ilike(like),
                    Term.english_term.ilike(like),
                    Term.definition.ilike(like),
                    Term.category.ilike(like),
                    cast(Term.aliases, String).ilike(like),
                    cast(Term.synonyms, String).ilike(like),
                )
            else:
                cond = Term.term_name.ilike(like)
                for col in (base_info[1] or []):
                    name = col.get("name")
                    if name:
                        cond = cond | _extras_ilike(str(name))
        base = base.where(cond)
        count_base = count_base.where(cond)
    total = (await db.execute(count_base)).scalar_one()
    rows = (
        await db.execute(
            base.order_by(Term.created_at.desc())
            .offset((page - 1) * page_size).limit(page_size)
        )
    ).scalars().all()
    base_names = {}
    if rows:
        base_ids = {r.term_base_id for r in rows}
        names = (
            await db.execute(
                select(TermBase.id, TermBase.name).where(TermBase.id.in_(base_ids))
            )
        ).all()
        base_names = {str(bid): name for bid, name in names}
    items = [_serialize_term(r, base_names.get(str(r.term_base_id), "")) for r in rows]
    return items, total


async def list_categories(
    db: AsyncSession, kb_id: uuid.UUID, term_base_id: uuid.UUID | None = None
) -> list[str]:
    """分类列表（去重排序）。"""
    base = select(Term.category).where(
        Term.kb_id == kb_id, Term.deleted_at.is_(None), Term.category != ""
    )
    if term_base_id is not None:
        base = base.where(Term.term_base_id == term_base_id)
    rows = (await db.execute(base.distinct().order_by(Term.category))).scalars().all()
    return list(rows)


async def get_term(db: AsyncSession, kb_id: uuid.UUID, term_id: uuid.UUID) -> Term:
    term = (
        await db.execute(
            select(Term).where(
                Term.id == term_id,
                Term.kb_id == kb_id,
                Term.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if term is None:
        raise BusinessException(code=ErrorCode.BUSINESS_NOT_FOUND, message="术语不存在")
    return term


async def get_term_detail(
    db: AsyncSession, kb_id: uuid.UUID, term_id: uuid.UUID
) -> dict:
    term = await get_term(db, kb_id, term_id)
    base_name = (
        await db.execute(select(TermBase.name).where(TermBase.id == term.term_base_id))
    ).scalar_one_or_none()
    return _serialize_term(term, base_name or "")


async def _ensure_term_unique(
    db: AsyncSession, kb_id: uuid.UUID, base_id: uuid.UUID, name: str, exclude_id: uuid.UUID | None = None
) -> None:
    stmt = select(Term.id).where(
        Term.kb_id == kb_id,
        Term.term_base_id == base_id,
        Term.term_name == name,
        Term.deleted_at.is_(None),
    )
    if exclude_id is not None:
        stmt = stmt.where(Term.id != exclude_id)
    exists = (await db.execute(stmt)).scalar_one_or_none()
    if exists is not None:
        raise BusinessException(code=ErrorCode.BUSINESS_CONFLICT, message="同术语集内术语名称已存在", http_status=409)


async def create_term(
    db: AsyncSession,
    kb_id: uuid.UUID,
    user_id: uuid.UUID | None,
    data: dict,
) -> dict:
    """创建术语（手动，默认 active）。"""
    name = str(data.get("term") or data.get("term_name") or "").strip()
    if not name:
        raise BusinessException(code=ErrorCode.VALIDATION_ERROR, message="术语名称不能为空")
    if len(name) > 256:
        raise BusinessException(code=ErrorCode.VALIDATION_ERROR, message="术语名称过长")
    base_id = data.get("term_base_id")
    if not base_id:
        raise BusinessException(code=ErrorCode.VALIDATION_ERROR, message="必须指定术语集")
    await get_term_base(db, kb_id, uuid.UUID(str(base_id)))
    await _ensure_term_unique(db, kb_id, uuid.UUID(str(base_id)), name)
    term = Term(
        kb_id=kb_id,
        term_base_id=uuid.UUID(str(base_id)),
        term_name=name[:256],
        standard_name=str(data.get("standard_name") or "")[:256],
        english_term=str(data.get("english_term") or "")[:256],
        definition=str(data.get("definition") or "")[:2000],
        category=str(data.get("category") or "")[:128],
        standard_number=str(data.get("standard_number") or "")[:128],
        synonyms=list(data.get("synonyms") or [])[:50],
        aliases=list(data.get("aliases") or [])[:50],
        extras=data.get("extras") or {},
        status=TERM_STATUS_ACTIVE,
        created_by=user_id,
    )
    db.add(term)
    await db.commit()
    return _serialize_term(term)


async def update_term(
    db: AsyncSession, kb_id: uuid.UUID, term_id: uuid.UUID, data: dict
) -> dict:
    term = await get_term(db, kb_id, term_id)
    if "term" in data or "term_name" in data:
        name = str(data.get("term") or data.get("term_name") or "").strip()
        if not name:
            raise BusinessException(code=ErrorCode.VALIDATION_ERROR, message="术语名称不能为空")
        if name != term.term_name:
            await _ensure_term_unique(db, kb_id, term.term_base_id, name, exclude_id=term.id)
        term.term_name = name[:256]
    if "standard_name" in data:
        term.standard_name = str(data.get("standard_name") or "")[:256]
    if "english_term" in data:
        term.english_term = str(data.get("english_term") or "")[:256]
    if "definition" in data:
        term.definition = str(data.get("definition") or "")[:2000]
    if "category" in data:
        term.category = str(data.get("category") or "")[:128]
    if "standard_number" in data:
        term.standard_number = str(data.get("standard_number") or "")[:128]
    if "synonyms" in data:
        term.synonyms = list(data.get("synonyms") or [])[:50]
    if "aliases" in data:
        term.aliases = list(data.get("aliases") or [])[:50]
    if "extras" in data:
        term.extras = {**(term.extras or {}), **(data.get("extras") or {})}
    await db.commit()
    return _serialize_term(term)


async def review_term(
    db: AsyncSession, kb_id: uuid.UUID, term_id: uuid.UUID, action: str, reviewer_id: uuid.UUID
) -> dict:
    """审核术语：approve → active；reject → rejected。"""
    term = await get_term(db, kb_id, term_id)
    if action == "approve":
        term.status = TERM_STATUS_ACTIVE
    elif action == "reject":
        term.status = TERM_STATUS_REJECTED
    else:
        raise BusinessException(code=ErrorCode.VALIDATION_ERROR, message="无效的审核动作")
    term.reviewed_by = reviewer_id
    term.reviewed_at = _now()
    await db.commit()
    return _serialize_term(term)


async def delete_term(
    db: AsyncSession, kb_id: uuid.UUID, term_id: uuid.UUID
) -> None:
    term = await get_term(db, kb_id, term_id)
    await db.delete(term)
    await db.commit()


async def batch_import_terms(
    db: AsyncSession,
    kb_id: uuid.UUID,
    base_id: uuid.UUID,
    user_id: uuid.UUID | None,
    items: list[dict],
) -> dict:
    """批量导入（≤5000，幂等 upsert，手动 active）。"""
    await get_term_base(db, kb_id, base_id)
    count = await import_terms(db, kb_id, base_id, user_id, items, source_type="manual")
    await db.commit()
    return {"imported": count, "total": len(items)}


async def export_terms(
    db: AsyncSession, kb_id: uuid.UUID
) -> bytes:
    """导出当前 KB 全部未删除术语为 CSV（UTF-8 BOM，Excel 友好）。"""
    rows = (
        await db.execute(
            select(Term).where(
                Term.kb_id == kb_id,
                Term.deleted_at.is_(None),
            ).order_by(Term.created_at.asc())
        )
    ).scalars().all()
    base_names = {}
    if rows:
        base_ids = {r.term_base_id for r in rows}
        names = (
            await db.execute(
                select(TermBase.id, TermBase.name).where(TermBase.id.in_(base_ids))
            )
        ).all()
        base_names = {str(bid): name for bid, name in names}
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "术语", "标准名", "英文", "定义", "分类", "标准号",
        "同义词", "别名", "状态", "术语集",
    ])
    for t in rows:
        writer.writerow([
            t.term_name, t.standard_name, t.english_term, t.definition,
            t.category, t.standard_number,
            "|".join(t.synonyms or []), "|".join(t.aliases or []),
            t.status, base_names.get(str(t.term_base_id), ""),
        ])
    return ("\ufeff" + buf.getvalue()).encode("utf-8")


async def batch_save_terms(
    db: AsyncSession,
    kb_id: uuid.UUID,
    base_id: uuid.UUID,
    user_id: uuid.UUID | None,
    items: list[dict],
    deleted_ids: list[str],
) -> dict:
    """术语集内批量保存（对齐原项目 batch save）：新增/更新/删除一次提交。

    仅 manual 术语集允许；删除为硬删。
    """
    base = await get_term_base(db, kb_id, base_id)
    if base.source_type != SOURCE_TYPE_MANUAL:
        raise BusinessException(
            code=ErrorCode.BUSINESS_INVALID_STATE,
            message="外部数据源术语集为只读，请通过同步或修改数据源维护",
        )
    if len(items) + len(deleted_ids) > _IMPORT_LIMIT:
        raise BusinessException(
            code=ErrorCode.VALIDATION_ERROR,
            message=f"单次批量保存不能超过 {_IMPORT_LIMIT} 条",
        )
    now = _now()

    deleted = 0
    for del_id in deleted_ids:
        try:
            del_uuid = uuid.UUID(str(del_id))
        except ValueError:
            continue
        term = (
            await db.execute(
                select(Term).where(
                    Term.id == del_uuid,
                    Term.kb_id == kb_id,
                    Term.term_base_id == base_id,
                    Term.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if term is not None:
            await db.delete(term)
            deleted += 1

    created = 0
    updated = 0
    for item in items:
        name = str(item.get("term") or "").strip()
        if not name:
            continue
        name = name[:256]
        term_id = item.get("id")
        if term_id:
            try:
                term_uuid = uuid.UUID(str(term_id))
            except ValueError:
                continue
            term = (
                await db.execute(
                    select(Term).where(
                        Term.id == term_uuid,
                        Term.kb_id == kb_id,
                        Term.term_base_id == base_id,
                        Term.deleted_at.is_(None),
                    )
                )
            ).scalar_one_or_none()
            if term is None:
                continue
            if name != term.term_name:
                await _ensure_term_unique(db, kb_id, base_id, name, exclude_id=term.id)
            term.term_name = name
            term.standard_name = str(item.get("standard_name") or "")[:256]
            term.english_term = str(item.get("english_term") or "")[:256]
            term.definition = str(item.get("definition") or "")[:2000]
            term.category = str(item.get("category") or "")[:128]
            term.standard_number = str(item.get("standard_number") or "")[:128]
            term.synonyms = list(item.get("synonyms") or [])[:50]
            term.aliases = list(item.get("aliases") or [])[:50]
            term.extras = {**(term.extras or {}), **(item.get("extras") or {})}
            term.updated_at = now
            updated += 1
        else:
            await _ensure_term_unique(db, kb_id, base_id, name)
            db.add(Term(
                kb_id=kb_id,
                term_base_id=base_id,
                term_name=name,
                standard_name=str(item.get("standard_name") or "")[:256],
                english_term=str(item.get("english_term") or "")[:256],
                definition=str(item.get("definition") or "")[:2000],
                category=str(item.get("category") or "")[:128],
                standard_number=str(item.get("standard_number") or "")[:128],
                synonyms=list(item.get("synonyms") or [])[:50],
                aliases=list(item.get("aliases") or [])[:50],
                extras=item.get("extras") or {},
                status=TERM_STATUS_ACTIVE,
                created_by=user_id,
            ))
            created += 1
    await db.commit()
    return {"created": created, "updated": updated, "deleted": deleted}
