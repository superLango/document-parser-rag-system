"""知识库配置中心端点模块（方案 §7 / §10.2）。

提供知识库配置的全流程管理接口，所有端点通过 ``get_kb_context`` /
``require_role`` 守卫，强制知识库隔离与 RBAC 权限校验。

端点清单：
- 配置读取/更新
    GET    /kbs/{kb_id}/config                     获取完整配置
    GET    /kbs/{kb_id}/config/{section}           获取某节配置
    PUT    /kbs/{kb_id}/config                     更新 config（深合并）
    PUT    /kbs/{kb_id}/config/{section}           更新某节配置

- 领域模板
    GET    /templates                              内置模板列表
    GET    /templates/{code}                       模板详情
    POST   /kbs/{kb_id}/apply-template             应用模板到 KB

- Hook 管理
    GET    /kbs/{kb_id}/hook                       Hook 信息
    GET    /kbs/{kb_id}/hook/content               读取 Hook 脚本
    PUT    /kbs/{kb_id}/hook/content               更新 Hook 脚本
    POST   /kbs/{kb_id}/hook/reload                重载 Hook
    DELETE /kbs/{kb_id}/hook                       删除 Hook

- 领域配置表查询
    GET    /kbs/{kb_id}/domain/categories          类别列表
    POST   /kbs/{kb_id}/domain/categories          新增类别
    PUT    /kbs/{kb_id}/domain/categories/{cat_id} 更新类别
    DELETE /kbs/{kb_id}/domain/categories/{cat_id} 删除类别
    GET    /kbs/{kb_id}/domain/regex-rules         正则规则列表
    GET    /kbs/{kb_id}/domain/field-templates     字段模板列表
    GET    /kbs/{kb_id}/domain/dict-config         字典配置

- 校验与诊断
    POST   /kbs/{kb_id}/config/validate            校验配置完整性
    GET    /kbs/{kb_id}/resources/verify           物理资源诊断

权限约定：
- 读取（GET）：所有成员（viewer+）
- 修改（PUT/POST/DELETE）：owner/admin（MANAGE_ROLES）
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Path
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import KBContext, get_kb_context, require_role
from app.core.database import get_db
from app.core.exceptions import BusinessException, ErrorCode
from app.core.logging import get_logger
from app.core.response import success
from app.models.kb_domain_config import (
    KbCategory,
    KbCategoryEnum,
    KbDictConfig,
    KbFieldTemplate,
    KbRegexRule,
)
from app.models.knowledge_base import MANAGE_ROLES
from app.schemas.kb_config import (
    ApplyTemplateRequest,
    ApplyTemplateResult,
    KbCategoryCreate,
    KbCategoryUpdate,
    KbConfigResponse,
    KbConfigSectionUpdate,
    KbConfigUpdate,
    KbConfigValidationResult,
    KbHookContent,
    KbHookInfo,
    KbHookReloadResult,
    KbHookUpdate,
    KbResourceVerifyResult,
)
from app.services.kb.domain_template_service import (
    get_template_detail,
    init_kb_from_template,
    list_available_templates,
)
from app.services.kb.kb_config_loader import kb_config_loader
from app.services.kb.kb_lifecycle import kb_lifecycle

logger = get_logger(__name__)

# 合法的 config 节名
_VALID_SECTIONS = frozenset({"ocr", "vector", "extraction", "qa", "dict"})

router = APIRouter(prefix="/kbs", tags=["知识库配置中心"])


# ============================================================
# 全局：领域模板列表（无 kb 上下文，仅需登录）
# ============================================================
from app.api.deps import get_current_active_user  # noqa: E402


@router.get("/templates", response_model_exclude_none=True)
async def list_templates(
    _current_user=Depends(get_current_active_user),
) -> dict:
    """获取全部内置领域模板列表。

    公开接口（仅需登录），供新建知识库向导选择模板。
    """
    templates = list_available_templates()
    return success(data={"items": templates, "total": len(templates)})


@router.get("/templates/{code}", response_model_exclude_none=True)
async def get_template(
    code: str,
    _current_user=Depends(get_current_active_user),
) -> dict:
    """获取指定领域模板详情。"""
    detail = get_template_detail(code)
    if detail is None:
        raise BusinessException(
            code=ErrorCode.VALIDATION_ERROR,
            message=f"领域模板 '{code}' 不存在",
        )
    return success(data=detail)


# ============================================================
# 配置读取/更新
# ============================================================
@router.get("/{kb_id}/config", response_model_exclude_none=True)
async def get_kb_config(
    kb_ctx: KBContext = Depends(get_kb_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取知识库完整配置（合并后的 KBConfig）。"""
    cfg = await kb_config_loader.load(kb_ctx.kb_id, db, kb=kb_ctx.kb)
    resp = KbConfigResponse(
        kb_id=cfg.kb_id,
        config=cfg.config,
        categories=cfg.categories,
        field_templates=cfg.field_templates,
        regex_rules=cfg.regex_rules,
        dict_config=cfg.dict_config,
        template_code=kb_ctx.kb.template_code,
    )
    return success(data=resp.model_dump())


@router.get("/{kb_id}/config/{section}", response_model_exclude_none=True)
async def get_kb_config_section(
    section: str,
    kb_ctx: KBContext = Depends(get_kb_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取知识库某节配置（ocr/vector/extraction/qa/dict）。"""
    if section not in _VALID_SECTIONS:
        raise BusinessException(
            code=ErrorCode.VALIDATION_ERROR,
            message=f"非法配置节 '{section}'，合法值: {sorted(_VALID_SECTIONS)}",
        )
    cfg = await kb_config_loader.load(kb_ctx.kb_id, db, kb=kb_ctx.kb)
    section_data = cfg.config.get(section, {})
    return success(data={"section": section, "config": section_data})


@router.put("/{kb_id}/config", response_model_exclude_none=True)
async def update_kb_config(
    payload: KbConfigUpdate,
    kb_ctx: KBContext = Depends(require_role(*MANAGE_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """更新知识库 config（深合并到现有 config）。"""
    if not payload.config:
        raise BusinessException(
            code=ErrorCode.VALIDATION_ERROR,
            message="config 不能为空",
        )
    # 深合并
    existing = kb_ctx.kb.config if isinstance(kb_ctx.kb.config, dict) else {}
    merged = _deep_merge_dicts(existing, payload.config)
    kb_ctx.kb.config = merged
    await db.commit()
    await db.refresh(kb_ctx.kb)

    logger.info(
        "KB config 已更新",
        kb_id=str(kb_ctx.kb_id),
        user_id=str(kb_ctx.user.id),
        keys=list(payload.config.keys()),
    )
    return success(data={"config": merged}, message="配置已更新")


@router.put("/{kb_id}/config/{section}", response_model_exclude_none=True)
async def update_kb_config_section(
    section: str,
    payload: KbConfigSectionUpdate,
    kb_ctx: KBContext = Depends(require_role(*MANAGE_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """更新知识库某节配置。"""
    if section not in _VALID_SECTIONS:
        raise BusinessException(
            code=ErrorCode.VALIDATION_ERROR,
            message=f"非法配置节 '{section}'，合法值: {sorted(_VALID_SECTIONS)}",
        )
    existing = kb_ctx.kb.config if isinstance(kb_ctx.kb.config, dict) else {}
    if section not in existing or not isinstance(existing.get(section), dict):
        existing[section] = {}
    existing[section] = _deep_merge_dicts(existing[section], payload.section)
    kb_ctx.kb.config = existing
    await db.commit()
    await db.refresh(kb_ctx.kb)

    logger.info(
        "KB config 节已更新",
        kb_id=str(kb_ctx.kb_id),
        section=section,
        user_id=str(kb_ctx.user.id),
    )
    return success(data={"section": section, "config": existing[section]}, message="配置节已更新")


# ============================================================
# 领域模板应用
# ============================================================
@router.post("/{kb_id}/apply-template", response_model_exclude_none=True)
async def apply_template(
    payload: ApplyTemplateRequest,
    kb_ctx: KBContext = Depends(require_role(*MANAGE_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """应用领域模板到知识库（覆盖现有领域配置）。

    幂等操作：先清理旧领域配置，再从模板写入。
    """
    result = await init_kb_from_template(kb_ctx.kb_id, payload.template_code, db)
    # 更新 KB 的 template_code 字段
    kb_ctx.kb.template_code = payload.template_code
    await db.commit()

    logger.info(
        "领域模板已应用到 KB",
        kb_id=str(kb_ctx.kb_id),
        template_code=payload.template_code,
        user_id=str(kb_ctx.user.id),
    )
    resp = ApplyTemplateResult(**result)
    return success(data=resp.model_dump(), message="模板应用成功")


# ============================================================
# Hook 管理
# ============================================================
@router.get("/{kb_id}/hook", response_model_exclude_none=True)
async def get_hook_info(
    kb_ctx: KBContext = Depends(get_kb_context),
) -> dict:
    """获取 Hook 脚本信息。"""
    from app.kb_hooks.registry import get_kb_hook_info

    info = get_kb_hook_info(kb_ctx.kb_id)
    resp = KbHookInfo(
        kb_id=info["kb_id"],
        has_hook=info["has_hook"],
        path=info["path"],
        overridden_interfaces=info.get("overridden_interfaces", []),
        size=info.get("size"),
        mtime=info.get("mtime"),
    )
    return success(data=resp.model_dump())


@router.get("/{kb_id}/hook/content", response_model_exclude_none=True)
async def get_hook_content(
    kb_ctx: KBContext = Depends(get_kb_context),
) -> dict:
    """读取 Hook 脚本内容。"""
    from pathlib import Path

    from app.kb_hooks.registry import _kb_hook_file, get_kb_hook_info

    info = get_kb_hook_info(kb_ctx.kb_id)
    content = ""
    if info["has_hook"]:
        hook_file: Path = _kb_hook_file(kb_ctx.kb_id)
        try:
            content = hook_file.read_text(encoding="utf-8")
        except OSError as err:
            logger.warning("Hook 脚本读取失败", kb_id=str(kb_ctx.kb_id), error=str(err))

    resp = KbHookContent(
        kb_id=info["kb_id"],
        has_hook=info["has_hook"],
        content=content,
        overridden_interfaces=info.get("overridden_interfaces", []),
    )
    return success(data=resp.model_dump())


@router.put("/{kb_id}/hook/content", response_model_exclude_none=True)
async def update_hook_content(
    payload: KbHookUpdate,
    kb_ctx: KBContext = Depends(require_role(*MANAGE_ROLES)),
) -> dict:
    """更新 Hook 脚本内容（写入后自动清缓存，下次调用重载）。"""
    from app.kb_hooks.registry import write_kb_hook_script

    # 简单语法校验：编译检查
    try:
        compile(payload.content, "<hook>", "exec")
    except SyntaxError as err:
        raise BusinessException(
            code=ErrorCode.VALIDATION_ERROR,
            message=f"Hook 脚本语法错误: {err}",
        )

    write_kb_hook_script(kb_ctx.kb_id, payload.content)
    logger.info(
        "Hook 脚本已更新",
        kb_id=str(kb_ctx.kb_id),
        size=len(payload.content),
        user_id=str(kb_ctx.user.id),
    )
    return success(message="Hook 脚本已保存，下次调用自动重载")


@router.post("/{kb_id}/hook/reload", response_model_exclude_none=True)
async def reload_hook(
    kb_ctx: KBContext = Depends(require_role(*MANAGE_ROLES)),
) -> dict:
    """强制重载 Hook 脚本（清缓存）。"""
    from app.kb_hooks.registry import reload_kb_hook

    has_script = reload_kb_hook(kb_ctx.kb_id)
    resp = KbHookReloadResult(
        kb_id=str(kb_ctx.kb_id),
        reloaded=True,
        has_script=has_script,
    )
    return success(data=resp.model_dump(), message="Hook 缓存已清除")


@router.delete("/{kb_id}/hook", response_model_exclude_none=True)
async def delete_hook(
    kb_ctx: KBContext = Depends(require_role(*MANAGE_ROLES)),
) -> dict:
    """删除 Hook 脚本（回退到默认逻辑）。"""
    from app.kb_hooks.registry import delete_kb_hook_script

    deleted = delete_kb_hook_script(kb_ctx.kb_id)
    logger.info(
        "Hook 脚本已删除",
        kb_id=str(kb_ctx.kb_id),
        deleted=deleted,
        user_id=str(kb_ctx.user.id),
    )
    return success(data={"deleted": deleted}, message="Hook 已删除，回退默认逻辑")


# ============================================================
# 领域配置表查询/管理
# ============================================================
@router.get("/{kb_id}/domain/categories", response_model_exclude_none=True)
async def list_categories(
    kb_ctx: KBContext = Depends(get_kb_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取类别列表（含 enum 约束）。"""
    cfg = await kb_config_loader.load(kb_ctx.kb_id, db, kb=kb_ctx.kb)
    return success(data={"items": cfg.categories, "total": len(cfg.categories)})


@router.post("/{kb_id}/domain/categories", status_code=201, response_model_exclude_none=True)
async def create_category(
    payload: KbCategoryCreate,
    kb_ctx: KBContext = Depends(require_role(*MANAGE_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """新增抽取类别（含 enum 约束）。"""
    # 校验类别名唯一（显式按 kb_id 过滤，纵深防御不依赖 RLS）
    exist_stmt = select(KbCategory.id).where(
        KbCategory.kb_id == kb_ctx.kb_id,
        KbCategory.name == payload.name,
    )
    if (await db.execute(exist_stmt)).scalar_one_or_none() is not None:
        raise BusinessException(
            code=ErrorCode.VALIDATION_ERROR,
            message=f"类别 '{payload.name}' 已存在",
        )

    cat = KbCategory(
        kb_id=kb_ctx.kb_id,
        name=payload.name,
        extraction_class=payload.extraction_class,
        description=payload.description,
        is_active=payload.is_active,
        sort_order=payload.sort_order,
        recall_filter_threshold=payload.recall_filter_threshold,
    )
    db.add(cat)
    await db.flush()

    for field_name, values in payload.enums.items():
        db.add(
            KbCategoryEnum(
                category_id=cat.id,
                field_name=field_name,
                enum_values=list(values),
            )
        )
    await db.commit()
    await db.refresh(cat)

    logger.info(
        "类别已新增",
        kb_id=str(kb_ctx.kb_id),
        category=payload.name,
        user_id=str(kb_ctx.user.id),
    )
    return success(data={"id": str(cat.id), "name": cat.name}, message="类别已创建")


@router.put("/{kb_id}/domain/categories/{cat_id}", response_model_exclude_none=True)
async def update_category(
    cat_id: uuid.UUID,
    payload: KbCategoryUpdate,
    kb_ctx: KBContext = Depends(require_role(*MANAGE_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """更新类别定义。"""
    # 显式按 kb_id 过滤，防止跨 KB 越权操作
    cat = (
        await db.execute(
            select(KbCategory).where(
                KbCategory.id == cat_id,
                KbCategory.kb_id == kb_ctx.kb_id,
            )
        )
    ).scalar_one_or_none()
    if cat is None:
        raise BusinessException(code=ErrorCode.VALIDATION_ERROR, message="类别不存在")

    if payload.name is not None:
        cat.name = payload.name
    if payload.extraction_class is not None:
        cat.extraction_class = payload.extraction_class
    if payload.description is not None:
        cat.description = payload.description
    if payload.is_active is not None:
        cat.is_active = payload.is_active
    if payload.sort_order is not None:
        cat.sort_order = payload.sort_order
    if payload.recall_filter_threshold is not None:
        cat.recall_filter_threshold = payload.recall_filter_threshold

    # 覆盖 enum 约束（若提供）
    if payload.enums is not None:
        await db.execute(delete(KbCategoryEnum).where(KbCategoryEnum.category_id == cat_id))
        for field_name, values in payload.enums.items():
            db.add(
                KbCategoryEnum(
                    category_id=cat_id,
                    field_name=field_name,
                    enum_values=list(values),
                )
            )

    await db.commit()
    await db.refresh(cat)
    logger.info("类别已更新", kb_id=str(kb_ctx.kb_id), cat_id=str(cat_id))
    return success(data={"id": str(cat.id)}, message="类别已更新")


@router.delete("/{kb_id}/domain/categories/{cat_id}")
async def delete_category(
    cat_id: uuid.UUID,
    kb_ctx: KBContext = Depends(require_role(*MANAGE_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """删除类别（级联删除 enum 约束）。"""
    # 显式按 kb_id 过滤，防止跨 KB 越权删除
    cat = (
        await db.execute(
            select(KbCategory).where(
                KbCategory.id == cat_id,
                KbCategory.kb_id == kb_ctx.kb_id,
            )
        )
    ).scalar_one_or_none()
    if cat is None:
        raise BusinessException(code=ErrorCode.VALIDATION_ERROR, message="类别不存在")

    await db.delete(cat)  # 级联删除 enum
    await db.commit()
    logger.info("类别已删除", kb_id=str(kb_ctx.kb_id), cat_id=str(cat_id))
    return success(message="类别已删除")


@router.get("/{kb_id}/domain/regex-rules", response_model_exclude_none=True)
async def list_regex_rules(
    kb_ctx: KBContext = Depends(get_kb_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取正则规则列表。"""
    cfg = await kb_config_loader.load(kb_ctx.kb_id, db, kb=kb_ctx.kb)
    return success(data={"items": cfg.regex_rules, "total": len(cfg.regex_rules)})


@router.get("/{kb_id}/domain/field-templates", response_model_exclude_none=True)
async def list_field_templates(
    kb_ctx: KBContext = Depends(get_kb_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取字段模板列表。"""
    cfg = await kb_config_loader.load(kb_ctx.kb_id, db, kb=kb_ctx.kb)
    items = [
        {"template_type": k, "fields": v} for k, v in cfg.field_templates.items()
    ]
    return success(data={"items": items, "total": len(items)})


@router.get("/{kb_id}/domain/dict-config", response_model_exclude_none=True)
async def get_dict_config(
    kb_ctx: KBContext = Depends(get_kb_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取字典配置。"""
    cfg = await kb_config_loader.load(kb_ctx.kb_id, db, kb=kb_ctx.kb)
    return success(data=cfg.dict_config if cfg.dict_config else {"enabled": False})


# ============================================================
# 配置校验与资源诊断
# ============================================================
@router.post("/{kb_id}/config/validate", response_model_exclude_none=True)
async def validate_kb_config(
    kb_ctx: KBContext = Depends(require_role(*MANAGE_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """校验知识库配置完整性。

    检查项：
    - config 各节结构合法
    - 至少有 1 个启用的类别（除非 general_qa 领域）
    - 抽取类别有 enum 约束
    - 正则规则语法合法
    """
    cfg = await kb_config_loader.load(kb_ctx.kb_id, db, kb=kb_ctx.kb)
    errors: list[str] = []
    warnings: list[str] = []
    checks: dict[str, bool] = {}

    # 1. config 节结构
    for section in _VALID_SECTIONS:
        checks[f"config.{section}_exists"] = section in cfg.config
        if section not in cfg.config:
            warnings.append(f"config 节 '{section}' 缺失，将使用全局默认")

    # 2. 启用类别检查（general_qa 允许 0 类别）
    is_general_qa = kb_ctx.kb.domain_code == "general_qa"
    active_cats = [c for c in cfg.categories if c.get("is_active", True)]
    checks["has_active_categories"] = len(active_cats) > 0 or is_general_qa
    if not is_general_qa and len(active_cats) == 0:
        errors.append("无启用的抽取类别（general_qa 领域除外）")

    # 3. 类别 enum 约束
    for cat in active_cats:
        cat_name = cat.get("name", "")
        has_enums = bool(cat.get("enums"))
        checks[f"category.{cat_name}.has_enums"] = has_enums
        if not has_enums:
            warnings.append(f"类别 '{cat_name}' 无 enum 约束，可能导致跨类混入")

    # 4. 正则规则语法
    import re

    for rule in cfg.regex_rules:
        rule_name = rule.get("name", "")
        pattern = rule.get("pattern", "")
        try:
            re.compile(pattern)
            checks[f"regex.{rule_name}.valid"] = True
        except re.error as err:
            checks[f"regex.{rule_name}.valid"] = False
            errors.append(f"正则规则 '{rule_name}' 语法错误: {err}")

    valid = len(errors) == 0
    result = KbConfigValidationResult(
        valid=valid, errors=errors, warnings=warnings, checks=checks
    )
    return success(data=result.model_dump())


@router.get("/{kb_id}/resources/verify", response_model_exclude_none=True)
async def verify_kb_resources(
    kb_ctx: KBContext = Depends(require_role(*MANAGE_ROLES)),
) -> dict:
    """物理资源完整性诊断。"""
    steps = await kb_lifecycle.verify_kb_resources(kb_ctx.kb_id)
    resp = KbResourceVerifyResult(kb_id=kb_ctx.kb_id, steps=steps)
    return success(data=resp.model_dump())


# ============================================================
# 工具函数
# ============================================================
def _deep_merge_dicts(base: dict, override: dict) -> dict:
    """递归合并两个字典：override 覆盖 base 同名键，子字典递归合并。"""
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge_dicts(result[k], v)
        else:
            result[k] = v
    return result
