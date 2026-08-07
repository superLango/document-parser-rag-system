"""知识库内 Schema 模板管理端点（三层结构：模板 → 类别 → 字段）。

模板是抽取 Schema 的顶层容器，模板下通过 ``schema_configs`` 组织类别（category）
与字段（field）节点。类别节点携带抽取级配置（return_type / extraction_strategy /
query_mode / fixed_query / confidence_threshold / top_k / datasets 绑定），
字段节点仅含 name / type / description / example / required。

所有端点强制 ``Depends(get_kb_context)`` 实现知识库隔离与 RBAC 权限校验。

端点（前缀 ``/kbs/{kb_id}/schema-templates``）：
- GET    /                          模板列表（任意成员）
- POST   /                          创建模板（editor+）
- GET    /{template_id}             模板详情（含类别树，任意成员）
- PUT    /{template_id}             更新模板（editor+）
- DELETE /{template_id}             删除模板（含类别/字段，editor+）
- POST   /{template_id}/categories  新增类别（editor+）
- PUT    /{template_id}/categories/{category_id}  更新类别（editor+）
- DELETE /{template_id}/categories/{category_id}  删除类别（含字段，editor+）
- POST   /{template_id}/categories/{category_id}/fields  新增字段（editor+）
- PUT    /{template_id}/categories/{category_id}/fields/{field_id}  更新字段（editor+）
- DELETE /{template_id}/categories/{category_id}/fields/{field_id}  删除字段（editor+）
"""

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import KBContext, get_kb_context, require_role
from app.core.database import get_db
from app.core.exceptions import BusinessException, ErrorCode
from app.core.response import success
from app.models.knowledge_base import EDIT_ROLES
from app.models.schema_model import SchemaConfig, SchemaTemplate

router = APIRouter(prefix="/kbs/{kb_id}/schema-templates", tags=["知识库-Schema 模板"])

# 策略/模式合法值
_STRATEGIES = ("auto", "always", "never")
_QUERY_MODES = ("fixed", "dataset", "term_base")
_NAME_SOURCES = ("manual", "term_base")
_RETURN_TYPES = ("object", "array")


# ============================================================
# 请求体定义
# ============================================================
class TemplateCreateRequest(BaseModel):
    name: str
    description: str = ""
    is_active: bool = True


class TemplateUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    is_active: bool | None = None


class CategoryCreateRequest(BaseModel):
    """类别创建请求。"""

    name: str = ""
    description: str = ""
    return_type: str = "array"
    extraction_strategy: str = "auto"
    query_mode: str = "fixed"
    fixed_query: str | None = None
    confidence_threshold: float | None = None
    top_k: int | None = None
    rerank_top_k: int | None = None
    max_tokens: int | None = None
    datasets: list[dict] = Field(default_factory=list)
    is_active: bool = True
    sort_order: int = 0
    # ---- 类别名称来源 / Query 术语集配置 ----
    name_source: str = "manual"
    name_term_base_id: UUID | None = None
    name_term_field: str | None = None
    query_sources: list[dict] = Field(default_factory=list)


class CategoryUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    return_type: str | None = None
    extraction_strategy: str | None = None
    query_mode: str | None = None
    fixed_query: str | None = None
    confidence_threshold: float | None = None
    top_k: int | None = None
    rerank_top_k: int | None = None
    max_tokens: int | None = None
    datasets: list[dict] | None = None
    is_active: bool | None = None
    sort_order: int | None = None
    # ---- 类别名称来源 / Query 术语集配置 ----
    name_source: str | None = None
    name_term_base_id: UUID | None = None
    name_term_field: str | None = None
    query_sources: list[dict] | None = None


class FieldCreateRequest(BaseModel):
    """字段创建请求。"""

    name: str
    type: str = "string"
    description: str = ""
    example: str | None = None
    required: bool = False
    sort_order: int = 0


class FieldUpdateRequest(BaseModel):
    name: str | None = None
    type: str | None = None
    description: str | None = None
    example: str | None = None
    required: bool | None = None
    sort_order: int | None = None


# ============================================================
# 序列化
# ============================================================
def serialize_template(t: SchemaTemplate) -> dict:
    return {
        "id": str(t.id),
        "kb_id": str(t.kb_id),
        "name": t.name,
        "description": t.description or "",
        "is_active": t.is_active,
        "created_at": t.created_at.isoformat() if t.created_at else "",
    }


def serialize_category(c: SchemaConfig) -> dict:
    return {
        "id": str(c.id),
        "name": c.name,
        "description": c.description or "",
        "return_type": c.return_type,
        "extraction_strategy": c.extraction_strategy,
        "query_mode": c.query_mode,
        "fixed_query": c.fixed_query,
        "confidence_threshold": c.confidence_threshold,
        "top_k": c.top_k,
        "rerank_top_k": c.rerank_top_k,
        "max_tokens": c.max_tokens,
        "datasets": c.datasets or [],
        "is_active": c.is_active,
        "sort_order": c.sort_order,
        "name_source": c.name_source,
        "name_term_base_id": str(c.name_term_base_id) if c.name_term_base_id else None,
        "name_term_field": c.name_term_field,
        "query_sources": c.query_sources or [],
    }


def serialize_field(f: SchemaConfig) -> dict:
    sample = f.sample_fields if isinstance(f.sample_fields, dict) else {}
    return {
        "id": str(f.id),
        "name": f.name,
        "type": f.schema_definition.get("type", "string") if isinstance(f.schema_definition, dict) else "string",
        "description": f.description or "",
        "example": sample.get("example") if sample else None,
        "required": f.schema_definition.get("required", False) if isinstance(f.schema_definition, dict) else False,
        "sort_order": f.sort_order,
    }


# ============================================================
# 模板 CRUD
# ============================================================
@router.get("")
async def list_templates(
    kb_ctx: KBContext = Depends(get_kb_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """列出 KB 下的 Schema 模板。"""
    stmt = (
        select(SchemaTemplate)
        .where(SchemaTemplate.kb_id == kb_ctx.kb_id)
        .order_by(SchemaTemplate.created_at)
    )
    result = await db.execute(stmt)
    return success(data=[serialize_template(t) for t in result.scalars().all()])


@router.post("")
async def create_template(
    body: TemplateCreateRequest,
    kb_ctx: KBContext = Depends(require_role(*EDIT_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """创建 Schema 模板。"""
    template = SchemaTemplate(
        kb_id=kb_ctx.kb_id,
        name=body.name,
        description=body.description,
        is_active=body.is_active,
    )
    db.add(template)
    await db.commit()
    await db.refresh(template)
    return success(data=serialize_template(template))


@router.get("/{template_id}")
async def get_template(
    template_id: UUID,
    kb_ctx: KBContext = Depends(get_kb_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取模板详情（含类别树）。"""
    template = await _get_template(db, template_id, kb_ctx.kb_id)
    categories = await _load_categories(db, template_id)
    return success(data={
        **serialize_template(template),
        "categories": categories,
    })


@router.put("/{template_id}")
async def update_template(
    template_id: UUID,
    body: TemplateUpdateRequest,
    kb_ctx: KBContext = Depends(require_role(*EDIT_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """更新模板。"""
    template = await _get_template(db, template_id, kb_ctx.kb_id)
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(template, k, v)
    await db.commit()
    await db.refresh(template)
    return success(data=serialize_template(template))


@router.delete("/{template_id}")
async def delete_template(
    template_id: UUID,
    kb_ctx: KBContext = Depends(require_role(*EDIT_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """删除模板（含类别与字段，级联）。"""
    template = await _get_template(db, template_id, kb_ctx.kb_id)
    await db.delete(template)
    await db.commit()
    return success(message="删除成功")


# ============================================================
# 类别管理
# ============================================================
@router.post("/{template_id}/categories")
async def create_category(
    template_id: UUID,
    body: CategoryCreateRequest,
    kb_ctx: KBContext = Depends(require_role(*EDIT_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """新增类别。"""
    await _get_template(db, template_id, kb_ctx.kb_id)
    _validate_category(body.return_type, body.extraction_strategy, body.query_mode, body.name_source)
    category = SchemaConfig(
        kb_id=kb_ctx.kb_id,
        template_id=template_id,
        node_type="category",
        name=body.name,
        description=body.description,
        return_type=body.return_type,
        extraction_strategy=body.extraction_strategy,
        query_mode=body.query_mode,
        fixed_query=body.fixed_query,
        confidence_threshold=body.confidence_threshold,
        top_k=body.top_k,
        datasets=body.datasets,
        is_active=body.is_active,
        sort_order=body.sort_order,
        name_source=body.name_source,
        name_term_base_id=body.name_term_base_id,
        name_term_field=body.name_term_field,
        query_sources=body.query_sources,
    )
    db.add(category)
    await db.commit()
    await db.refresh(category)
    return success(data=serialize_category(category))


@router.put("/{template_id}/categories/{category_id}")
async def update_category(
    template_id: UUID,
    category_id: UUID,
    body: CategoryUpdateRequest,
    kb_ctx: KBContext = Depends(require_role(*EDIT_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """更新类别。"""
    await _get_template(db, template_id, kb_ctx.kb_id)
    category = await _get_category(db, category_id, template_id, kb_ctx.kb_id)
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(category, k, v)
    await db.commit()
    await db.refresh(category)
    return success(data=serialize_category(category))


@router.delete("/{template_id}/categories/{category_id}")
async def delete_category(
    template_id: UUID,
    category_id: UUID,
    kb_ctx: KBContext = Depends(require_role(*EDIT_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """删除类别（含字段，级联）。"""
    await _get_template(db, template_id, kb_ctx.kb_id)
    category = await _get_category(db, category_id, template_id, kb_ctx.kb_id)
    await db.delete(category)
    await db.commit()
    return success(message="删除成功")


# ============================================================
# 字段管理
# ============================================================
@router.post("/{template_id}/categories/{category_id}/fields")
async def create_field(
    template_id: UUID,
    category_id: UUID,
    body: FieldCreateRequest,
    kb_ctx: KBContext = Depends(require_role(*EDIT_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """新增字段。"""
    await _get_template(db, template_id, kb_ctx.kb_id)
    category = await _get_category(db, category_id, template_id, kb_ctx.kb_id)
    field = SchemaConfig(
        kb_id=kb_ctx.kb_id,
        template_id=template_id,
        parent_id=category.id,
        node_type="field",
        name=body.name,
        description=body.description,
        schema_definition={"type": body.type, "required": body.required},
        sample_fields={"example": body.example} if body.example else {},
        sort_order=body.sort_order,
    )
    db.add(field)
    await db.commit()
    await db.refresh(field)
    return success(data=serialize_field(field))


@router.put("/{template_id}/categories/{category_id}/fields/{field_id}")
async def update_field(
    template_id: UUID,
    category_id: UUID,
    field_id: UUID,
    body: FieldUpdateRequest,
    kb_ctx: KBContext = Depends(require_role(*EDIT_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """更新字段。"""
    await _get_template(db, template_id, kb_ctx.kb_id)
    await _get_category(db, category_id, template_id, kb_ctx.kb_id)
    field = await _get_field(db, field_id, category_id, kb_ctx.kb_id)

    data = body.model_dump(exclude_unset=True)
    if "name" in data:
        field.name = data["name"]
    if "description" in data:
        field.description = data["description"]
    if "sort_order" in data:
        field.sort_order = data["sort_order"]
    if "type" in data or "required" in data:
        defn = field.schema_definition or {}
        if "type" in data:
            defn["type"] = data["type"]
        if "required" in data:
            defn["required"] = data["required"]
        field.schema_definition = defn
    if "example" in data:
        field.sample_fields = {"example": data["example"]} if data["example"] else {}

    await db.commit()
    await db.refresh(field)
    return success(data=serialize_field(field))


@router.delete("/{template_id}/categories/{category_id}/fields/{field_id}")
async def delete_field(
    template_id: UUID,
    category_id: UUID,
    field_id: UUID,
    kb_ctx: KBContext = Depends(require_role(*EDIT_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """删除字段。"""
    await _get_template(db, template_id, kb_ctx.kb_id)
    await _get_category(db, category_id, template_id, kb_ctx.kb_id)
    field = await _get_field(db, field_id, category_id, kb_ctx.kb_id)
    await db.delete(field)
    await db.commit()
    return success(message="删除成功")


# ============================================================
# 辅助
# ============================================================
def _validate_category(return_type: str, strategy: str, query_mode: str, name_source: str = "manual") -> None:
    if return_type not in _RETURN_TYPES:
        raise BusinessException(
            code=ErrorCode.VALIDATION_ERROR, message=f"非法 return_type: {return_type}"
        )
    if strategy not in _STRATEGIES:
        raise BusinessException(
            code=ErrorCode.VALIDATION_ERROR, message=f"非法 extraction_strategy: {strategy}"
        )
    if query_mode not in _QUERY_MODES:
        raise BusinessException(
            code=ErrorCode.VALIDATION_ERROR, message=f"非法 query_mode: {query_mode}"
        )
    if name_source not in _NAME_SOURCES:
        raise BusinessException(
            code=ErrorCode.VALIDATION_ERROR, message=f"非法 name_source: {name_source}"
        )


async def _get_template(db: AsyncSession, template_id: UUID, kb_id) -> SchemaTemplate:
    stmt = select(SchemaTemplate).where(
        SchemaTemplate.id == template_id, SchemaTemplate.kb_id == kb_id
    )
    result = await db.execute(stmt)
    template = result.scalar_one_or_none()
    if template is None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_DOCUMENT_NOT_FOUND,
            message=f"Schema 模板 {template_id} 不存在",
        )
    return template


async def _get_category(
    db: AsyncSession, category_id: UUID, template_id: UUID, kb_id
) -> SchemaConfig:
    stmt = select(SchemaConfig).where(
        SchemaConfig.id == category_id,
        SchemaConfig.kb_id == kb_id,
        SchemaConfig.template_id == template_id,
        SchemaConfig.node_type == "category",
    )
    result = await db.execute(stmt)
    category = result.scalar_one_or_none()
    if category is None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_DOCUMENT_NOT_FOUND,
            message=f"类别 {category_id} 不存在",
        )
    return category


async def _get_field(
    db: AsyncSession, field_id: UUID, category_id: UUID, kb_id
) -> SchemaConfig:
    stmt = select(SchemaConfig).where(
        SchemaConfig.id == field_id,
        SchemaConfig.kb_id == kb_id,
        SchemaConfig.parent_id == category_id,
        SchemaConfig.node_type == "field",
    )
    result = await db.execute(stmt)
    field = result.scalar_one_or_none()
    if field is None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_DOCUMENT_NOT_FOUND,
            message=f"字段 {field_id} 不存在",
        )
    return field


async def _load_categories(db: AsyncSession, template_id: UUID) -> list[dict]:
    """加载模板下类别树（类别 + 字段）。"""
    stmt = (
        select(SchemaConfig)
        .where(SchemaConfig.template_id == template_id)
        .order_by(SchemaConfig.sort_order, SchemaConfig.created_at)
    )
    result = await db.execute(stmt)
    nodes = result.scalars().all()

    categories: list[dict] = []
    fields_by_cat: dict[str, list[dict]] = {}
    for node in nodes:
        if node.node_type == "category":
            categories.append(serialize_category(node))
        elif node.node_type == "field" and node.parent_id:
            fields_by_cat.setdefault(str(node.parent_id), []).append(serialize_field(node))

    for cat in categories:
        cat["fields"] = fields_by_cat.get(cat["id"], [])
    return categories