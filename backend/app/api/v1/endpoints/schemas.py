"""Schema 配置端点模块。

提供抽取 Schema 的 CRUD 接口，支持父子层级结构：

- GET /schemas/：分页查询所有 Schema（兼容旧接口）
- GET /schemas/categories：查询所有父分类（含子 Schema 数量统计）
- GET /schemas/{parent_id}/children：查询父分类下的所有子 Schema
- GET /schemas/{parent_id}/merged：合并父分类下所有子 Schema 为整体 Schema
- GET /schemas/{schema_id}：获取 Schema 详情
- POST /schemas/：创建 Schema（父分类或子 Schema）
- PUT /schemas/{schema_id}：更新 Schema
- DELETE /schemas/{schema_id}：删除 Schema（父分类会级联删除子 Schema）
- PATCH /schemas/{schema_id}/active：启用/停用 Schema（直接修改 is_active 字段）
"""

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, get_pagination_params
from app.core.database import get_db
from app.core.exceptions import BusinessException, ErrorCode
from app.core.response import paginated, success
from app.models.schema_model import SchemaConfig
from app.models.user import User

router = APIRouter(prefix="/schemas", tags=["Schema 管理"])


# ---------------------------------------------------------------
# 请求体定义
# ---------------------------------------------------------------
class SchemaFieldDef(BaseModel):
    """Schema 字段定义。"""

    name: str
    description: str = ""
    field_type: str = "string"
    required: bool = False
    enum_values: list[str] | None = None


class SchemaCreateRequest(BaseModel):
    """Schema 创建请求体。

    parent_id 为 None 时创建父分类；指定 parent_id 时创建该分类下的子 Schema。
    """

    name: str
    description: str = ""
    doc_type: str = ""
    fields: list[dict] = []
    sample_fields: dict = {}
    parent_id: str | None = None
    is_active: bool = True
    sort_order: int = 0


class SchemaUpdateRequest(BaseModel):
    """Schema 更新请求体。所有字段可选。"""

    name: str | None = None
    description: str | None = None
    doc_type: str | None = None
    fields: list[dict] | None = None
    sample_fields: dict | None = None
    parent_id: str | None = None
    is_active: bool | None = None
    sort_order: int | None = None


# ---------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------
def serialize_schema(s: SchemaConfig, children_count: int | None = None) -> dict:
    """将 SchemaConfig ORM 对象序列化为字典。

    Args:
        s: SchemaConfig 实例
        children_count: 可选，子 Schema 数量（仅父分类有意义）
    """
    result = {
        "id": str(s.id),
        "parent_id": str(s.parent_id) if s.parent_id else None,
        "name": s.name,
        "description": s.description or "",
        "doc_type": "",
        "fields": s.schema_definition or [],
        "sample_fields": s.sample_fields or {},
        "is_active": s.is_active,
        "sort_order": s.sort_order,
        "created_at": s.created_at.isoformat() if s.created_at else "",
        "updated_at": s.updated_at.isoformat() if s.updated_at else "",
        "is_parent": s.parent_id is None,
    }
    if children_count is not None:
        result["children_count"] = children_count
    return result


# ---------------------------------------------------------------
# 父分类相关端点（必须在 /{schema_id} 之前定义，避免路径冲突）
# ---------------------------------------------------------------
@router.get("/categories")
async def list_categories(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """查询所有父分类（含子 Schema 数量统计）。

    返回所有 parent_id IS NULL 的 Schema 节点，并附带每个父分类下的子 Schema 数量。
    用于前端父分类卡片展示。
    """
    # 查询所有父分类
    stmt = (
        select(SchemaConfig)
        .where(SchemaConfig.parent_id.is_(None))
        .order_by(SchemaConfig.sort_order, SchemaConfig.created_at)
    )
    result = await db.execute(stmt)
    parents = result.scalars().all()

    # 批量查询每个父分类的子 Schema 数量
    parent_ids = [p.id for p in parents]
    children_counts: dict[str, int] = {}
    if parent_ids:
        count_stmt = (
            select(SchemaConfig.parent_id, func.count(SchemaConfig.id))
            .where(SchemaConfig.parent_id.in_(parent_ids))
            .group_by(SchemaConfig.parent_id)
        )
        count_result = await db.execute(count_stmt)
        for parent_id, cnt in count_result.all():
            children_counts[str(parent_id)] = cnt

    items = [
        serialize_schema(p, children_count=children_counts.get(str(p.id), 0))
        for p in parents
    ]
    return success(data=items)


@router.get("/{parent_id}/children")
async def list_children(
    parent_id: UUID,
    only_active: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """查询父分类下的所有子 Schema。

    Args:
        parent_id: 父分类 ID
        only_active: 是否仅返回启用的子 Schema
    """
    stmt = (
        select(SchemaConfig)
        .where(SchemaConfig.parent_id == parent_id)
        .order_by(SchemaConfig.sort_order, SchemaConfig.created_at)
    )
    if only_active:
        stmt = stmt.where(SchemaConfig.is_active.is_(True))
    result = await db.execute(stmt)
    children = result.scalars().all()

    items = [serialize_schema(c) for c in children]
    return success(data=items)


@router.get("/{parent_id}/merged")
async def get_merged_schema(
    parent_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """合并父分类下所有启用的子 Schema 为整体 Schema。

    用于 LangExtract 抽取时获取完整字段定义：
    1. 加载父分类信息
    2. 加载所有启用的子 Schema
    3. 合并所有子 Schema 的 fields，去重同名字段
    4. 合并所有子 Schema 的 sample_fields
    """
    # 加载父分类
    parent_stmt = select(SchemaConfig).where(SchemaConfig.id == parent_id)
    parent_result = await db.execute(parent_stmt)
    parent = parent_result.scalar_one_or_none()
    if parent is None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_DOCUMENT_NOT_FOUND,
            message=f"父分类 {parent_id} 不存在",
        )
    if parent.parent_id is not None:
        raise BusinessException(
            code=ErrorCode.VALIDATION_ERROR,
            message=f"{parent_id} 不是父分类（parent_id 不为空）",
        )

    # 加载启用的子 Schema
    children_stmt = (
        select(SchemaConfig)
        .where(SchemaConfig.parent_id == parent_id)
        .where(SchemaConfig.is_active.is_(True))
        .order_by(SchemaConfig.sort_order, SchemaConfig.created_at)
    )
    children_result = await db.execute(children_stmt)
    children = children_result.scalars().all()

    # 合并字段定义（去重同名字段，后出现的覆盖前面的）
    merged_fields: list[dict] = []
    seen_field_names: set[str] = set()
    merged_samples: dict = {}
    for child in children:
        for field in (child.schema_definition or []):
            if not isinstance(field, dict):
                continue
            name = field.get("name")
            if not name or name in seen_field_names:
                continue
            seen_field_names.add(name)
            merged_fields.append(field)
        # 合并示例
        for k, v in (child.sample_fields or {}).items():
            if k not in merged_samples:
                merged_samples[k] = v

    return success(data={
        "id": str(parent.id),
        "name": parent.name,
        "description": parent.description or "",
        "fields": merged_fields,
        "sample_fields": merged_samples,
        "children_count": len(children),
        "children_ids": [str(c.id) for c in children],
    })


# ---------------------------------------------------------------
# 标准 CRUD 端点
# ---------------------------------------------------------------
@router.get("/")
async def list_schemas(
    pagination: dict = Depends(get_pagination_params),
    parent_id: str | None = None,
    only_parent: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """分页查询 Schema 列表。

    支持通过 parent_id 筛选特定分类下的 Schema；only_parent=True 时仅返回父分类。
    """
    page = pagination["page"]
    page_size = pagination["page_size"]

    base_stmt = select(SchemaConfig)
    if only_parent:
        base_stmt = base_stmt.where(SchemaConfig.parent_id.is_(None))
    elif parent_id is not None:
        base_stmt = base_stmt.where(SchemaConfig.parent_id == parent_id)

    total_result = await db.execute(
        select(func.count()).select_from(base_stmt.subquery())
    )
    total = total_result.scalar_one()

    list_stmt = (
        base_stmt.order_by(SchemaConfig.sort_order, SchemaConfig.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(list_stmt)
    schemas = result.scalars().all()

    items = [serialize_schema(s) for s in schemas]
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

    children_count = 0
    if schema.parent_id is None:
        # 父分类：统计子 Schema 数量
        count_stmt = select(func.count()).where(
            SchemaConfig.parent_id == schema.id
        )
        children_count = (await db.execute(count_stmt)).scalar_one()

    return success(data=serialize_schema(schema, children_count=children_count))


@router.post("/")
async def create_schema(
    body: SchemaCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """创建 Schema。

    parent_id 为 None 时创建父分类；指定 parent_id 时创建该分类下的子 Schema。
    """
    # 校验父分类存在
    parent_id_value: UUID | None = None
    if body.parent_id is not None:
        parent_stmt = select(SchemaConfig).where(SchemaConfig.id == UUID(body.parent_id))
        parent_result = await db.execute(parent_stmt)
        parent = parent_result.scalar_one_or_none()
        if parent is None:
            raise BusinessException(
                code=ErrorCode.BUSINESS_DOCUMENT_NOT_FOUND,
                message=f"父分类 {body.parent_id} 不存在",
            )
        if parent.parent_id is not None:
            raise BusinessException(
                code=ErrorCode.VALIDATION_ERROR,
                message="不支持多级嵌套，parent_id 必须指向父分类节点",
            )
        parent_id_value = parent.id

    schema = SchemaConfig(
        parent_id=parent_id_value,
        name=body.name,
        description=body.description,
        schema_definition=body.fields,
        sample_fields=body.sample_fields,
        is_active=body.is_active,
        sort_order=body.sort_order,
        is_template=not body.is_active,  # 兼容旧字段
    )
    db.add(schema)
    await db.commit()
    await db.refresh(schema)

    return success(data=serialize_schema(schema, children_count=0))


@router.put("/{schema_id}")
async def update_schema(
    schema_id: UUID,
    body: SchemaUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """更新 Schema。所有字段可选，仅更新提供的字段。"""
    stmt = select(SchemaConfig).where(SchemaConfig.id == schema_id)
    result = await db.execute(stmt)
    schema = result.scalar_one_or_none()

    if schema is None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_DOCUMENT_NOT_FOUND,
            message=f"Schema {schema_id} 不存在",
        )

    # 校验 parent_id（如果提供了的话）
    if body.parent_id is not None:
        if body.parent_id == str(schema_id):
            raise BusinessException(
                code=ErrorCode.VALIDATION_ERROR,
                message="不能将 Schema 的 parent_id 设为自身",
            )
        parent_stmt = select(SchemaConfig).where(
            SchemaConfig.id == UUID(body.parent_id)
        )
        parent_result = await db.execute(parent_stmt)
        parent = parent_result.scalar_one_or_none()
        if parent is None:
            raise BusinessException(
                code=ErrorCode.BUSINESS_DOCUMENT_NOT_FOUND,
                message=f"父分类 {body.parent_id} 不存在",
            )
        if parent.parent_id is not None:
            raise BusinessException(
                code=ErrorCode.VALIDATION_ERROR,
                message="不支持多级嵌套，parent_id 必须指向父分类节点",
            )
        schema.parent_id = parent.id

    if body.name is not None:
        schema.name = body.name
    if body.description is not None:
        schema.description = body.description
    if body.fields is not None:
        schema.schema_definition = body.fields
    if body.sample_fields is not None:
        schema.sample_fields = body.sample_fields
    if body.is_active is not None:
        schema.is_active = body.is_active
        schema.is_template = not body.is_active  # 同步兼容字段
    if body.sort_order is not None:
        schema.sort_order = body.sort_order

    await db.commit()
    await db.refresh(schema)

    children_count = 0
    if schema.parent_id is None:
        count_stmt = select(func.count()).where(
            SchemaConfig.parent_id == schema.id
        )
        children_count = (await db.execute(count_stmt)).scalar_one()

    return success(data=serialize_schema(schema, children_count=children_count))


@router.delete("/{schema_id}")
async def delete_schema(
    schema_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """删除 Schema。

    父分类删除时会级联删除所有子 Schema（通过外键 ON DELETE CASCADE）。
    """
    stmt = select(SchemaConfig).where(SchemaConfig.id == schema_id)
    result = await db.execute(stmt)
    schema = result.scalar_one_or_none()

    if schema is None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_DOCUMENT_NOT_FOUND,
            message=f"Schema {schema_id} 不存在",
        )

    # 检查是否为父分类且有子 Schema
    if schema.parent_id is None:
        count_stmt = select(func.count()).where(
            SchemaConfig.parent_id == schema.id
        )
        children_count = (await db.execute(count_stmt)).scalar_one()
        if children_count > 0:
            raise BusinessException(
                code=ErrorCode.VALIDATION_ERROR,
                message=f"父分类「{schema.name}」下还有 {children_count} 个子 Schema，"
                f"请先删除子 Schema 或迁移到其他分类",
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
    """启用/停用 Schema。直接修改 is_active 字段，确保状态一致性。"""
    stmt = select(SchemaConfig).where(SchemaConfig.id == schema_id)
    result = await db.execute(stmt)
    schema = result.scalar_one_or_none()

    if schema is None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_DOCUMENT_NOT_FOUND,
            message=f"Schema {schema_id} 不存在",
        )

    is_active = body.get("is_active", True)
    schema.is_active = is_active
    schema.is_template = not is_active  # 同步兼容字段
    await db.commit()
    await db.refresh(schema)

    return success(data={
        "id": str(schema.id),
        "name": schema.name,
        "is_active": schema.is_active,
    })
