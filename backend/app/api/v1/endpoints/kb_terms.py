"""知识库内术语库管理端点（阶段 1.3）。

提供 KB 隔离的术语 CRUD 与审核接口，所有端点强制
``Depends(get_kb_context)`` 实现知识库隔离与 RBAC 权限校验。
Term 表已含 kb_id 并启用 RLS，查询自动按当前 KB 过滤。

端点（前缀 ``/kbs/{kb_id}/terms``）：
- GET    /                 分页查询术语列表（任意成员，支持 category/status/keyword 过滤）
- GET    /categories       分类列表（任意成员）
- GET    /{term_id}        术语详情（任意成员）
- POST   /                 创建术语（editor+）
- POST   /batch            批量导入（editor+）
- PUT    /{term_id}        更新术语（editor+）
- PUT    /{term_id}/review 审核术语（editor+）
- DELETE /{term_id}        删除术语（editor+）
- GET    /export           导出当前 KB 全部术语（任意成员）

与旧 ``terms.py``（全局，向后兼容）共存。
"""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import KBContext, get_kb_context, get_pagination_params, require_role
from app.core.database import get_db
from app.core.exceptions import BusinessException, ErrorCode
from app.core.response import paginated, success
from app.models.knowledge_base import EDIT_ROLES
from app.models.term import Term

router = APIRouter(prefix="/kbs/{kb_id}/terms", tags=["知识库-术语库"])


# ============================================================
# 请求体定义
# ============================================================
class TermCreateRequest(BaseModel):
    """术语创建请求体。"""

    term: str
    english_term: str = ""
    definition: str = ""
    category: str = ""
    standard_number: str = ""
    synonyms: list[str] = []
    aliases: list[str] = []


class TermUpdateRequest(BaseModel):
    """术语更新请求体。所有字段可选。"""

    term: str | None = None
    english_term: str | None = None
    definition: str | None = None
    category: str | None = None
    standard_number: str | None = None
    synonyms: list[str] | None = None
    aliases: list[str] | None = None
    term_base_id: str | None = None


class TermReviewRequest(BaseModel):
    """术语审核请求体。"""

    action: Literal["approve", "reject"]


# ============================================================
# 工具函数
# ============================================================
def _serialize(t: Term, reviewer_name: str | None = None) -> dict:
    """序列化 Term ORM 对象为响应字典。"""
    return {
        "id": str(t.id),
        "term": t.term_name,
        "english_term": t.standard_name or "",
        "definition": t.definition or "",
        "category": t.category or "",
        "standard_number": t.standard_number or "",
        "synonyms": t.synonyms or [],
        "aliases": t.aliases or [],
        "term_base_id": str(t.term_base_id) if t.term_base_id else None,
        "status": t.status,
        "reviewed_by": str(t.reviewed_by) if t.reviewed_by else None,
        "reviewed_by_name": reviewer_name,
        "reviewed_at": t.reviewed_at.isoformat() if t.reviewed_at else None,
        "created_at": t.created_at.isoformat() if t.created_at else "",
        "updated_at": t.updated_at.isoformat() if t.updated_at else "",
    }


# ============================================================
# 分类与导出端点（路径优先，避免与 /{term_id} 冲突）
# ============================================================
@router.get("/categories")
async def list_categories(
    kb_ctx: KBContext = Depends(get_kb_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取 KB 内术语分类列表（去重，显式按 kb_id 过滤，纵深防御不依赖 RLS）。"""
    # 显式按 kb_id 过滤，纵深防御不依赖 RLS（superuser 绕过 RLS）
    rows = await db.execute(
        select(distinct(Term.category))
        .where(
            Term.kb_id == kb_ctx.kb_id,
            Term.category.isnot(None),
            Term.category != "",
        )
        .order_by(Term.category)
    )
    categories = [r[0] for r in rows.all() if r[0]]
    return success(data=categories)


@router.get("/export")
async def export_terms(
    kb_ctx: KBContext = Depends(get_kb_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """导出当前 KB 全部术语为 JSON 列表（显式按 kb_id 过滤，纵深防御不依赖 RLS）。"""
    # 显式按 kb_id 过滤，纵深防御不依赖 RLS（superuser 绕过 RLS）
    terms = (
        await db.execute(
            select(Term)
            .where(Term.kb_id == kb_ctx.kb_id)
            .order_by(Term.category, Term.term_name)
        )
    ).scalars().all()
    return success(data={"items": [_serialize(t) for t in terms], "total": len(terms)})


# ============================================================
# 标准 CRUD
# ============================================================
@router.get("")
async def list_terms(
    kb_ctx: KBContext = Depends(get_kb_context),
    pagination: dict = Depends(get_pagination_params),
    db: AsyncSession = Depends(get_db),
    status: str | None = Query(None, description="按状态过滤：active/pending/deprecated"),
    category: str | None = Query(None, description="按分类过滤"),
    keyword: str | None = Query(None, description="按术语名/英文/同义词模糊搜索"),
) -> dict:
    """分页查询 KB 内术语列表（显式按 kb_id 过滤，纵深防御不依赖 RLS）。"""
    page = pagination["page"]
    page_size = pagination["page_size"]

    # 显式按 kb_id 过滤，纵深防御不依赖 RLS（superuser 绕过 RLS）
    base = select(Term).where(Term.kb_id == kb_ctx.kb_id)
    count_base = (
        select(func.count()).select_from(Term).where(Term.kb_id == kb_ctx.kb_id)
    )

    if status:
        base = base.where(Term.status == status)
        count_base = count_base.where(Term.status == status)
    if category:
        base = base.where(Term.category == category)
        count_base = count_base.where(Term.category == category)
    if keyword:
        like = f"%{keyword}%"
        cond = (
            Term.term_name.ilike(like)
            | Term.standard_name.ilike(like)
            | Term.definition.ilike(like)
        )
        base = base.where(cond)
        count_base = count_base.where(cond)

    total = (await db.execute(count_base)).scalar_one()
    terms = (
        await db.execute(
            base.order_by(Term.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()
    return paginated([_serialize(t) for t in terms], total, page, page_size)


@router.get("/{term_id}")
async def get_term(
    term_id: UUID,
    kb_ctx: KBContext = Depends(get_kb_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取术语详情（显式按 kb_id 过滤，纵深防御不依赖 RLS）。"""
    # 显式按 kb_id 过滤，纵深防御不依赖 RLS（superuser 绕过 RLS）
    term = (
        await db.execute(
            select(Term).where(
                Term.id == term_id,
                Term.kb_id == kb_ctx.kb_id,
            )
        )
    ).scalar_one_or_none()
    if term is None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_TERM_NOT_FOUND,
            message=f"术语 {term_id} 不存在",
        )
    return success(data=_serialize(term))


@router.post("")
async def create_term(
    body: TermCreateRequest,
    kb_ctx: KBContext = Depends(require_role(*EDIT_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """创建术语（editor+）。"""
    term_base_uuid = None
    if body.term_base_id:
        try:
            term_base_uuid = UUID(body.term_base_id)
        except ValueError:
            term_base_uuid = None
    term = Term(
        kb_id=kb_ctx.kb_id,
        term_base_id=term_base_uuid,
        term_name=body.term,
        standard_name=body.english_term or None,
        definition=body.definition or None,
        synonyms=body.synonyms or None,
        aliases=body.aliases or None,
        status="active",
        category=body.category or None,
        standard_number=body.standard_number or None,
        reviewed_by=kb_ctx.user.id,
    )
    from datetime import datetime, timezone

    term.reviewed_at = datetime.now(timezone.utc)
    db.add(term)
    await db.commit()
    await db.refresh(term)
    return success(data=_serialize(term))


@router.post("/batch")
async def batch_import(
    body: list[TermCreateRequest],
    kb_ctx: KBContext = Depends(require_role(*EDIT_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """批量导入术语（editor+）。"""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    count = 0
    for item in body:
        term = Term(
            kb_id=kb_ctx.kb_id,
            term_name=item.term,
            standard_name=item.english_term or None,
            definition=item.definition or None,
            synonyms=item.synonyms or None,
            aliases=item.aliases or None,
            status="active",
            category=item.category or None,
            standard_number=item.standard_number or None,
            reviewed_by=kb_ctx.user.id,
            reviewed_at=now,
        )
        db.add(term)
        count += 1
    await db.commit()
    return success(data={"imported": count})


@router.put("/{term_id}")
async def update_term(
    term_id: UUID,
    body: TermUpdateRequest,
    kb_ctx: KBContext = Depends(require_role(*EDIT_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """更新术语（editor+）。所有字段可选。"""
    # 显式按 kb_id 过滤，纵深防御不依赖 RLS（superuser 绕过 RLS）
    term = (
        await db.execute(
            select(Term).where(
                Term.id == term_id,
                Term.kb_id == kb_ctx.kb_id,
            )
        )
    ).scalar_one_or_none()
    if term is None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_TERM_NOT_FOUND,
            message=f"术语 {term_id} 不存在",
        )
    if body.term is not None:
        term.term_name = body.term
    if body.english_term is not None:
        term.standard_name = body.english_term or None
    if body.definition is not None:
        term.definition = body.definition or None
    if body.category is not None:
        term.category = body.category or None
    if body.standard_number is not None:
        term.standard_number = body.standard_number or None
    if body.synonyms is not None:
        term.synonyms = body.synonyms
    if body.aliases is not None:
        term.aliases = body.aliases
    if body.term_base_id is not None:
        try:
            term.term_base_id = UUID(body.term_base_id) if body.term_base_id else None
        except ValueError:
            pass
    await db.commit()
    await db.refresh(term)
    return success(data=_serialize(term))


@router.put("/{term_id}/review")
async def review_term(
    term_id: UUID,
    payload: TermReviewRequest,
    kb_ctx: KBContext = Depends(require_role(*EDIT_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """审核术语（editor+）。approve→active，reject→deprecated。"""
    # 显式按 kb_id 过滤，纵深防御不依赖 RLS（superuser 绕过 RLS）
    term = (
        await db.execute(
            select(Term).where(
                Term.id == term_id,
                Term.kb_id == kb_ctx.kb_id,
            )
        )
    ).scalar_one_or_none()
    if term is None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_TERM_NOT_FOUND,
            message=f"术语 {term_id} 不存在",
        )
    from datetime import datetime, timezone

    term.status = "active" if payload.action == "approve" else "deprecated"
    term.reviewed_by = kb_ctx.user.id
    term.reviewed_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(term)
    return success(data=_serialize(term))


@router.delete("/{term_id}")
async def delete_term(
    term_id: UUID,
    kb_ctx: KBContext = Depends(require_role(*EDIT_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """删除术语（editor+）。"""
    # 显式按 kb_id 过滤，纵深防御不依赖 RLS（superuser 绕过 RLS）
    term = (
        await db.execute(
            select(Term).where(
                Term.id == term_id,
                Term.kb_id == kb_ctx.kb_id,
            )
        )
    ).scalar_one_or_none()
    if term is None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_TERM_NOT_FOUND,
            message=f"术语 {term_id} 不存在",
        )
    await db.delete(term)
    await db.commit()
    return success(message="删除成功")
