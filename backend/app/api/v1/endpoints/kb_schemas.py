"""知识库内 Schema 管理端点（阶段 1.2）。

提供 KB 隔离的抽取 Schema CRUD，所有端点强制 ``Depends(get_kb_context)``
实现知识库隔离与 RBAC 权限校验。SchemaConfig 表已含 kb_id 并启用 RLS，
查询自动按当前 KB 过滤。

端点（前缀 ``/kbs/{kb_id}/schemas``）：
- GET    /                 分页查询 Schema 列表（任意成员）
- GET    /categories       父分类列表（含子 Schema 数量）（任意成员）
- GET    /{parent_id}/children  父分类下子 Schema（任意成员）
- GET    /{parent_id}/merged    合并父分类下子 Schema（任意成员）
- GET    /{schema_id}      Schema 详情（任意成员）
- POST   /                 创建 Schema（editor+）
- PUT    /{schema_id}      更新 Schema（editor+）
- DELETE /{schema_id}      删除 Schema（editor+）
- PATCH  /{schema_id}/active 启停 Schema（editor+）
- POST   /{schema_id}/copy 复制 Schema（editor+）

与旧 ``schemas.py``（全局，向后兼容）共存。
"""

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import KBContext, get_kb_context, get_pagination_params, require_role
from app.core.database import get_db
from app.core.exceptions import BusinessException, ErrorCode
from app.core.response import paginated, success
from app.models.knowledge_base import EDIT_ROLES
from app.models.schema_model import SchemaConfig

router = APIRouter(prefix="/kbs/{kb_id}/schemas", tags=["知识库-Schema 管理"])


# ============================================================
# 请求体定义
# ============================================================
class SchemaCreateRequest(BaseModel):
    """Schema 创建请求体。

    parent_id 为 None 时创建父分类；指定 parent_id 时创建该分类下的子 Schema。
    """

    name: str
    description: str = ""
    fields: list[dict] = []
    sample_fields: dict = {}
    parent_id: str | None = None
    is_active: bool = True
    sort_order: int = 0


class SchemaUpdateRequest(BaseModel):
    """Schema 更新请求体。所有字段可选。"""

    name: str | None = None
    description: str | None = None
    fields: list[dict] | None = None
    sample_fields: dict | None = None
    parent_id: str | None = None
    is_active: bool | None = None
    sort_order: int | None = None


class SchemaCopyRequest(BaseModel):
    """Schema 复制请求体。"""

    new_name: str
    new_parent_id: str | None = None


# ============================================================
# 工具函数
# ============================================================
def _serialize(s: SchemaConfig, children_count: int | None = None) -> dict:
    """序列化 SchemaConfig 为响应字典。"""
    result = {
        "id": str(s.id),
        "parent_id": str(s.parent_id) if s.parent_id else None,
        "name": s.name,
        "description": s.description or "",
        "fields": s.schema_definition or [],
        "sample_fields": s.sample_fields or {},
        "is_active": s.is_active,
        "sort_order": s.sort_order,
        "is_parent": s.parent_id is None,
        "created_at": s.created_at.isoformat() if s.created_at else "",
        "updated_at": s.updated_at.isoformat() if s.updated_at else "",
    }
    if children_count is not None:
        result["children_count"] = children_count
    return result


# ============================================================
# 父分类与合并端点（路径优先，避免与 /{schema_id} 冲突）
# ============================================================
@router.get("/categories")
async def list_categories(
    kb_ctx: KBContext = Depends(get_kb_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """查询 KB 内所有父分类（含子 Schema 数量统计）。"""
    # 显式按 kb_id 过滤，纵深防御不依赖 RLS（superuser 绕过 RLS）
    stmt = (
        select(SchemaConfig)
        .where(
            SchemaConfig.parent_id.is_(None),
            SchemaConfig.kb_id == kb_ctx.kb_id,
        )
        .order_by(SchemaConfig.sort_order, SchemaConfig.created_at)
    )
    parents = (await db.execute(stmt)).scalars().all()

    parent_ids = [p.id for p in parents]
    counts: dict[str, int] = {}
    if parent_ids:
        count_stmt = (
            select(SchemaConfig.parent_id, func.count(SchemaConfig.id))
            .where(
                SchemaConfig.parent_id.in_(parent_ids),
                SchemaConfig.kb_id == kb_ctx.kb_id,
            )
            .group_by(SchemaConfig.parent_id)
        )
        for pid, cnt in (await db.execute(count_stmt)).all():
            counts[str(pid)] = cnt

    return success(data=[_serialize(p, counts.get(str(p.id), 0)) for p in parents])


@router.get("/{parent_id}/children")
async def list_children(
    parent_id: UUID,
    only_active: bool = False,
    kb_ctx: KBContext = Depends(get_kb_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """查询父分类下的所有子 Schema（显式按 kb_id 过滤，纵深防御不依赖 RLS）。"""
    stmt = (
        select(SchemaConfig)
        .where(
            SchemaConfig.parent_id == parent_id,
            SchemaConfig.kb_id == kb_ctx.kb_id,
        )
        .order_by(SchemaConfig.sort_order, SchemaConfig.created_at)
    )
    if only_active:
        stmt = stmt.where(SchemaConfig.is_active.is_(True))
    children = (await db.execute(stmt)).scalars().all()
    return success(data=[_serialize(c) for c in children])


@router.get("/{parent_id}/merged")
async def get_merged_schema(
    parent_id: UUID,
    kb_ctx: KBContext = Depends(get_kb_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """合并父分类下所有启用的子 Schema 为整体 Schema（供 LangExtract 抽取）。"""
    # 显式按 kb_id 过滤，纵深防御不依赖 RLS（superuser 绕过 RLS）
    parent = (
        await db.execute(
            select(SchemaConfig).where(
                SchemaConfig.id == parent_id,
                SchemaConfig.kb_id == kb_ctx.kb_id,
            )
        )
    ).scalar_one_or_none()
    if parent is None or parent.parent_id is not None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_SCHEMA_NOT_FOUND,
            message=f"父分类 {parent_id} 不存在",
        )

    children = (
        await db.execute(
            select(SchemaConfig)
            .where(
                SchemaConfig.parent_id == parent_id,
                SchemaConfig.is_active.is_(True),
                SchemaConfig.kb_id == kb_ctx.kb_id,
            )
            .order_by(SchemaConfig.sort_order, SchemaConfig.created_at)
        )
    ).scalars().all()

    merged_fields: list[dict] = []
    seen: set[str] = set()
    merged_samples: dict = {}
    for child in children:
        for field in (child.schema_definition or []):
            if not isinstance(field, dict):
                continue
            name = field.get("name")
            if name and name not in seen:
                seen.add(name)
                merged_fields.append(field)
        for k, v in (child.sample_fields or {}).items():
            merged_samples.setdefault(k, v)

    return success(data={
        "id": str(parent.id),
        "name": parent.name,
        "description": parent.description or "",
        "fields": merged_fields,
        "sample_fields": merged_samples,
        "children_count": len(children),
        "children_ids": [str(c.id) for c in children],
    })


# ============================================================
# 标准 CRUD
# ============================================================
@router.get("")
async def list_schemas(
    kb_ctx: KBContext = Depends(get_kb_context),
    pagination: dict = Depends(get_pagination_params),
    db: AsyncSession = Depends(get_db),
    parent_id: str | None = None,
    only_parent: bool = False,
) -> dict:
    """分页查询 KB 内 Schema 列表（显式按 kb_id 过滤，纵深防御不依赖 RLS）。"""
    page = pagination["page"]
    page_size = pagination["page_size"]

    # 显式按 kb_id 过滤，纵深防御不依赖 RLS（superuser 绕过 RLS）
    base = select(SchemaConfig).where(SchemaConfig.kb_id == kb_ctx.kb_id)
    if only_parent:
        base = base.where(SchemaConfig.parent_id.is_(None))
    elif parent_id is not None:
        base = base.where(SchemaConfig.parent_id == parent_id)

    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    list_stmt = (
        base.order_by(SchemaConfig.sort_order, SchemaConfig.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    schemas = (await db.execute(list_stmt)).scalars().all()
    return paginated([_serialize(s) for s in schemas], total, page, page_size)


@router.get("/{schema_id}")
async def get_schema(
    schema_id: UUID,
    kb_ctx: KBContext = Depends(get_kb_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取 Schema 详情（显式按 kb_id 过滤，纵深防御不依赖 RLS）。"""
    # 显式按 kb_id 过滤，纵深防御不依赖 RLS（superuser 绕过 RLS）
    schema = (
        await db.execute(
            select(SchemaConfig).where(
                SchemaConfig.id == schema_id,
                SchemaConfig.kb_id == kb_ctx.kb_id,
            )
        )
    ).scalar_one_or_none()
    if schema is None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_SCHEMA_NOT_FOUND,
            message=f"Schema {schema_id} 不存在",
        )
    children_count = 0
    if schema.parent_id is None:
        children_count = (
            await db.execute(
                select(func.count())
                .where(
                    SchemaConfig.parent_id == schema.id,
                    SchemaConfig.kb_id == kb_ctx.kb_id,
                )
            )
        ).scalar_one()
    return success(data=_serialize(schema, children_count=children_count))


@router.post("")
async def create_schema(
    body: SchemaCreateRequest,
    kb_ctx: KBContext = Depends(require_role(*EDIT_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """创建 Schema（editor+）。parent_id 为 None 创建父分类。"""
    parent_id_value: UUID | None = None
    if body.parent_id is not None:
        # 显式按 kb_id 过滤，纵深防御不依赖 RLS（superuser 绕过 RLS）
        parent = (
            await db.execute(
                select(SchemaConfig).where(
                    SchemaConfig.id == UUID(body.parent_id),
                    SchemaConfig.kb_id == kb_ctx.kb_id,
                )
            )
        ).scalar_one_or_none()
        if parent is None or parent.parent_id is not None:
            raise BusinessException(
                code=ErrorCode.BUSINESS_SCHEMA_NOT_FOUND,
                message="父分类不存在或不支持多级嵌套",
            )
        parent_id_value = parent.id

    schema = SchemaConfig(
        kb_id=kb_ctx.kb_id,
        parent_id=parent_id_value,
        name=body.name,
        description=body.description,
        schema_definition=body.fields,
        sample_fields=body.sample_fields,
        is_active=body.is_active,
        sort_order=body.sort_order,
        is_template=not body.is_active,
    )
    db.add(schema)
    await db.commit()
    await db.refresh(schema)
    return success(data=_serialize(schema, children_count=0))


@router.put("/{schema_id}")
async def update_schema(
    schema_id: UUID,
    body: SchemaUpdateRequest,
    kb_ctx: KBContext = Depends(require_role(*EDIT_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """更新 Schema（editor+）。所有字段可选。"""
    # 显式按 kb_id 过滤，纵深防御不依赖 RLS（superuser 绕过 RLS）
    schema = (
        await db.execute(
            select(SchemaConfig).where(
                SchemaConfig.id == schema_id,
                SchemaConfig.kb_id == kb_ctx.kb_id,
            )
        )
    ).scalar_one_or_none()
    if schema is None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_SCHEMA_NOT_FOUND,
            message=f"Schema {schema_id} 不存在",
        )

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
        schema.is_template = not body.is_active
    if body.sort_order is not None:
        schema.sort_order = body.sort_order
    if body.parent_id is not None:
        if body.parent_id == str(schema_id):
            raise BusinessException(
                code=ErrorCode.VALIDATION_ERROR,
                message="不能将 Schema 的 parent_id 设为自身",
            )
        # 显式按 kb_id 过滤，纵深防御不依赖 RLS
        parent = (
            await db.execute(
                select(SchemaConfig).where(
                    SchemaConfig.id == UUID(body.parent_id),
                    SchemaConfig.kb_id == kb_ctx.kb_id,
                )
            )
        ).scalar_one_or_none()
        if parent is None or parent.parent_id is not None:
            raise BusinessException(
                code=ErrorCode.VALIDATION_ERROR,
                message="父分类不存在或不支持多级嵌套",
            )
        schema.parent_id = parent.id

    await db.commit()
    await db.refresh(schema)
    children_count = 0
    if schema.parent_id is None:
        # 显式按 kb_id 过滤，纵深防御不依赖 RLS
        children_count = (
            await db.execute(
                select(func.count())
                .where(
                    SchemaConfig.parent_id == schema.id,
                    SchemaConfig.kb_id == kb_ctx.kb_id,
                )
            )
        ).scalar_one()
    return success(data=_serialize(schema, children_count=children_count))


@router.delete("/{schema_id}")
async def delete_schema(
    schema_id: UUID,
    kb_ctx: KBContext = Depends(require_role(*EDIT_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """删除 Schema（editor+）。父分类下有子 Schema 时拒绝删除。"""
    # 显式按 kb_id 过滤，纵深防御不依赖 RLS（superuser 绕过 RLS）
    schema = (
        await db.execute(
            select(SchemaConfig).where(
                SchemaConfig.id == schema_id,
                SchemaConfig.kb_id == kb_ctx.kb_id,
            )
        )
    ).scalar_one_or_none()
    if schema is None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_SCHEMA_NOT_FOUND,
            message=f"Schema {schema_id} 不存在",
        )
    if schema.parent_id is None:
        children_count = (
            await db.execute(
                select(func.count())
                .where(
                    SchemaConfig.parent_id == schema.id,
                    SchemaConfig.kb_id == kb_ctx.kb_id,
                )
            )
        ).scalar_one()
        if children_count > 0:
            raise BusinessException(
                code=ErrorCode.VALIDATION_ERROR,
                message=f"父分类「{schema.name}」下还有 {children_count} 个子 Schema，请先删除子 Schema",
            )
    await db.delete(schema)
    await db.commit()
    return success(message="删除成功")


@router.patch("/{schema_id}/active")
async def toggle_active(
    schema_id: UUID,
    body: dict,
    kb_ctx: KBContext = Depends(require_role(*EDIT_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """启用/停用 Schema（editor+）。"""
    # 显式按 kb_id 过滤，纵深防御不依赖 RLS（superuser 绕过 RLS）
    schema = (
        await db.execute(
            select(SchemaConfig).where(
                SchemaConfig.id == schema_id,
                SchemaConfig.kb_id == kb_ctx.kb_id,
            )
        )
    ).scalar_one_or_none()
    if schema is None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_SCHEMA_NOT_FOUND,
            message=f"Schema {schema_id} 不存在",
        )
    is_active = body.get("is_active", True)
    schema.is_active = is_active
    schema.is_template = not is_active
    await db.commit()
    await db.refresh(schema)
    return success(data={"id": str(schema.id), "name": schema.name, "is_active": schema.is_active})


@router.post("/{schema_id}/copy")
async def copy_schema(
    schema_id: UUID,
    body: SchemaCopyRequest,
    kb_ctx: KBContext = Depends(require_role(*EDIT_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """复制 Schema（editor+）。复制字段定义与示例到新 Schema。"""
    # 显式按 kb_id 过滤，纵深防御不依赖 RLS（superuser 绕过 RLS）
    src = (
        await db.execute(
            select(SchemaConfig).where(
                SchemaConfig.id == schema_id,
                SchemaConfig.kb_id == kb_ctx.kb_id,
            )
        )
    ).scalar_one_or_none()
    if src is None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_SCHEMA_NOT_FOUND,
            message=f"Schema {schema_id} 不存在",
        )
    parent_id_value: UUID | None = None
    if body.new_parent_id is not None:
        # 显式按 kb_id 过滤，纵深防御不依赖 RLS
        parent = (
            await db.execute(
                select(SchemaConfig).where(
                    SchemaConfig.id == UUID(body.new_parent_id),
                    SchemaConfig.kb_id == kb_ctx.kb_id,
                )
            )
        ).scalar_one_or_none()
        if parent is None or parent.parent_id is not None:
            raise BusinessException(
                code=ErrorCode.VALIDATION_ERROR,
                message="目标父分类不存在或不支持多级嵌套",
            )
        parent_id_value = parent.id
    elif src.parent_id is not None:
        parent_id_value = src.parent_id

    new_schema = SchemaConfig(
        kb_id=kb_ctx.kb_id,
        parent_id=parent_id_value,
        name=body.new_name,
        description=src.description,
        schema_definition=src.schema_definition,
        sample_fields=src.sample_fields,
        is_active=True,
        sort_order=src.sort_order,
        is_template=False,
    )
    db.add(new_schema)
    await db.commit()
    await db.refresh(new_schema)
    return success(data=_serialize(new_schema, children_count=0))
