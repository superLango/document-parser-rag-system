"""术语库端点模块。

提供术语管理的 CRUD 接口：
- GET /terms/：分页查询术语列表
- GET /terms/{term_id}：获取术语详情
- POST /terms/：创建术语
- PUT /terms/{term_id}：更新术语
- DELETE /terms/{term_id}：删除术语
- POST /terms/batch：批量导入
- GET /terms/categories：获取分类列表
"""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, get_pagination_params
from app.core.database import get_db
from app.core.exceptions import BusinessException, ErrorCode
from app.core.response import paginated, success
from app.models.term import Term
from app.models.user import User

router = APIRouter(prefix="/terms", tags=["术语库"])


class TermCreateRequest(BaseModel):
    """术语创建请求体。"""

    term: str
    english_term: str = ""
    definition: str = ""
    category: str = ""
    standard_number: str = ""
    synonyms: list[str] = []


class TermUpdateRequest(BaseModel):
    """术语更新请求体。"""

    term: str | None = None
    english_term: str | None = None
    definition: str | None = None
    category: str | None = None
    standard_number: str | None = None
    synonyms: list[str] | None = None


class TermReviewRequest(BaseModel):
    """术语审核请求体。"""

    action: Literal["approve", "reject"]


def _serialize_term(t: Term) -> dict:
    """将 Term ORM 对象序列化为前端期望的字典格式。"""
    return {
        "id": str(t.id),
        "term": t.term_name,
        "english_term": t.standard_name or "",
        "definition": t.definition or "",
        "category": "",
        "standard_number": "",
        "synonyms": t.synonyms or [],
        "created_at": t.created_at.isoformat() if t.created_at else "",
    }


@router.get("/")
async def list_terms(
    status: str | None = Query(None, description="按状态过滤：active/pending/deprecated"),
    pagination: dict = Depends(get_pagination_params),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """分页查询术语列表。"""
    page = pagination["page"]
    page_size = pagination["page_size"]

    count_stmt = select(func.count()).select_from(Term)
    list_stmt = select(Term).order_by(Term.created_at.desc())

    if status:
        count_stmt = count_stmt.where(Term.status == status)
        list_stmt = list_stmt.where(Term.status == status)

    total_result = await db.execute(count_stmt)
    total = total_result.scalar_one()

    offset = (page - 1) * page_size
    list_stmt = list_stmt.offset(offset).limit(page_size)
    result = await db.execute(list_stmt)
    terms = result.scalars().all()

    items = [_serialize_term(t) for t in terms]
    return paginated(items, total, page, page_size)


@router.get("/categories")
async def get_categories(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """获取术语分类列表。"""
    return success(data=[])


@router.get("/{term_id}")
async def get_term(
    term_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """获取术语详情。"""
    stmt = select(Term).where(Term.id == term_id)
    result = await db.execute(stmt)
    term = result.scalar_one_or_none()

    if term is None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_DOCUMENT_NOT_FOUND,
            message=f"术语 {term_id} 不存在",
        )

    return success(data=_serialize_term(term))


@router.post("/")
async def create_term(
    body: TermCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """创建术语。"""
    term = Term(
        term_name=body.term,
        standard_name=body.english_term or None,
        definition=body.definition or None,
        synonyms=body.synonyms or None,
        status="active",
    )
    db.add(term)
    await db.commit()
    await db.refresh(term)

    return success(data=_serialize_term(term))


@router.post("/batch")
async def batch_import(
    body: list[TermCreateRequest],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """批量导入术语。"""
    count = 0
    for item in body:
        term = Term(
            term_name=item.term,
            standard_name=item.english_term or None,
            definition=item.definition or None,
            synonyms=item.synonyms or None,
            status="active",
        )
        db.add(term)
        count += 1

    await db.commit()
    return success(data={"imported": count})


@router.put("/{term_id}")
async def update_term(
    term_id: UUID,
    body: TermUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """更新术语。"""
    stmt = select(Term).where(Term.id == term_id)
    result = await db.execute(stmt)
    term = result.scalar_one_or_none()

    if term is None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_DOCUMENT_NOT_FOUND,
            message=f"术语 {term_id} 不存在",
        )

    if body.term is not None:
        term.term_name = body.term
    if body.english_term is not None:
        term.standard_name = body.english_term or None
    if body.definition is not None:
        term.definition = body.definition or None
    if body.synonyms is not None:
        term.synonyms = body.synonyms

    await db.commit()
    await db.refresh(term)

    return success(data=_serialize_term(term))


@router.delete("/{term_id}")
async def delete_term(
    term_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """删除术语。"""
    stmt = select(Term).where(Term.id == term_id)
    result = await db.execute(stmt)
    term = result.scalar_one_or_none()

    if term is None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_DOCUMENT_NOT_FOUND,
            message=f"术语 {term_id} 不存在",
        )

    await db.delete(term)
    await db.commit()
    return success(message="删除成功")


@router.put("/{term_id}/review")
async def review_term(
    term_id: UUID,
    payload: TermReviewRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """审核术语（通过/拒绝）。

    - approve：将术语状态置为 active
    - reject：将术语状态置为 deprecated
    """
    stmt = select(Term).where(Term.id == term_id)
    result = await db.execute(stmt)
    term = result.scalar_one_or_none()

    if term is None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_DOCUMENT_NOT_FOUND,
            message=f"术语 {term_id} 不存在",
        )

    if payload.action == "approve":
        term.status = "active"
    else:
        term.status = "deprecated"

    await db.commit()
    await db.refresh(term)

    return success(data=_serialize_term(term))
