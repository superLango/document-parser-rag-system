"""Schema 配置端点模块。

提供抽取 Schema 的 CRUD 接口：
- GET /schemas/：分页查询 Schema 列表
- GET /schemas/{schema_id}：获取 Schema 详情
- POST /schemas/：创建 Schema
- PUT /schemas/{schema_id}：更新 Schema
- DELETE /schemas/{schema_id}：删除 Schema
- PATCH /schemas/{schema_id}/active：启用/停用
"""

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, get_pagination_params
from app.core.database import get_db
from app.core.exceptions import BusinessException, ErrorCode
from app.core.response import paginated, success
from app.models.schema_model import SchemaConfig
from app.models.user import User

router = APIRouter(prefix="/schemas", tags=["Schema 管理"])


class SchemaCreateRequest(BaseModel):
    """Schema 创建请求体。"""

    name: str
    description: str = ""
    doc_type: str = ""
    fields: list[dict] = []


class SchemaUpdateRequest(BaseModel):
    """Schema 更新请求体。"""

    name: str | None = None
    description: str | None = None
    doc_type: str | None = None
    fields: list[dict] | None = None


@router.get("/")
async def list_schemas(
    pagination: dict = Depends(get_pagination_params),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """分页查询 Schema 列表。"""
    page = pagination["page"]
    page_size = pagination["page_size"]

    total_result = await db.execute(select(func.count()).select_from(SchemaConfig))
    total = total_result.scalar_one()

    offset = (page - 1) * page_size
    list_stmt = (
        select(SchemaConfig)
        .order_by(SchemaConfig.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    result = await db.execute(list_stmt)
    schemas = result.scalars().all()

    items = [
        {
            "id": str(s.id),
            "name": s.name,
            "description": s.description or "",
            "doc_type": "",
            "fields": s.schema_definition or [],
            "is_active": not s.is_template,
            "created_at": s.created_at.isoformat() if s.created_at else "",
            "updated_at": s.updated_at.isoformat() if s.updated_at else "",
        }
        for s in schemas
    ]
    return paginated(items, total, page, page_size)


@router.get("/{schema_id}")
async def get_schema(
    schema_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """获取 Schema 详情。"""
    stmt = select(SchemaConfig).where(SchemaConfig.id == schema_id)
    result = await db.execute(stmt)
    schema = result.scalar_one_or_none()

    if schema is None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_DOCUMENT_NOT_FOUND,
            message=f"Schema {schema_id} 不存在",
        )

    return success(data={
        "id": str(schema.id),
        "name": schema.name,
        "description": schema.description or "",
        "doc_type": "",
        "fields": schema.schema_definition or [],
        "is_active": not schema.is_template,
        "created_at": schema.created_at.isoformat() if schema.created_at else "",
        "updated_at": schema.updated_at.isoformat() if schema.updated_at else "",
    })


@router.post("/")
async def create_schema(
    body: SchemaCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """创建 Schema。"""
    schema = SchemaConfig(
        name=body.name,
        description=body.description,
        schema_definition=body.fields,
        is_template=False,
    )
    db.add(schema)
    await db.commit()
    await db.refresh(schema)

    return success(data={
        "id": str(schema.id),
        "name": schema.name,
        "description": schema.description or "",
        "doc_type": body.doc_type,
        "fields": schema.schema_definition or [],
        "is_active": True,
        "created_at": schema.created_at.isoformat() if schema.created_at else "",
        "updated_at": "",
    })


@router.put("/{schema_id}")
async def update_schema(
    schema_id: UUID,
    body: SchemaUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """更新 Schema。"""
    stmt = select(SchemaConfig).where(SchemaConfig.id == schema_id)
    result = await db.execute(stmt)
    schema = result.scalar_one_or_none()

    if schema is None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_DOCUMENT_NOT_FOUND,
            message=f"Schema {schema_id} 不存在",
        )

    if body.name is not None:
        schema.name = body.name
    if body.description is not None:
        schema.description = body.description
    if body.fields is not None:
        schema.schema_definition = body.fields

    await db.commit()
    await db.refresh(schema)

    return success(data={
        "id": str(schema.id),
        "name": schema.name,
        "description": schema.description or "",
        "doc_type": body.doc_type or "",
        "fields": schema.schema_definition or [],
        "is_active": not schema.is_template,
        "created_at": schema.created_at.isoformat() if schema.created_at else "",
        "updated_at": schema.updated_at.isoformat() if schema.updated_at else "",
    })


@router.delete("/{schema_id}")
async def delete_schema(
    schema_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """删除 Schema。"""
    stmt = select(SchemaConfig).where(SchemaConfig.id == schema_id)
    result = await db.execute(stmt)
    schema = result.scalar_one_or_none()

    if schema is None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_DOCUMENT_NOT_FOUND,
            message=f"Schema {schema_id} 不存在",
        )

    await db.delete(schema)
    await db.commit()
    return success(message="删除成功")


@router.patch("/{schema_id}/active")
async def toggle_active(
    schema_id: UUID,
    body: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """启用/停用 Schema。"""
    stmt = select(SchemaConfig).where(SchemaConfig.id == schema_id)
    result = await db.execute(stmt)
    schema = result.scalar_one_or_none()

    if schema is None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_DOCUMENT_NOT_FOUND,
            message=f"Schema {schema_id} 不存在",
        )

    is_active = body.get("is_active", True)
    schema.is_template = not is_active
    await db.commit()

    return success(data={
        "id": str(schema.id),
        "name": schema.name,
        "is_active": is_active,
    })
