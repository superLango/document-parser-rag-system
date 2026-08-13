# ruff: noqa: B008 - FastAPI Depends 默认参数为框架标准写法（与现有端点一致）
"""抽取配置端点（M34/S2）：Schema 模板、Prompt、规则组、脚本。"""

import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import activate_kb_context, require_not_pending
from app.api.v1.endpoints.kb_documents import _require_editor
from app.core.database import get_db
from app.core.exceptions import BusinessException, ErrorCode, PermissionException
from app.core.response import success
from app.middleware.audit_log import audit_action
from app.models.user import User
from app.schemas.extraction import (
    GlobalConfigSave,
    PromptCreate,
    PromptSaveRequest,
    PromptUpdate,
    RuleGroupCreate,
    RuleGroupItemsSave,
    SchemaCategoryCreate,
    SchemaCategoryUpdate,
    SchemaFieldCreate,
    SchemaFieldUpdate,
    SchemaTemplateCreate,
    SchemaTemplateUpdate,
    ScriptCreate,
    ScriptEmbedRequest,
    ScriptRunRequest,
    ScriptUpdate,
)
from app.services import extraction_config_service as svc
from app.services import kb_service
from app.services.extraction import script_tools

schema_router = APIRouter(prefix="/kb/{kb_id}/schema-templates", tags=["知识库-抽取配置-Schema"])
cfg_router = APIRouter(prefix="/kb/{kb_id}/extraction-config", tags=["知识库-抽取配置"])


async def _kb_access(
    kb_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> dict:
    data = await kb_service.get_kb(db, current_user, kb_id)
    await activate_kb_context(db, kb_id, current_user)
    return data


# ============================================================
# Schema 模板
# ============================================================
@schema_router.get("")
async def list_schema_templates(
    kb_id: uuid.UUID, request: Request,
    db: AsyncSession = Depends(get_db), current_user: User = Depends(require_not_pending),
) -> dict:
    """Schema 模板列表（成员可读）。"""
    await _kb_access(kb_id, db=db, current_user=current_user)
    return success(data={"items": await svc.list_schema_templates(db, kb_id)})


@schema_router.post("")
@audit_action(action="schema_template.create", resource_type="schema_template")
async def create_schema_template(
    kb_id: uuid.UUID, payload: SchemaTemplateCreate, request: Request,
    db: AsyncSession = Depends(get_db), current_user: User = Depends(require_not_pending),
) -> dict:
    kb = await _kb_access(kb_id, db=db, current_user=current_user)
    _require_editor(kb)
    data = await svc.create_schema_template(db, kb_id, current_user.id, payload.model_dump())
    return success(data=data, message="Schema 模板已创建")


@schema_router.get("/{template_id}")
async def get_schema_template(
    kb_id: uuid.UUID, template_id: uuid.UUID, request: Request,
    db: AsyncSession = Depends(get_db), current_user: User = Depends(require_not_pending),
) -> dict:
    await _kb_access(kb_id, db=db, current_user=current_user)
    return success(data=await svc.get_schema_template(db, kb_id, template_id))


@schema_router.put("/{template_id}")
@audit_action(action="schema_template.update", resource_type="schema_template")
async def update_schema_template(
    kb_id: uuid.UUID, template_id: uuid.UUID, payload: SchemaTemplateUpdate, request: Request,
    db: AsyncSession = Depends(get_db), current_user: User = Depends(require_not_pending),
) -> dict:
    kb = await _kb_access(kb_id, db=db, current_user=current_user)
    _require_editor(kb)
    data = await svc.update_schema_template(db, kb_id, template_id, payload.model_dump(exclude_none=True))
    return success(data=data, message="Schema 模板已更新")


@schema_router.delete("/{template_id}")
@audit_action(action="schema_template.delete", resource_type="schema_template")
async def delete_schema_template(
    kb_id: uuid.UUID, template_id: uuid.UUID, request: Request,
    db: AsyncSession = Depends(get_db), current_user: User = Depends(require_not_pending),
) -> dict:
    kb = await _kb_access(kb_id, db=db, current_user=current_user)
    _require_editor(kb)
    await svc.delete_schema_template(db, kb_id, template_id)
    return success(message="Schema 模板已删除")


@schema_router.post("/{template_id}/categories")
@audit_action(action="schema_category.create", resource_type="schema_category")
async def create_schema_category(
    kb_id: uuid.UUID, template_id: uuid.UUID, payload: SchemaCategoryCreate, request: Request,
    db: AsyncSession = Depends(get_db), current_user: User = Depends(require_not_pending),
) -> dict:
    kb = await _kb_access(kb_id, db=db, current_user=current_user)
    _require_editor(kb)
    data = await svc.create_schema_category(db, kb_id, template_id, payload.model_dump())
    return success(data=data, message="Schema 类别已创建")


@schema_router.put("/{template_id}/categories/{category_id}")
@audit_action(action="schema_category.update", resource_type="schema_category")
async def update_schema_category(
    kb_id: uuid.UUID, template_id: uuid.UUID, category_id: uuid.UUID,
    payload: SchemaCategoryUpdate, request: Request,
    db: AsyncSession = Depends(get_db), current_user: User = Depends(require_not_pending),
) -> dict:
    kb = await _kb_access(kb_id, db=db, current_user=current_user)
    _require_editor(kb)
    data = await svc.update_schema_category(
        db, kb_id, template_id, category_id, payload.model_dump(exclude_none=True)
    )
    return success(data=data, message="Schema 类别已更新")


@schema_router.delete("/{template_id}/categories/{category_id}")
@audit_action(action="schema_category.delete", resource_type="schema_category")
async def delete_schema_category(
    kb_id: uuid.UUID, template_id: uuid.UUID, category_id: uuid.UUID, request: Request,
    db: AsyncSession = Depends(get_db), current_user: User = Depends(require_not_pending),
) -> dict:
    kb = await _kb_access(kb_id, db=db, current_user=current_user)
    _require_editor(kb)
    await svc.delete_schema_category(db, kb_id, template_id, category_id)
    return success(message="Schema 类别已删除")


@schema_router.post("/{template_id}/categories/{category_id}/fields")
@audit_action(action="schema_field.create", resource_type="schema_field")
async def create_schema_field(
    kb_id: uuid.UUID, template_id: uuid.UUID, category_id: uuid.UUID,
    payload: SchemaFieldCreate, request: Request,
    db: AsyncSession = Depends(get_db), current_user: User = Depends(require_not_pending),
) -> dict:
    kb = await _kb_access(kb_id, db=db, current_user=current_user)
    _require_editor(kb)
    data = await svc.create_schema_field(db, kb_id, template_id, category_id, payload.model_dump())
    return success(data=data, message="Schema 字段已创建")


@schema_router.put("/{template_id}/categories/{category_id}/fields/{field_id}")
@audit_action(action="schema_field.update", resource_type="schema_field")
async def update_schema_field(
    kb_id: uuid.UUID, template_id: uuid.UUID, category_id: uuid.UUID, field_id: uuid.UUID,
    payload: SchemaFieldUpdate, request: Request,
    db: AsyncSession = Depends(get_db), current_user: User = Depends(require_not_pending),
) -> dict:
    kb = await _kb_access(kb_id, db=db, current_user=current_user)
    _require_editor(kb)
    data = await svc.update_schema_field(
        db, kb_id, template_id, category_id, field_id, payload.model_dump(exclude_none=True)
    )
    return success(data=data, message="Schema 字段已更新")


@schema_router.delete("/{template_id}/categories/{category_id}/fields/{field_id}")
@audit_action(action="schema_field.delete", resource_type="schema_field")
async def delete_schema_field(
    kb_id: uuid.UUID, template_id: uuid.UUID, category_id: uuid.UUID, field_id: uuid.UUID, request: Request,
    db: AsyncSession = Depends(get_db), current_user: User = Depends(require_not_pending),
) -> dict:
    kb = await _kb_access(kb_id, db=db, current_user=current_user)
    _require_editor(kb)
    await svc.delete_schema_field(db, kb_id, template_id, category_id, field_id)
    return success(message="Schema 字段已删除")


# ============================================================
# Prompt 模板
# ============================================================
@cfg_router.get("/global")
async def get_global_config(
    kb_id: uuid.UUID, request: Request,
    db: AsyncSession = Depends(get_db), current_user: User = Depends(require_not_pending),
) -> dict:
    """获取 KB 结构化抽取全局配置（默认值 + 用户覆盖合并）。"""
    await _kb_access(kb_id, db=db, current_user=current_user)
    return success(data=await svc.get_global_config(db, kb_id))


@cfg_router.put("/global")
@audit_action(action="global_config.save", resource_type="global_config")
async def save_global_config(
    kb_id: uuid.UUID, payload: GlobalConfigSave, request: Request,
    db: AsyncSession = Depends(get_db), current_user: User = Depends(require_not_pending),
) -> dict:
    """保存 KB 结构化抽取全局配置（editor+，版本自增）。"""
    kb = await _kb_access(kb_id, db=db, current_user=current_user)
    _require_editor(kb)
    data = await svc.save_global_config(db, kb_id, payload.model_dump())
    return success(data=data, message="全局配置已保存")


@cfg_router.get("/prompts")
async def list_prompts(
    kb_id: uuid.UUID, request: Request,
    db: AsyncSession = Depends(get_db), current_user: User = Depends(require_not_pending),
) -> dict:
    await _kb_access(kb_id, db=db, current_user=current_user)
    return success(data={"items": await svc.list_prompts(db, kb_id)})


@cfg_router.post("/prompts")
@audit_action(action="prompt.create", resource_type="prompt")
async def create_prompt(
    kb_id: uuid.UUID, payload: PromptCreate, request: Request,
    db: AsyncSession = Depends(get_db), current_user: User = Depends(require_not_pending),
) -> dict:
    kb = await _kb_access(kb_id, db=db, current_user=current_user)
    _require_editor(kb)
    data = await svc.create_prompt(db, kb_id, current_user.id, payload.model_dump())
    return success(data=data, message="Prompt 模板已创建")


@cfg_router.get("/prompts/{prompt_id}")
async def get_prompt(
    kb_id: uuid.UUID, prompt_id: uuid.UUID, request: Request,
    db: AsyncSession = Depends(get_db), current_user: User = Depends(require_not_pending),
) -> dict:
    await _kb_access(kb_id, db=db, current_user=current_user)
    return success(data=await svc.get_prompt(db, kb_id, prompt_id))


@cfg_router.put("/prompts/{prompt_id}")
@audit_action(action="prompt.update", resource_type="prompt")
async def update_prompt(
    kb_id: uuid.UUID, prompt_id: uuid.UUID, payload: PromptUpdate, request: Request,
    db: AsyncSession = Depends(get_db), current_user: User = Depends(require_not_pending),
) -> dict:
    kb = await _kb_access(kb_id, db=db, current_user=current_user)
    _require_editor(kb)
    data = await svc.update_prompt(db, kb_id, prompt_id, payload.model_dump(exclude_none=True))
    return success(data=data, message="Prompt 模板已更新")


@cfg_router.put("/prompts/{prompt_id}/save")
@audit_action(action="prompt.save", resource_type="prompt")
async def save_prompt(
    kb_id: uuid.UUID, prompt_id: uuid.UUID, payload: PromptSaveRequest, request: Request,
    db: AsyncSession = Depends(get_db), current_user: User = Depends(require_not_pending),
) -> dict:
    kb = await _kb_access(kb_id, db=db, current_user=current_user)
    _require_editor(kb)
    data = await svc.save_prompt_content(db, kb_id, prompt_id, payload.model_dump(exclude_none=True))
    return success(data=data, message="Prompt 已保存")


@cfg_router.delete("/prompts/{prompt_id}")
@audit_action(action="prompt.delete", resource_type="prompt")
async def delete_prompt(
    kb_id: uuid.UUID, prompt_id: uuid.UUID, request: Request,
    db: AsyncSession = Depends(get_db), current_user: User = Depends(require_not_pending),
) -> dict:
    kb = await _kb_access(kb_id, db=db, current_user=current_user)
    _require_editor(kb)
    await svc.delete_prompt(db, kb_id, prompt_id)
    return success(message="Prompt 模板已删除")


# ============================================================
# 规则组
# ============================================================
@cfg_router.get("/rule-groups")
async def list_rule_groups(
    kb_id: uuid.UUID, request: Request,
    db: AsyncSession = Depends(get_db), current_user: User = Depends(require_not_pending),
) -> dict:
    await _kb_access(kb_id, db=db, current_user=current_user)
    return success(data={"items": await svc.list_rule_groups(db, kb_id)})


@cfg_router.post("/rule-groups")
@audit_action(action="rule_group.create", resource_type="rule_group")
async def create_rule_group(
    kb_id: uuid.UUID, payload: RuleGroupCreate, request: Request,
    db: AsyncSession = Depends(get_db), current_user: User = Depends(require_not_pending),
) -> dict:
    kb = await _kb_access(kb_id, db=db, current_user=current_user)
    _require_editor(kb)
    data = await svc.create_rule_group(db, kb_id, payload.model_dump())
    return success(data=data, message="规则组已创建")


@cfg_router.get("/rule-groups/{group_id}")
async def get_rule_group(
    kb_id: uuid.UUID, group_id: uuid.UUID, request: Request,
    db: AsyncSession = Depends(get_db), current_user: User = Depends(require_not_pending),
) -> dict:
    await _kb_access(kb_id, db=db, current_user=current_user)
    return success(data=await svc.get_rule_group(db, kb_id, group_id))


@cfg_router.put("/rule-groups/{group_id}/items")
@audit_action(action="rule_group.items_save", resource_type="rule_group")
async def save_rule_group_items(
    kb_id: uuid.UUID, group_id: uuid.UUID, payload: RuleGroupItemsSave, request: Request,
    db: AsyncSession = Depends(get_db), current_user: User = Depends(require_not_pending),
) -> dict:
    kb = await _kb_access(kb_id, db=db, current_user=current_user)
    _require_editor(kb)
    data = await svc.save_rule_group_items(db, kb_id, group_id, payload.model_dump())
    return success(data=data, message="规则项已保存")


@cfg_router.delete("/rule-groups/{group_id}")
@audit_action(action="rule_group.delete", resource_type="rule_group")
async def delete_rule_group(
    kb_id: uuid.UUID, group_id: uuid.UUID, request: Request,
    db: AsyncSession = Depends(get_db), current_user: User = Depends(require_not_pending),
) -> dict:
    kb = await _kb_access(kb_id, db=db, current_user=current_user)
    _require_editor(kb)
    await svc.delete_rule_group(db, kb_id, group_id)
    return success(message="规则组已删除")


# ============================================================
# 脚本
# ============================================================
@cfg_router.get("/scripts/io")
async def get_script_io(
    kb_id: uuid.UUID, request: Request,
    db: AsyncSession = Depends(get_db), current_user: User = Depends(require_not_pending),
) -> dict:
    await _kb_access(kb_id, db=db, current_user=current_user)
    return success(data=svc.script_io_registry())


@cfg_router.get("/scripts")
async def list_scripts(
    kb_id: uuid.UUID, request: Request, folder: str | None = Query(default=None, max_length=16),
    db: AsyncSession = Depends(get_db), current_user: User = Depends(require_not_pending),
) -> dict:
    await _kb_access(kb_id, db=db, current_user=current_user)
    return success(data={"items": await svc.list_scripts(db, kb_id, folder)})


@cfg_router.post("/scripts")
@audit_action(action="script.create", resource_type="script")
async def create_script(
    kb_id: uuid.UUID, payload: ScriptCreate, request: Request,
    db: AsyncSession = Depends(get_db), current_user: User = Depends(require_not_pending),
) -> dict:
    kb = await _kb_access(kb_id, db=db, current_user=current_user)
    _require_editor(kb)
    data = await svc.create_script(db, kb_id, current_user.id, payload.model_dump())
    return success(data=data, message="脚本已创建")


@cfg_router.put("/scripts/{script_id}")
@audit_action(action="script.update", resource_type="script")
async def update_script(
    kb_id: uuid.UUID, script_id: uuid.UUID, payload: ScriptUpdate, request: Request,
    db: AsyncSession = Depends(get_db), current_user: User = Depends(require_not_pending),
) -> dict:
    kb = await _kb_access(kb_id, db=db, current_user=current_user)
    _require_editor(kb)
    data = await svc.update_script(db, kb_id, script_id, payload.model_dump(exclude_none=True))
    return success(data=data, message="脚本已更新")


@cfg_router.delete("/scripts/{script_id}")
@audit_action(action="script.delete", resource_type="script")
async def delete_script(
    kb_id: uuid.UUID, script_id: uuid.UUID, request: Request,
    db: AsyncSession = Depends(get_db), current_user: User = Depends(require_not_pending),
) -> dict:
    kb = await _kb_access(kb_id, db=db, current_user=current_user)
    _require_editor(kb)
    await svc.delete_script(db, kb_id, script_id)
    return success(message="脚本已删除")


@cfg_router.post("/script-embed")
async def script_embed(
    kb_id: uuid.UUID, payload: ScriptEmbedRequest,
) -> dict:
    """脚本子进程嵌入回调：内部令牌鉴权，返回 BGE-M3 向量列表。"""
    if not script_tools.validate_embed_token(payload.token, str(kb_id)):
        raise PermissionException(
            code=ErrorCode.AUTH_PERMISSION_DENIED, message="嵌入令牌无效或已过期"
        )
    texts = [t for t in (payload.texts or []) if isinstance(t, str) and t.strip()]
    if len(texts) > script_tools.EMBED_MAX_TEXTS:
        raise BusinessException(
            code=ErrorCode.VALIDATION_ERROR,
            message=f"单次嵌入文本数超过上限（{script_tools.EMBED_MAX_TEXTS}）",
        )
    if not texts:
        return {"vectors": []}
    vectors = await script_tools._cache_embed(texts)
    return {"vectors": vectors}


@cfg_router.post("/scripts/run")
@audit_action(action="script.run", resource_type="script")
async def run_script(
    kb_id: uuid.UUID, payload: ScriptRunRequest, request: Request,
    db: AsyncSession = Depends(get_db), current_user: User = Depends(require_not_pending),
) -> dict:
    # 脚本试运行允许 KB 任意成员（对齐原项目：配置中心试运行）
    await _kb_access(kb_id, db=db, current_user=current_user)
    data = await svc.run_script(db, kb_id, payload.model_dump(exclude_none=True))
    return success(data=data)
