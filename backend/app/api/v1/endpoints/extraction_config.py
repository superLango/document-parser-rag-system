"""知识库内抽取配置中心端点。

提供 KB 隔离的抽取配置（全局配置 / Prompt 模板 / 抽取规则 / 验证规则 /
术语绑定 / 版本管理）CRUD 与解析接口，所有端点强制 ``Depends(get_kb_context)``
实现知识库隔离与 RBAC 权限校验。

命名规范：全局配置区块使用 ``retrieval`` / ``llm`` / ``post_process``，
不使用 phase 前缀；类别级 top_k / confidence_threshold 通过 Schema 模板
类别节点设置，不设全局专用字段。

端点（前缀 ``/kbs/{kb_id}/extraction-config``）：
- GET  /                         解析获取完整抽取配置（任意成员）
- GET  /global                   获取全局配置（任意成员）
- PUT  /global                   保存全局配置（editor+）
- GET  /prompts                  列出 Prompt 模板（任意成员）
- POST /prompts                  新建 Prompt 模板（editor+）
- PUT  /prompts/{id}             更新 Prompt 模板（editor+）
- DELETE /prompts/{id}           删除 Prompt 模板（editor+）
- GET  /rules                    列出抽取规则（任意成员）
- PUT  /rules                    批量保存抽取规则（editor+）
- GET  /validation               列出验证规则（任意成员）
- PUT  /validation               批量保存验证规则（editor+）
- GET  /bindings                 列出术语绑定（任意成员）
- PUT  /bindings                 批量保存术语绑定（editor+）
- GET  /versions                 列出版本快照（任意成员）
- POST /versions                 创建版本快照（editor+）
- GET  /versions/{id}            查看版本快照详情（任意成员）
- GET  /versions/{id}/diff       对比当前配置与某版本（任意成员）
- POST /versions/{id}/rollback   回滚到某版本（editor+，全量恢复）
- DELETE /versions/{id}          删除某版本快照（editor+）
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
from app.models.extraction_config import (
    KbDomainConfigVersion,
    KbExtractionConfig,
    KbPromptCategory,
    KbPromptTemplate,
    KbRule,
    KbRuleGroup,
    KbRuleGroupItem,
    KbScript,
    KbTermBinding,
    RULE_STAGE_POST,
    SCRIPT_FOLDERS,
)
from app.models.knowledge_base import EDIT_ROLES
from app.models.schema_model import SchemaConfig, SchemaTemplate
from app.models.term import TermBase
from app.services.extraction.rule_engine.registry import RULE_REGISTRY
from app.services.extraction.rule_engine.script_executor import execute_script
from app.services.extraction.rule_engine.script_manager import (
    SCRIPT_IO_REGISTRY,
    script_manager,
)
from app.services.extraction.rule_engine.script_tools import KbScriptTools
from app.services.extraction_config.defaults import get_default_config
from app.services.extraction_config.resolver import ExtractionConfigResolver
from app.services.extraction_config.snapshot_io import (
    diff_snapshots,
    export_snapshot,
    import_snapshot,
)

router = APIRouter(prefix="/kbs/{kb_id}/extraction-config", tags=["知识库-抽取配置"])

resolver = ExtractionConfigResolver()


# ============================================================
# 请求体定义
# ============================================================
class GlobalConfigRequest(BaseModel):
    """全局配置保存请求体。"""

    enabled: bool = True
    content: dict = Field(default_factory=dict)


class PromptTemplateRequest(BaseModel):
    """Prompt 模板请求体（重构后）。

    - scope=simple：仅使用 system_prompt + user_prompt
    - scope=schema：使用 system_prompt + 按类别存于 KbPromptCategory 的 user_prompt
    """

    name: str
    description: str = ""
    scope: str = "simple"
    system_prompt: str = ""
    user_prompt: str = ""
    schema_template_id: UUID | None = None
    # schema 模式下选中的类别 ID 列表（新建时确定范围）
    category_ids: list[UUID] = Field(default_factory=list)
    is_active: bool = True


class PromptCategoryUpsert(BaseModel):
    """schema 模式下单个类别的 user_prompt 保存项。"""

    category_id: UUID
    user_prompt: str = ""


class PromptSaveRequest(BaseModel):
    """Prompt 模板编辑页保存请求体（编辑内部页使用）。

    支持 simple 的 user_prompt，以及 schema 的按类别 user_prompt 批量保存。
    """

    system_prompt: str = ""
    user_prompt: str = ""
    categories: list[PromptCategoryUpsert] = Field(default_factory=list)
    is_active: bool = True


class RuleUpsert(BaseModel):
    """规则保存项（统一后处理 + 校验规则）。"""

    rule_key: str
    stage: str = "post"
    name: str = ""
    description: str = ""
    enabled: bool = False
    params: dict = Field(default_factory=dict)
    scope: dict = Field(default_factory=lambda: {"type": "global"})
    sort_order: int = 0


class ScriptUpsert(BaseModel):
    """自定义处理脚本保存项。"""

    folder: str = "post"
    name: str
    code: str = ""
    params_schema: list = Field(default_factory=list)
    enabled: bool = True
    sort_order: int = 0
    description: str = ""


class ScriptRunRequest(BaseModel):
    """脚本运行调试请求体。

    - ``script_id``：调试已保存脚本时传入（缺省用 ``code``）。
    - ``code``：待调试的脚本源码（未保存 / 临时内容）。
    - ``args``：本次调用的运行时入参（模拟各目录的 args）。
    - ``params``：脚本自定义参数。
    """

    script_id: str | None = None
    code: str = ""
    args: dict = Field(default_factory=dict)
    params: dict = Field(default_factory=dict)
    timeout: float = 10


class RuleGroupCreateRequest(BaseModel):
    """新建规则组请求体。"""

    name: str | None = None
    schema_template_id: UUID
    description: str = ""


class RuleGroupItemUpsert(BaseModel):
    """规则项保存项（引用脚本 + 阶段 + 顺序）。"""

    id: UUID | None = None
    category_id: UUID
    category_name: str = ""
    script_id: UUID
    stage: str = RULE_STAGE_POST
    sort_order: int = 0


class RuleGroupItemsRequest(BaseModel):
    """某类别规则项批量保存请求体（全量替换该类别规则）。"""

    category_id: UUID
    category_name: str = ""
    items: list[RuleGroupItemUpsert] = Field(default_factory=list)


class ValidationRuleUpsert(BaseModel):
    """验证规则保存项。"""

    rule_key: str
    name: str = ""
    description: str = ""
    enabled: bool = False
    config: dict = Field(default_factory=dict)
    sort_order: int = 0


class TermBindingUpsert(BaseModel):
    """术语绑定保存项。"""

    schema_id: str | None = None
    field_name: str
    term_base_id: str | None = None
    config: dict = Field(default_factory=dict)


class VersionCreateRequest(BaseModel):
    """版本快照创建请求体。"""

    name: str
    description: str = ""


# ============================================================
# 全局配置
# ============================================================
@router.get("")
async def get_full_config(
    kb_ctx: KBContext = Depends(get_kb_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """解析获取当前 KB 的完整抽取配置（供前端载入 / 后端流水线使用）。"""
    cfg = await resolver.resolve(db, kb_ctx.kb_id)
    rules_list = list(cfg.rules.values())
    return success(data={
        "kb_id": cfg.kb_id,
        "config_enabled": cfg.config_enabled,
        "global": cfg.global_config,
        "prompt_templates": cfg.prompt_templates,
        "rules": rules_list,
        "validation_rules": [
            v for v in rules_list if v.get("stage") == "validation"
        ],
        "term_bindings": {f"{k[0]}|{k[1]}": v for k, v in cfg.term_bindings.items()},
        "schema_templates": cfg.schema_templates,
    })


@router.get("/global")
async def get_global(
    kb_ctx: KBContext = Depends(get_kb_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取全局配置（含默认值）。"""
    row = (
        await db.execute(
            select(KbExtractionConfig).where(KbExtractionConfig.kb_id == kb_ctx.kb_id)
        )
    ).scalar_one_or_none()
    if row is None or not row.content:
        return success(data={
            "enabled": row.enabled if row else True,
            "content": get_default_config(),
            "version": row.version if row else 1,
        })
    return success(data={
        "enabled": row.enabled,
        "content": row.content,
        "version": row.version,
    })


@router.put("/global")
async def save_global(
    body: GlobalConfigRequest,
    kb_ctx: KBContext = Depends(require_role(*EDIT_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """保存全局配置（editor+）。"""
    row = (
        await db.execute(
            select(KbExtractionConfig).where(KbExtractionConfig.kb_id == kb_ctx.kb_id)
        )
    ).scalar_one_or_none()
    if row is None:
        row = KbExtractionConfig(kb_id=kb_ctx.kb_id)
        db.add(row)
    row.enabled = body.enabled
    row.content = body.content
    row.version = (row.version or 1) + 1
    await db.commit()
    await db.refresh(row)
    return success(data={
        "enabled": row.enabled,
        "content": row.content,
        "version": row.version,
    })


# ============================================================
# Prompt 模板
# ============================================================
def _serialize_prompt(p: KbPromptTemplate) -> dict:
    """序列化 Prompt 模板（列表 / 详情基础信息）。"""
    return {
        "id": str(p.id),
        "name": p.name,
        "description": p.description or "",
        "scope": p.scope,
        "system_prompt": p.system_prompt or "",
        "user_prompt": p.user_prompt or "",
        "schema_template_id": str(p.schema_template_id) if p.schema_template_id else None,
        "is_active": p.is_active,
    }


async def _get_prompt(db: AsyncSession, prompt_id: UUID, kb_id) -> KbPromptTemplate:
    result = await db.execute(
        select(KbPromptTemplate).where(
            KbPromptTemplate.id == prompt_id,
            KbPromptTemplate.kb_id == kb_id,
        )
    )
    p = result.scalar_one_or_none()
    if p is None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_SCHEMA_NOT_FOUND,
            message=f"Prompt 模板 {prompt_id} 不存在",
        )
    return p


async def _load_prompt_categories(db: AsyncSession, prompt_id: UUID) -> list[dict]:
    """加载 Prompt 模板的类别 user_prompt 列表（含类别名）。"""
    rows = (
        await db.execute(
            select(KbPromptCategory, SchemaConfig)
            .join(SchemaConfig, SchemaConfig.id == KbPromptCategory.category_id)
            .where(KbPromptCategory.prompt_template_id == prompt_id)
            .order_by(KbPromptCategory.sort_order)
        )
    ).all()
    return [
        {
            "category_id": str(pc.category_id),
            "category_name": cfg.name,
            "user_prompt": pc.user_prompt or "",
        }
        for pc, cfg in rows
    ]


@router.get("/prompts")
async def list_prompts(
    kb_ctx: KBContext = Depends(get_kb_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """列出 KB 下的 Prompt 模板。"""
    rows = (
        await db.execute(
            select(KbPromptTemplate)
            .where(KbPromptTemplate.kb_id == kb_ctx.kb_id)
            .order_by(KbPromptTemplate.created_at)
        )
    ).scalars().all()
    return success(data={"items": [_serialize_prompt(p) for p in rows]})


@router.get("/prompts/{prompt_id}")
async def get_prompt(
    prompt_id: UUID,
    kb_ctx: KBContext = Depends(get_kb_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取 Prompt 模板详情（含 schema 模式的类别 user_prompt）。"""
    p = await _get_prompt(db, prompt_id, kb_ctx.kb_id)
    data = _serialize_prompt(p)
    if p.scope == "schema":
        data["categories"] = await _load_prompt_categories(db, prompt_id)
    return success(data=data)


@router.post("/prompts")
async def create_prompt(
    body: PromptTemplateRequest,
    kb_ctx: KBContext = Depends(require_role(*EDIT_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """新建 Prompt 模板（editor+）。

    - scope=simple：可带 user_prompt
    - scope=schema：需带 schema_template_id + category_ids，创建时初始化类别 user_prompt 记录
    """
    if body.scope not in ("simple", "schema"):
        raise BusinessException(
            code=ErrorCode.VALIDATION_ERROR,
            message=f"非法 scope: {body.scope}",
        )
    exists = (
        await db.execute(
            select(KbPromptTemplate).where(
                KbPromptTemplate.kb_id == kb_ctx.kb_id,
                KbPromptTemplate.name == body.name,
            )
        )
    ).scalar_one_or_none()
    if exists:
        raise BusinessException(
            code=ErrorCode.VALIDATION_ERROR,
            message=f"Prompt 模板名 {body.name} 已存在",
        )

    # 校验 schema 模板归属
    if body.scope == "schema":
        if not body.schema_template_id:
            raise BusinessException(
                code=ErrorCode.VALIDATION_ERROR,
                message="scope=schema 时必须选择 Schema 模板",
            )
        tpl = (
            await db.execute(
                select(SchemaTemplate).where(
                    SchemaTemplate.id == body.schema_template_id,
                    SchemaTemplate.kb_id == kb_ctx.kb_id,
                )
            )
        ).scalar_one_or_none()
        if tpl is None:
            raise BusinessException(
                code=ErrorCode.VALIDATION_ERROR,
                message=f"Schema 模板 {body.schema_template_id} 不存在",
            )

    p = KbPromptTemplate(
        kb_id=kb_ctx.kb_id,
        name=body.name,
        description=body.description or None,
        scope=body.scope,
        system_prompt=body.system_prompt,
        user_prompt=body.user_prompt if body.scope == "simple" else "",
        schema_template_id=body.schema_template_id if body.scope == "schema" else None,
        is_active=body.is_active,
    )
    db.add(p)
    await db.flush()

    # schema 模式：为选中的类别创建 user_prompt 记录
    if body.scope == "schema" and body.category_ids:
        cats = (
            await db.execute(
                select(SchemaConfig).where(
                    SchemaConfig.id.in_(body.category_ids),
                    SchemaConfig.kb_id == kb_ctx.kb_id,
                    SchemaConfig.template_id == body.schema_template_id,
                    SchemaConfig.node_type == "category",
                )
            )
        ).scalars().all()
        for idx, cat in enumerate(cats):
            db.add(
                KbPromptCategory(
                    kb_id=kb_ctx.kb_id,
                    prompt_template_id=p.id,
                    category_id=cat.id,
                    user_prompt="",
                    sort_order=idx,
                )
            )

    await db.commit()
    await db.refresh(p)
    return success(data={"id": str(p.id)})


@router.put("/prompts/{prompt_id}")
async def update_prompt(
    prompt_id: UUID,
    body: PromptTemplateRequest,
    kb_ctx: KBContext = Depends(require_role(*EDIT_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """更新 Prompt 模板基础信息（editor+）。"""
    p = await _get_prompt(db, prompt_id, kb_ctx.kb_id)
    if body.scope not in ("simple", "schema"):
        raise BusinessException(
            code=ErrorCode.VALIDATION_ERROR,
            message=f"非法 scope: {body.scope}",
        )
    p.name = body.name
    p.description = body.description or None
    p.scope = body.scope
    p.system_prompt = body.system_prompt
    p.user_prompt = body.user_prompt if body.scope == "simple" else ""
    p.schema_template_id = body.schema_template_id if body.scope == "schema" else None
    p.is_active = body.is_active
    await db.commit()
    return success(message="已更新")


@router.put("/prompts/{prompt_id}/save")
async def save_prompt(
    prompt_id: UUID,
    body: PromptSaveRequest,
    kb_ctx: KBContext = Depends(require_role(*EDIT_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """保存 Prompt 模板编辑内容（editor+）。

    更新 system_prompt；simple 模式更新 user_prompt；
    schema 模式按类别批量更新 user_prompt。
    """
    p = await _get_prompt(db, prompt_id, kb_ctx.kb_id)
    p.system_prompt = body.system_prompt
    p.is_active = body.is_active

    if p.scope == "simple":
        p.user_prompt = body.user_prompt
    else:
        # schema 模式：按 category_id 更新已存在的类别 prompt
        if body.categories:
            existing = (
                await db.execute(
                    select(KbPromptCategory).where(
                        KbPromptCategory.prompt_template_id == prompt_id,
                        KbPromptCategory.kb_id == kb_ctx.kb_id,
                    )
                )
            ).scalars().all()
            by_cat = {pc.category_id: pc for pc in existing}
            for item in body.categories:
                pc = by_cat.get(item.category_id)
                if pc is not None:
                    pc.user_prompt = item.user_prompt

    await db.commit()
    return success(message="已保存")


@router.delete("/prompts/{prompt_id}")
async def delete_prompt(
    prompt_id: UUID,
    kb_ctx: KBContext = Depends(require_role(*EDIT_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """删除 Prompt 模板（editor+，级联删除类别子记录）。"""
    p = await _get_prompt(db, prompt_id, kb_ctx.kb_id)
    await db.delete(p)
    await db.commit()
    return success(message="已删除")


# ============================================================
# 抽取规则
# ============================================================
@router.get("/rules/registry")
async def list_rule_registry(
    kb_ctx: KBContext = Depends(get_kb_context),
) -> dict:
    """内置规则注册表 + 参数 schema（驱动前端动态渲染规则表单）。"""
    return success(data={
        "stages": {
            stage: list(rules.keys())
            for stage, rules in RULE_REGISTRY.items()
        },
        "rules": {
            rule_key: {
                "rule_key": rule_key,
                "stage": spec.get("stage"),
                "name": spec.get("name"),
                "description": spec.get("description"),
                "enabled_default": spec.get("enabled_default"),
                "sort_order": spec.get("sort_order"),
                "params_schema": spec.get("params_schema", []),
                "default_params": spec.get("default_params", {}),
            }
            for rules in RULE_REGISTRY.values()
            for rule_key, spec in rules.items()
        },
    })


@router.get("/rules")
async def list_rules(
    kb_ctx: KBContext = Depends(get_kb_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """列出 KB 下的规则（统一后处理 + 校验）。"""
    rows = (
        await db.execute(
            select(KbRule)
            .where(KbRule.kb_id == kb_ctx.kb_id)
            .order_by(KbRule.stage, KbRule.sort_order, KbRule.rule_key)
        )
    ).scalars().all()
    data = [{
        "id": str(r.id),
        "rule_key": r.rule_key,
        "stage": r.stage,
        "name": r.name,
        "description": r.description or "",
        "enabled": r.enabled,
        "params": r.params or {},
        "scope": r.scope or {"type": "global"},
        "sort_order": r.sort_order,
    } for r in rows]
    return success(data={"items": data})


@router.put("/rules")
async def save_rules(
    items: list[RuleUpsert],
    kb_ctx: KBContext = Depends(require_role(*EDIT_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """批量保存规则（新增/更新，editor+）。"""
    for item in items:
        scope = item.scope or {"type": "global"}
        row = (
            await db.execute(
                select(KbRule).where(
                    KbRule.kb_id == kb_ctx.kb_id,
                    KbRule.stage == item.stage,
                    KbRule.rule_key == item.rule_key,
                    KbRule.scope == scope,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            row = KbRule(
                kb_id=kb_ctx.kb_id,
                stage=item.stage,
                rule_key=item.rule_key,
                name=item.name or item.rule_key,
                scope=scope,
            )
            db.add(row)
        row.stage = item.stage
        row.name = item.name or item.rule_key
        row.description = item.description
        row.enabled = item.enabled
        row.params = item.params
        row.scope = scope
        row.sort_order = item.sort_order
    await db.commit()
    return success(message="已保存")


# ============================================================
# 自定义处理脚本（类似 magic-api 脚本即函数）
# ============================================================
@router.get("/scripts/io")
async def get_script_io(
    kb_ctx: KBContext = Depends(get_kb_context),
) -> dict:
    """返回各目录（pre/post/validation）的入参 / 出参契约，驱动前端右侧面板。"""
    return success(data={"folders": SCRIPT_IO_REGISTRY})


@router.get("/scripts")
async def list_scripts(
    folder: str | None = None,
    kb_ctx: KBContext = Depends(get_kb_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """列出 KB 下的自定义脚本（可按目录过滤）。"""
    stmt = (
        select(KbScript)
        .where(KbScript.kb_id == kb_ctx.kb_id)
        .order_by(KbScript.folder, KbScript.sort_order, KbScript.created_at)
    )
    if folder:
        if folder not in SCRIPT_FOLDERS:
            raise BusinessException(code=ErrorCode.BUSINESS_SCHEMA_NOT_FOUND, message=f"无效目录: {folder}")
        stmt = stmt.where(KbScript.folder == folder)
    rows = (await db.execute(stmt)).scalars().all()
    data = [{
        "id": str(s.id),
        "folder": s.folder,
        "name": s.name,
        "code": s.code,
        "params_schema": s.params_schema or [],
        "enabled": s.enabled,
        "sort_order": s.sort_order,
        "description": s.description or "",
        "updated_at": s.updated_at.isoformat() if s.updated_at else "",
    } for s in rows]
    return success(data={"items": data})


@router.post("/scripts")
async def create_script(
    body: ScriptUpsert,
    kb_ctx: KBContext = Depends(require_role(*EDIT_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """新建自定义脚本（editor+）。"""
    if body.folder not in SCRIPT_FOLDERS:
        raise BusinessException(code=ErrorCode.BUSINESS_SCHEMA_NOT_FOUND, message=f"无效目录: {body.folder}")
    if not body.name.strip():
        raise BusinessException(code=ErrorCode.BUSINESS_SCHEMA_NOT_FOUND, message="脚本名称不能为空")
    script = KbScript(
        kb_id=kb_ctx.kb_id,
        folder=body.folder,
        name=body.name.strip(),
        code=body.code,
        params_schema=body.params_schema,
        enabled=body.enabled,
        sort_order=body.sort_order,
        description=body.description,
    )
    db.add(script)
    await db.commit()
    await db.refresh(script)
    return success(data={"id": str(script.id)})


@router.put("/scripts/{script_id}")
async def update_script(
    script_id: UUID,
    body: ScriptUpsert,
    kb_ctx: KBContext = Depends(require_role(*EDIT_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """更新自定义脚本（editor+）。"""
    script = await _get_script(db, script_id, kb_ctx.kb_id)
    if body.folder not in SCRIPT_FOLDERS:
        raise BusinessException(code=ErrorCode.BUSINESS_SCHEMA_NOT_FOUND, message=f"无效目录: {body.folder}")
    script.folder = body.folder
    script.name = body.name.strip() or script.name
    script.code = body.code
    script.params_schema = body.params_schema
    script.enabled = body.enabled
    script.sort_order = body.sort_order
    script.description = body.description
    await db.commit()
    return success(message="已保存")


@router.delete("/scripts/{script_id}")
async def delete_script(
    script_id: UUID,
    kb_ctx: KBContext = Depends(require_role(*EDIT_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """删除自定义脚本（editor+）。"""
    script = await _get_script(db, script_id, kb_ctx.kb_id)
    await db.delete(script)
    await db.commit()
    return success(message="已删除")


@router.post("/scripts/run")
async def run_script_endpoint(
    body: ScriptRunRequest,
    kb_ctx: KBContext = Depends(get_kb_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """脚本运行 / 调试（任意成员可执行，用于配置中心试运行）。"""
    code = body.code
    if body.script_id:
        script = await _get_script(db, UUID(body.script_id), kb_ctx.kb_id)
        code = script.code or ""
    if not code.strip():
        raise BusinessException(code=ErrorCode.BUSINESS_SCHEMA_NOT_FOUND, message="脚本为空")
    # 注入 kb_tools 工具句柄（含 db，调试时可访问术语集；无 target 时后处理类工具不可用）
    inject = {"kb_tools": KbScriptTools(kb_id=str(kb_ctx.kb_id), db=db)}
    try:
        result = await execute_script(
            code, body.args or {}, body.params or {}, timeout=body.timeout,
            inject=inject,
        )
    except Exception as err:  # noqa: BLE001
        return success(data={"ok": False, "error": str(err)})
    return success(data={"ok": True, "result": result})


# ============================================================
# 规则组（按 Schema 模板分组管理后处理 / 校验脚本规则）
# ============================================================
async def _get_rule_group(db: AsyncSession, group_id: UUID, kb_id) -> KbRuleGroup:
    result = await db.execute(
        select(KbRuleGroup).where(
            KbRuleGroup.id == group_id, KbRuleGroup.kb_id == kb_id
        )
    )
    group = result.scalar_one_or_none()
    if group is None:
        raise BusinessException(code=ErrorCode.BUSINESS_SCHEMA_NOT_FOUND, message="规则组不存在")
    return group


@router.get("/rule-groups")
async def list_rule_groups(
    kb_ctx: KBContext = Depends(get_kb_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """列出 KB 下的规则组（含模板名、类别数）。"""
    groups = (
        await db.execute(
            select(KbRuleGroup)
            .where(KbRuleGroup.kb_id == kb_ctx.kb_id)
            .order_by(KbRuleGroup.created_at)
        )
    ).scalars().all()
    # 类别数统计：按模板统计 category 节点数 + 规则项数
    tpl_ids = [g.schema_template_id for g in groups]
    cat_counts: dict[str, int] = {}
    if tpl_ids:
        cat_rows = await db.execute(
            select(SchemaConfig.template_id, func.count())
            .where(
                SchemaConfig.template_id.in_(tpl_ids),
                SchemaConfig.node_type == "category",
            )
            .group_by(SchemaConfig.template_id)
        )
        cat_counts = {str(t): c for t, c in cat_rows.all()}
    item_counts: dict[str, int] = {}
    if groups:
        item_rows = await db.execute(
            select(KbRuleGroupItem.rule_group_id, func.count())
            .where(KbRuleGroupItem.rule_group_id.in_([g.id for g in groups]))
            .group_by(KbRuleGroupItem.rule_group_id)
        )
        item_counts = {str(g): c for g, c in item_rows.all()}
    data = []
    for g in groups:
        tpl = await db.get(SchemaTemplate, g.schema_template_id)
        data.append({
            "id": str(g.id),
            "name": g.name or (tpl.name if tpl else ""),
            "schema_template_id": str(g.schema_template_id),
            "schema_template_name": tpl.name if tpl else "",
            "description": g.description or "",
            "category_count": cat_counts.get(str(g.schema_template_id), 0),
            "item_count": item_counts.get(str(g.id), 0),
        })
    return success(data={"items": data})


@router.post("/rule-groups")
async def create_rule_group(
    body: RuleGroupCreateRequest,
    kb_ctx: KBContext = Depends(require_role(*EDIT_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """新建规则组（editor+）。"""
    tpl = await db.get(SchemaTemplate, body.schema_template_id)
    if tpl is None or tpl.kb_id != kb_ctx.kb_id:
        raise BusinessException(code=ErrorCode.BUSINESS_SCHEMA_NOT_FOUND, message="Schema 模板不存在")
    exists = (
        await db.execute(
            select(KbRuleGroup).where(
                KbRuleGroup.kb_id == kb_ctx.kb_id,
                KbRuleGroup.schema_template_id == body.schema_template_id,
            )
        )
    ).scalar_one_or_none()
    if exists is not None:
        raise BusinessException(code=ErrorCode.BUSINESS_SCHEMA_NOT_FOUND, message="该模板已存在规则组")
    group = KbRuleGroup(
        kb_id=kb_ctx.kb_id,
        name=(body.name or "").strip() or tpl.name,
        schema_template_id=body.schema_template_id,
        description=body.description,
    )
    db.add(group)
    await db.commit()
    await db.refresh(group)
    return success(data={"id": str(group.id)})


@router.get("/rule-groups/{group_id}")
async def get_rule_group(
    group_id: UUID,
    kb_ctx: KBContext = Depends(get_kb_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """规则组详情：模板下所有类别 + 每类别的规则项（含脚本名/描述/阶段）。"""
    group = await _get_rule_group(db, group_id, kb_ctx.kb_id)
    tpl = await db.get(SchemaTemplate, group.schema_template_id)
    # 模板下所有类别
    cats = (
        await db.execute(
            select(SchemaConfig)
            .where(
                SchemaConfig.template_id == group.schema_template_id,
                SchemaConfig.node_type == "category",
            )
            .order_by(SchemaConfig.sort_order, SchemaConfig.created_at)
        )
    ).scalars().all()
    # 该规则组全部规则项
    items = (
        await db.execute(
            select(KbRuleGroupItem)
            .where(KbRuleGroupItem.rule_group_id == group.id)
            .order_by(KbRuleGroupItem.sort_order, KbRuleGroupItem.created_at)
        )
    ).scalars().all()
    script_map: dict[str, KbScript] = {}
    if items:
        scripts = (
            await db.execute(
                select(KbScript).where(KbScript.kb_id == kb_ctx.kb_id)
            )
        ).scalars().all()
        script_map = {str(s.id): s for s in scripts}
    # 批量解析 term_base 来源类别名称（name 为空时回退术语集名称）
    term_base_ids = {
        c.name_term_base_id
        for c in cats
        if c.name_source == "term_base" and not (c.name or "").strip() and c.name_term_base_id
    }
    term_names: dict[str, str] = {}
    if term_base_ids:
        term_rows = (
            await db.execute(
                select(TermBase.id, TermBase.name).where(
                    TermBase.kb_id == kb_ctx.kb_id,
                    TermBase.id.in_(list(term_base_ids)),
                )
            )
        ).all()
        term_names = {str(t): n for t, n in term_rows}

    categories = []
    for c in cats:
        cat_items = [
            it for it in items if it.category_id == c.id
        ] if items else []
        rules = []
        for it in cat_items:
            sc = script_map.get(str(it.script_id))
            rules.append({
                "id": str(it.id),
                "category_id": str(it.category_id),
                "category_name": it.category_name,
                "script_id": str(it.script_id),
                "script_name": sc.name if sc else "",
                "script_description": sc.description if sc else "",
                "stage": it.stage,
                "sort_order": it.sort_order,
            })
        cat_name = c.name or ""
        if not cat_name.strip() and c.name_source == "term_base":
            cat_name = term_names.get(str(c.name_term_base_id)) or cat_name
        categories.append({
            "id": str(c.id),
            "name": cat_name,
            "rules": rules,
        })
    return success(data={
        "id": str(group.id),
        "name": group.name or (tpl.name if tpl else ""),
        "schema_template_id": str(group.schema_template_id),
        "schema_template_name": tpl.name if tpl else "",
        "description": group.description or "",
        "categories": categories,
    })


@router.put("/rule-groups/{group_id}/items")
async def save_rule_group_items(
    group_id: UUID,
    body: RuleGroupItemsRequest,
    kb_ctx: KBContext = Depends(require_role(*EDIT_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """全量替换某类别的规则项（editor+），按 sort_order 持久化。"""
    group = await _get_rule_group(db, group_id, kb_ctx.kb_id)
    # 校验 script 存在且属于本 KB
    script_ids = [it.script_id for it in body.items]
    if script_ids:
        scripts = (
            await db.execute(
                select(KbScript.id).where(
                    KbScript.kb_id == kb_ctx.kb_id,
                    KbScript.id.in_(script_ids),
                )
            )
        ).scalars().all()
        if len(scripts) != len(set(script_ids)):
            raise BusinessException(code=ErrorCode.BUSINESS_SCHEMA_NOT_FOUND, message="脚本不存在")
    # 删除该类别现有规则项
    old_rows = (
        await db.execute(
            select(KbRuleGroupItem).where(
                KbRuleGroupItem.rule_group_id == group.id,
                KbRuleGroupItem.category_id == body.category_id,
            )
        )
    ).scalars().all()
    for r in old_rows:
        await db.delete(r)
    # 立即提交删除，避免与下方新增项（相同 rule_group_id+category_id+script_id+stage）
    # 在唯一约束上冲突（ORM delete 默认延迟到最终 flush，两者会同时落库）
    await db.flush()
    cat_name = body.category_name
    for idx, it in enumerate(body.items):
        db.add(KbRuleGroupItem(
            kb_id=kb_ctx.kb_id,
            rule_group_id=group.id,
            category_id=it.category_id,
            category_name=it.category_name or cat_name,
            script_id=it.script_id,
            stage=it.stage,
            sort_order=it.sort_order if it.sort_order else idx,
        ))
    await db.commit()
    return success(message="已保存")


@router.delete("/rule-groups/{group_id}")
async def delete_rule_group(
    group_id: UUID,
    kb_ctx: KBContext = Depends(require_role(*EDIT_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """删除规则组（级联删规则项，editor+）。"""
    group = await _get_rule_group(db, group_id, kb_ctx.kb_id)
    await db.delete(group)
    await db.commit()
    return success(message="已删除")


async def _get_script(db: AsyncSession, script_id: UUID, kb_id) -> KbScript:
    result = await db.execute(
        select(KbScript).where(KbScript.id == script_id, KbScript.kb_id == kb_id)
    )
    script = result.scalar_one_or_none()
    if script is None:
        raise BusinessException(code=ErrorCode.BUSINESS_SCHEMA_NOT_FOUND, message="脚本不存在")
    return script


# ============================================================
# 验证规则（兼容入口，操作 kb_rules 的 validation 阶段）
# ============================================================
@router.get("/validation")
async def list_validation(
    kb_ctx: KBContext = Depends(get_kb_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """列出 KB 下的验证规则（stage=validation）。"""
    rows = (
        await db.execute(
            select(KbRule)
            .where(KbRule.kb_id == kb_ctx.kb_id, KbRule.stage == "validation")
            .order_by(KbRule.sort_order, KbRule.rule_key)
        )
    ).scalars().all()
    data = [{
        "id": str(r.id),
        "rule_key": r.rule_key,
        "name": r.name,
        "description": r.description or "",
        "enabled": r.enabled,
        "config": r.params or {},
        "scope": r.scope or {"type": "global"},
        "sort_order": r.sort_order,
    } for r in rows]
    return success(data={"items": data})


@router.put("/validation")
async def save_validation(
    items: list[ValidationRuleUpsert],
    kb_ctx: KBContext = Depends(require_role(*EDIT_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """批量保存验证规则（stage=validation，兼容旧接口）。"""
    for item in items:
        scope = getattr(item, "scope", None) or {"type": "global"}
        row = (
            await db.execute(
                select(KbRule).where(
                    KbRule.kb_id == kb_ctx.kb_id,
                    KbRule.stage == "validation",
                    KbRule.rule_key == item.rule_key,
                    KbRule.scope == scope,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            row = KbRule(
                kb_id=kb_ctx.kb_id,
                stage="validation",
                rule_key=item.rule_key,
                name=item.name or item.rule_key,
                scope=scope,
            )
            db.add(row)
        row.name = item.name or item.rule_key
        row.description = item.description
        row.enabled = item.enabled
        row.params = item.config
        row.scope = scope
        row.sort_order = item.sort_order
    await db.commit()
    return success(message="已保存")


# ============================================================
# 术语绑定
# ============================================================
@router.get("/bindings")
async def list_bindings(
    kb_ctx: KBContext = Depends(get_kb_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """列出 KB 下的术语绑定。"""
    rows = (
        await db.execute(
            select(KbTermBinding).where(KbTermBinding.kb_id == kb_ctx.kb_id)
        )
    ).scalars().all()
    data = [{
        "id": str(b.id),
        "schema_id": str(b.schema_id) if b.schema_id else None,
        "field_name": b.field_name,
        "term_base_id": str(b.term_base_id) if b.term_base_id else None,
        "config": b.config or {},
    } for b in rows]
    return success(data={"items": data})


@router.put("/bindings")
async def save_bindings(
    items: list[TermBindingUpsert],
    kb_ctx: KBContext = Depends(require_role(*EDIT_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """批量保存术语绑定（新增/更新，editor+）。"""
    for item in items:
        schema_id = UUID(item.schema_id) if item.schema_id else None
        row = (
            await db.execute(
                select(KbTermBinding).where(
                    KbTermBinding.kb_id == kb_ctx.kb_id,
                    KbTermBinding.schema_id == schema_id,
                    KbTermBinding.field_name == item.field_name,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            row = KbTermBinding(
                kb_id=kb_ctx.kb_id,
                schema_id=schema_id,
                field_name=item.field_name,
            )
            db.add(row)
        row.schema_id = schema_id
        row.field_name = item.field_name
        row.term_base_id = UUID(item.term_base_id) if item.term_base_id else None
        row.config = item.config
    await db.commit()
    return success(message="已保存")


# ============================================================
# 版本管理
# ============================================================
@router.get("/versions")
async def list_versions(
    kb_ctx: KBContext = Depends(get_kb_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """列出 KB 下的版本快照。"""
    rows = (
        await db.execute(
            select(KbDomainConfigVersion)
            .where(KbDomainConfigVersion.kb_id == kb_ctx.kb_id)
            .order_by(KbDomainConfigVersion.version.desc())
        )
    ).scalars().all()
    data = [{
        "id": str(v.id),
        "version": v.version,
        "name": v.name,
        "description": v.description or "",
        "created_at": v.created_at.isoformat() if v.created_at else "",
        "created_by": str(v.created_by) if v.created_by else None,
    } for v in rows]
    return success(data={"items": data})


@router.post("/versions")
async def create_version(
    body: VersionCreateRequest,
    kb_ctx: KBContext = Depends(require_role(*EDIT_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """创建当前配置的全量快照（editor+）。

    快照使用 ``export_snapshot`` 完整导出 8 类配置（全局 / 脚本 / 数据集 /
    Schema 模板 / 术语绑定 / Prompt 模板 / 规则 / 规则组），支持全量回滚。
    """
    max_ver = (
        await db.execute(
            select(func.max(KbDomainConfigVersion.version)).where(
                KbDomainConfigVersion.kb_id == kb_ctx.kb_id
            )
        )
    ).scalar_one()
    snapshot = await export_snapshot(db, kb_ctx.kb_id)
    v = KbDomainConfigVersion(
        kb_id=kb_ctx.kb_id,
        version=(max_ver or 0) + 1,
        name=body.name,
        description=body.description or None,
        snapshot=snapshot,
        created_by=kb_ctx.user.id,
    )
    db.add(v)
    await db.commit()
    await db.refresh(v)
    return success(data={"id": str(v.id), "version": v.version})


@router.post("/versions/{version_id}/rollback")
async def rollback_version(
    version_id: UUID,
    kb_ctx: KBContext = Depends(require_role(*EDIT_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """回滚抽取配置到指定版本（editor+）。

    全量恢复快照中的 8 类配置（全局 / 脚本 / 数据集 / Schema 模板 / 术语绑定 /
    Prompt 模板 / 规则 / 规则组），当前配置将被覆盖为该版本保存时的状态。
    """
    v = (
        await db.execute(
            select(KbDomainConfigVersion).where(
                KbDomainConfigVersion.id == version_id,
                KbDomainConfigVersion.kb_id == kb_ctx.kb_id,
            )
        )
    ).scalar_one_or_none()
    if v is None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_SCHEMA_NOT_FOUND,
            message=f"版本 {version_id} 不存在",
        )
    await import_snapshot(db, kb_ctx.kb_id, v.snapshot or {})
    await db.commit()
    return success(message="已回滚")


def _snapshot_summary(snap: dict) -> dict:
    """将快照折叠为轻量摘要，供详情页展示各配置域的内容。"""
    return {
        "global": snap.get("global") or {},
        "scripts": [s.get("name") for s in (snap.get("scripts") or [])],
        "datasets": [d.get("name") for d in (snap.get("datasets") or [])],
        "schema_templates": [
            {"name": t.get("name"), "categories": len(t.get("configs") or [])}
            for t in (snap.get("schema_templates") or [])
        ],
        "term_bindings": len(snap.get("term_bindings") or []),
        "prompt_templates": [
            {"name": p.get("name"), "scope": p.get("scope")}
            for p in (snap.get("prompt_templates") or [])
        ],
        "rules": [r.get("name") for r in (snap.get("rules") or [])],
        "rule_groups": [
            {"name": g.get("name") or "未命名规则组", "items": len(g.get("items") or [])}
            for g in (snap.get("rule_groups") or [])
        ],
    }


@router.get("/versions/{version_id}")
async def get_version_detail(
    version_id: UUID,
    kb_ctx: KBContext = Depends(get_kb_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """查看指定版本快照的详情（任意成员）。"""
    v = (
        await db.execute(
            select(KbDomainConfigVersion).where(
                KbDomainConfigVersion.id == version_id,
                KbDomainConfigVersion.kb_id == kb_ctx.kb_id,
            )
        )
    ).scalar_one_or_none()
    if v is None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_SCHEMA_NOT_FOUND,
            message=f"版本 {version_id} 不存在",
        )
    return success(data={
        "id": str(v.id),
        "version": v.version,
        "name": v.name,
        "description": v.description or "",
        "created_at": v.created_at.isoformat() if v.created_at else "",
        "created_by": str(v.created_by) if v.created_by else None,
        "summary": _snapshot_summary(v.snapshot or {}),
    })


@router.get("/versions/{version_id}/diff")
async def diff_version(
    version_id: UUID,
    kb_ctx: KBContext = Depends(get_kb_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """对比当前配置与指定版本快照，返回差异清单（任意成员，供对比与回滚预警）。"""
    v = (
        await db.execute(
            select(KbDomainConfigVersion).where(
                KbDomainConfigVersion.id == version_id,
                KbDomainConfigVersion.kb_id == kb_ctx.kb_id,
            )
        )
    ).scalar_one_or_none()
    if v is None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_SCHEMA_NOT_FOUND,
            message=f"版本 {version_id} 不存在",
        )
    current = await export_snapshot(db, kb_ctx.kb_id)
    diff = diff_snapshots(current, v.snapshot or {})
    return success(data={
        "version": v.version,
        "name": v.name,
        "diff": diff,
    })


@router.delete("/versions/{version_id}")
async def delete_version(
    version_id: UUID,
    kb_ctx: KBContext = Depends(require_role(*EDIT_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """删除指定版本快照（editor+）。"""
    v = (
        await db.execute(
            select(KbDomainConfigVersion).where(
                KbDomainConfigVersion.id == version_id,
                KbDomainConfigVersion.kb_id == kb_ctx.kb_id,
            )
        )
    ).scalar_one_or_none()
    if v is None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_SCHEMA_NOT_FOUND,
            message=f"版本 {version_id} 不存在",
        )
    await db.delete(v)
    await db.commit()
    return success(message="已删除")