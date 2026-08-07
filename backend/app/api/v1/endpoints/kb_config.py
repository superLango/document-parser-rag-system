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

import asyncio
import time
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Path
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy.orm.attributes import flag_modified

from app.api.deps import KBContext, get_kb_context, require_role
from app.core.config import settings
from app.core.database import get_db
from app.core.exceptions import BusinessException, ErrorCode
from app.core.logging import get_logger
from app.core.response import success
from app.models.kb_domain_config import (
    KbCategory,
    KbCategoryEnum,
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
    ServiceCheckResult,
    ServiceConfigItem,
    ServiceConfigSection,
    ServicesDiagnoseResult,
)
from app.services.kb.domain_template_service import (
    get_template_detail,
    init_kb_from_template,
    list_available_templates,
)
from app.services.kb.kb_config_loader import kb_config_loader
from app.services.kb.kb_lifecycle import kb_lifecycle

from enum import Enum

logger = get_logger(__name__)

# 合法的 config 节名
class ConfigSectionEnum(str, Enum):
    ocr = "ocr"
    vector = "vector"
    extraction = "extraction"
    qa = "qa"
    dict = "dict"

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
        template_code=kb_ctx.kb.template_code,
    )
    return success(data=resp.model_dump())


@router.get("/{kb_id}/config/{section}", response_model_exclude_none=True)
async def get_kb_config_section(
    section: ConfigSectionEnum,
    kb_ctx: KBContext = Depends(get_kb_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取知识库某节配置（ocr/vector/extraction/qa/dict）。"""
    cfg = await kb_config_loader.load(kb_ctx.kb_id, db, kb=kb_ctx.kb)
    section_data = cfg.config.get(section.value, {})
    return success(data={"section": section.value, "config": section_data})


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
    section: ConfigSectionEnum,
    payload: KbConfigSectionUpdate,
    kb_ctx: KBContext = Depends(require_role(*MANAGE_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """更新知识库某节配置。"""
    section_key = section.value
    existing = kb_ctx.kb.config if isinstance(kb_ctx.kb.config, dict) else {}
    if section_key not in existing or not isinstance(existing.get(section_key), dict):
        existing[section_key] = {}
    existing[section_key] = _deep_merge_dicts(existing[section_key], payload.section)
    kb_ctx.kb.config = existing
    await db.commit()
    await db.refresh(kb_ctx.kb)

    logger.info(
        "KB config 节已更新",
        kb_id=str(kb_ctx.kb_id),
        section=section_key,
        user_id=str(kb_ctx.user.id),
    )
    return success(data={"section": section_key, "config": existing[section_key]}, message="配置节已更新")


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
# 服务连接校验与服务配置管理
# ============================================================

# 服务定义：服务名 -> 显示名、分类、图标、配置字段
_SERVICE_DEFINITIONS: dict[str, dict] = {
    "minio": {
        "display_name": "MinIO 对象存储",
        "description": "文档文件与备份存储",
        "icon": "HardDrive",
        "category": "storage",
        "fields": [
            {"key": "endpoint", "label": "服务端点", "type": "string", "default": settings.MINIO_ENDPOINT, "required": True, "placeholder": "localhost:9000"},
            {"key": "access_key", "label": "Access Key", "type": "string", "default": settings.MINIO_ACCESS_KEY, "required": True},
            {"key": "secret_key", "label": "Secret Key", "type": "password", "default": settings.MINIO_SECRET_KEY, "required": True},
            {"key": "secure", "label": "启用 HTTPS", "type": "boolean", "default": settings.MINIO_SECURE},
        ],
    },
    "milvus": {
        "display_name": "Milvus 向量数据库",
        "description": "文档向量索引与检索",
        "icon": "Search",
        "category": "vector",
        "fields": [
            {"key": "host", "label": "主机地址", "type": "string", "default": settings.MILVUS_HOST, "required": True, "placeholder": "localhost"},
            {"key": "port", "label": "端口", "type": "number", "default": settings.MILVUS_PORT, "required": True},
            {"key": "collection", "label": "默认 Collection", "type": "string", "default": settings.MILVUS_COLLECTION},
        ],
    },
    "nebula": {
        "display_name": "NebulaGraph 图谱数据库",
        "description": "知识图谱存储与查询",
        "icon": "Network",
        "category": "graph",
        "fields": [
            {"key": "graphd_host", "label": "Graphd 主机", "type": "string", "default": settings.NEBULA_GRAPHD_HOST, "required": True, "placeholder": "localhost"},
            {"key": "graphd_port", "label": "Graphd 端口", "type": "number", "default": settings.NEBULA_GRAPHD_PORT, "required": True},
            {"key": "user", "label": "用户名", "type": "string", "default": settings.NEBULA_USER, "required": True},
            {"key": "password", "label": "密码", "type": "password", "default": settings.NEBULA_PASSWORD},
            {"key": "space_prefix", "label": "Space 前缀", "type": "string", "default": settings.NEBULA_SPACE_PREFIX},
        ],
    },
    "redis": {
        "display_name": "Redis 缓存",
        "description": "缓存与会话存储",
        "icon": "Database",
        "category": "cache",
        "fields": [
            {"key": "url", "label": "连接 URL", "type": "string", "default": settings.REDIS_URL, "required": True, "placeholder": "redis://localhost:6379/0"},
        ],
    },
    "llm_vllm": {
        "display_name": "LLM vLLM (9988)",
        "description": "通用大语言模型服务（兼作结构化抽取端点）",
        "icon": "Brain",
        "category": "llm",
        "fields": [
            {"key": "api_base", "label": "API Base URL", "type": "string", "default": settings.LLM_API_BASE, "required": True, "placeholder": "http://localhost:9988/v1"},
            {"key": "model", "label": "模型名称", "type": "string", "default": settings.LLM_API_MODEL, "required": True},
            {"key": "api_key", "label": "API Key", "type": "password", "default": settings.EXTRACTION_V3_LLM_API_KEY, "placeholder": "sk-... 或 EMPTY"},
        ],
    },
    "ocr_vllm": {
        "display_name": "OCR vLLM (9977)",
        "description": "GLM-OCR 文档识别服务",
        "icon": "FileText",
        "category": "llm",
        "fields": [
            {"key": "server_url", "label": "API Base URL", "type": "string", "default": settings.GLMOCR_SERVER_URL, "required": True, "placeholder": "http://localhost:9977/v1"},
            {"key": "model", "label": "模型名称", "type": "string", "default": settings.GLMOCR_MODEL, "required": True},
        ],
    },
    "popo_vllm": {
        "display_name": "Popo vLLM (9999)",
        "description": "Popo 专用模型服务",
        "icon": "Sparkles",
        "category": "llm",
        "fields": [
            {"key": "api_base", "label": "API Base URL", "type": "string", "default": "http://localhost:9999/v1", "required": True, "placeholder": "http://localhost:9999/v1"},
            {"key": "model", "label": "模型名称", "type": "string", "default": "popo-model"},
        ],
    },
    "layout_model": {
        "display_name": "版面分析模型",
        "description": "PP-DocLayoutV3 文档版面检测",
        "icon": "LayoutGrid",
        "category": "model",
        "fields": [
            {"key": "enabled", "label": "启用版面分析", "type": "boolean", "default": True},
        ],
    },
    "embedding_model": {
        "display_name": "Embedding 模型",
        "description": "bge-m3 文本向量化模型",
        "icon": "Hash",
        "category": "model",
        "fields": [
            {"key": "model_path", "label": "模型路径", "type": "string", "default": settings.EMBEDDING_MODEL_PATH},
            {"key": "batch_size", "label": "批量大小", "type": "number", "default": settings.EMBEDDING_BATCH_SIZE},
        ],
    },
}


async def _check_minio(kb_id: uuid.UUID | None = None) -> tuple[str, str, float, dict]:
    """检查 MinIO/S3 存储连通性与 bucket 存在性。"""
    start = time.time()
    try:
        from app.services.infra.storage_service import storage_service
        client = storage_service._get_client()
        # 检查 KB bucket 是否存在
        if kb_id:
            bucket_name = f"{settings.KB_MINIO_BUCKET_PREFIX}{kb_id.hex}"
            await asyncio.to_thread(client.head_bucket, Bucket=bucket_name)
            msg = f"Bucket '{bucket_name}' 可访问"
        else:
            await asyncio.to_thread(client.list_buckets)
            msg = "MinIO 服务连接正常"
        return "ok", msg, (time.time() - start) * 1000, {"endpoint": settings.MINIO_ENDPOINT}
    except Exception as exc:
        return "error", f"连接失败: {str(exc)[:200]}", (time.time() - start) * 1000, {}


async def _check_milvus(kb_id: uuid.UUID | None = None) -> tuple[str, str, float, dict]:
    """检查 Milvus 向量库连通性。"""
    start = time.time()
    try:
        from pymilvus import connections, utility
        alias = "config_check"
        if not connections.has_connection(alias):
            connections.connect(
                alias=alias,
                host=settings.MILVUS_HOST,
                port=str(settings.MILVUS_PORT),
                timeout=3,
            )
        collections = utility.list_collections(using=alias)
        connections.disconnect(alias)
        return "ok", f"连接正常，共 {len(collections)} 个 collection", (time.time() - start) * 1000, {
            "host": f"{settings.MILVUS_HOST}:{settings.MILVUS_PORT}",
            "collections": collections[:10],
        }
    except Exception as exc:
        return "error", f"连接失败: {str(exc)[:200]}", (time.time() - start) * 1000, {}


async def _check_nebula(kb_id: uuid.UUID | None = None) -> tuple[str, str, float, dict]:
    """检查 NebulaGraph 图数据库连通性。"""
    start = time.time()
    try:
        from app.services.graph.graph_store import graph_store
        connected = await asyncio.to_thread(graph_store._try_connect)
        if not connected:
            return "warning", "连接可用但未能获取详情（图谱功能将降级）", (time.time() - start) * 1000, {}
        space_count = 0
        try:
            session = await asyncio.to_thread(graph_store._get_session)
            try:
                resp = await asyncio.to_thread(session.execute, "SHOW SPACES;")
                if resp.is_succeeded():
                    space_count = len(resp.rows())
            finally:
                await asyncio.to_thread(session.release)
        except Exception:
            pass
        return "ok", f"连接正常，共 {space_count} 个 graph space", (time.time() - start) * 1000, {
            "host": f"{settings.NEBULA_GRAPHD_HOST}:{settings.NEBULA_GRAPHD_PORT}",
        }
    except Exception as exc:
        return "warning", f"连接失败（图谱功能将优雅降级）: {str(exc)[:150]}", (time.time() - start) * 1000, {}


async def _check_redis(kb_id: uuid.UUID | None = None) -> tuple[str, str, float, dict]:
    """检查 Redis 缓存连通性。"""
    start = time.time()
    try:
        import redis.asyncio as aioredis
        client = aioredis.from_url(settings.REDIS_URL, socket_connect_timeout=2)
        pong = await client.ping()
        await client.aclose()
        return "ok", "PONG" if pong else "Ping 返回异常", (time.time() - start) * 1000, {}
    except Exception as exc:
        return "error", f"连接失败: {str(exc)[:200]}", (time.time() - start) * 1000, {}


async def _check_llm(port: int, service_name: str) -> tuple[str, str, float, dict]:
    """检查 vLLM LLM 服务连通性（简单 health 检查）。"""
    start = time.time()
    try:
        import httpx
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"http://localhost:{port}/health")
            if resp.status_code < 500:
                return "ok", f"{service_name} 服务响应正常 (HTTP {resp.status_code})", (time.time() - start) * 1000, {
                    "endpoint": f"http://localhost:{port}",
                }
            return "error", f"服务返回错误状态: HTTP {resp.status_code}", (time.time() - start) * 1000, {}
    except Exception as exc:
        return "error", f"连接失败: {str(exc)[:200]}", (time.time() - start) * 1000, {}


async def _check_layout_model() -> tuple[str, str, float, dict]:
    """检查版面分析模型可用性。"""
    start = time.time()
    try:
        from app.services.ocr import ocr_service
        available = await asyncio.to_thread(ocr_service.is_layout_model_available)
        if available:
            from app.services.ocr.ocr_config import ocr_config
            return "ok", f"PP-DocLayoutV3 模型可用", (time.time() - start) * 1000, {
                "model_dir": ocr_config.layout_model_dir,
            }
        return "warning", "版面分析模型未加载，将使用整页 OCR", (time.time() - start) * 1000, {}
    except Exception as exc:
        return "warning", f"模型检查失败（将跳过版面分析）: {str(exc)[:150]}", (time.time() - start) * 1000, {}


async def _check_embedding_model() -> tuple[str, str, float, dict]:
    """检查 Embedding 模型（懒加载，只检查配置）。"""
    start = time.time()
    import os
    model_path = settings.EMBEDDING_MODEL_PATH
    if os.path.exists(model_path):
        return "ok", f"bge-m3 模型路径存在（懒加载）", (time.time() - start) * 1000, {"model_path": model_path}
    return "warning", f"模型路径不存在: {model_path}", (time.time() - start) * 1000, {}


_SERVICE_CHECKS: dict[str, callable] = {
    "minio": _check_minio,
    "milvus": _check_milvus,
    "nebula": _check_nebula,
    "redis": _check_redis,
    "llm_vllm": lambda kb_id: _check_llm(9988, "LLM"),
    "ocr_vllm": lambda kb_id: _check_llm(9977, "OCR vLLM"),
    "popo_vllm": lambda kb_id: _check_llm(9999, "Popo vLLM"),
    "layout_model": lambda kb_id: _check_layout_model(),
    "embedding_model": lambda kb_id: _check_embedding_model(),
}


@router.get("/{kb_id}/services", response_model_exclude_none=True)
async def list_service_configs(
    kb_ctx: KBContext = Depends(get_kb_context),
) -> dict:
    """获取所有服务的配置列表（含默认值与当前 KB 覆盖值、持久化校验状态）。"""
    kb_config = kb_ctx.kb.config if isinstance(kb_ctx.kb.config, dict) else {}
    service_configs = kb_config.get("services", {})
    services_status = kb_config.get("services_status", {})
    services_map = services_status.get("services", {})

    sections = []
    for svc_name, svc_def in _SERVICE_DEFINITIONS.items():
        svc_overrides = service_configs.get(svc_name, {})
        svc_status = services_map.get(svc_name)
        fields = []
        for f in svc_def["fields"]:
            current_value = svc_overrides.get(f["key"], f["default"])
            fields.append(ServiceConfigItem(
                key=f["key"],
                label=f["label"],
                type=f["type"],
                value=current_value,
                default=f.get("default"),
                required=f.get("required", False),
                placeholder=f.get("placeholder"),
                description=f.get("description"),
            ).model_dump())
        sections.append(ServiceConfigSection(
            name=svc_name,
            display_name=svc_def["display_name"],
            description=svc_def["description"],
            icon=svc_def.get("icon"),
            category=svc_def["category"],
            configurable=True,
            fields=fields,
            last_status=svc_status,
        ).model_dump())

    return success(data={
        "services": sections,
        "last_diagnose": {
            "checked_at": services_status.get("checked_at"),
            "total": services_status.get("total", 0),
            "ok_count": services_status.get("ok_count", 0),
            "error_count": services_status.get("error_count", 0),
            "warning_count": services_status.get("warning_count", 0),
        } if services_status else None,
    })


@router.get("/{kb_id}/services/status", response_model_exclude_none=True)
async def get_services_status(
    kb_ctx: KBContext = Depends(get_kb_context),
) -> dict:
    """获取持久化的服务诊断状态（供概览页等页面读取）。"""
    kb_config = kb_ctx.kb.config if isinstance(kb_ctx.kb.config, dict) else {}
    services_status = kb_config.get("services_status")
    if not services_status:
        return success(data={
            "checked_at": None,
            "total": len(_SERVICE_DEFINITIONS),
            "ok_count": 0,
            "error_count": 0,
            "warning_count": 0,
            "services": [],
            "never_checked": True,
        })
    return success(data={**services_status, "never_checked": False})


@router.put("/{kb_id}/services/{service_name}", response_model_exclude_none=True)
async def update_service_config(
    service_name: str,
    payload: dict,
    kb_ctx: KBContext = Depends(require_role(*MANAGE_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """更新单个服务的配置（仅保存该服务的覆盖项）。"""
    if service_name not in _SERVICE_DEFINITIONS:
        raise BusinessException(
            code=ErrorCode.VALIDATION_ERROR,
            message=f"未知服务: {service_name}，合法值: {sorted(_SERVICE_DEFINITIONS.keys())}",
        )

    existing = kb_ctx.kb.config if isinstance(kb_ctx.kb.config, dict) else {}
    services_config = dict(existing.get("services", {}))
    # 只保存非默认值的覆盖项
    svc_def = _SERVICE_DEFINITIONS[service_name]
    overrides = {}
    for f in svc_def["fields"]:
        key = f["key"]
        if key in payload and payload[key] != f.get("default"):
            overrides[key] = payload[key]
    services_config[service_name] = overrides
    new_config = dict(existing)
    new_config["services"] = services_config
    kb_ctx.kb.config = new_config
    flag_modified(kb_ctx.kb, "config")
    await db.commit()

    logger.info(
        "服务配置已更新",
        kb_id=str(kb_ctx.kb_id),
        service=service_name,
        user_id=str(kb_ctx.user.id),
    )
    return success(data={"service": service_name, "config": overrides}, message=f"{svc_def['display_name']} 配置已保存")


@router.post("/{kb_id}/services/{service_name}/validate", response_model_exclude_none=True)
async def validate_single_service(
    service_name: str,
    kb_ctx: KBContext = Depends(require_role(*MANAGE_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """校验单个服务连接状态，并更新持久化诊断结果。"""
    if service_name not in _SERVICE_CHECKS:
        raise BusinessException(
            code=ErrorCode.VALIDATION_ERROR,
            message=f"未知服务: {service_name}",
        )

    svc_def = _SERVICE_DEFINITIONS.get(service_name, {})
    check_fn = _SERVICE_CHECKS[service_name]
    try:
        status, message, rt_ms, details = await asyncio.wait_for(
            check_fn(kb_ctx.kb_id), timeout=10.0
        )
    except asyncio.TimeoutError:
        status, message, rt_ms, details = "error", "校验超时（10s）", 10000, {}

    result = ServiceCheckResult(
        name=service_name,
        display_name=svc_def.get("display_name", service_name),
        status=status,
        message=message,
        response_time_ms=rt_ms,
        details=details,
    )

    # 更新持久化诊断结果中的单个服务状态
    existing = kb_ctx.kb.config if isinstance(kb_ctx.kb.config, dict) else {}
    services_status = dict(existing.get("services_status", {}))
    services_map = dict(services_status.get("services", {}))
    services_map[service_name] = result.model_dump()
    # 重新统计
    ok_count = sum(1 for s in services_map.values() if s.get("status") == "ok")
    error_count = sum(1 for s in services_map.values() if s.get("status") == "error")
    warning_count = sum(1 for s in services_map.values() if s.get("status") == "warning")
    new_services_status = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "total": len(services_map),
        "ok_count": ok_count,
        "error_count": error_count,
        "warning_count": warning_count,
        "services": services_map,
    }
    new_config = dict(existing)
    new_config["services_status"] = new_services_status
    kb_ctx.kb.config = new_config
    flag_modified(kb_ctx.kb, "config")
    await db.commit()

    return success(data=result.model_dump())


@router.post("/{kb_id}/diagnose", response_model_exclude_none=True)
async def diagnose_all_services(
    kb_ctx: KBContext = Depends(require_role(*MANAGE_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """一键诊断所有服务连接状态（依次检查，带超时保护），并持久化诊断结果。"""
    results = []
    ok_count = 0
    error_count = 0
    warning_count = 0

    for svc_name, svc_def in _SERVICE_DEFINITIONS.items():
        check_fn = _SERVICE_CHECKS.get(svc_name)
        if not check_fn:
            continue
        try:
            status, message, rt_ms, details = await asyncio.wait_for(
                check_fn(kb_ctx.kb_id), timeout=10.0
            )
        except asyncio.TimeoutError:
            status, message, rt_ms, details = "error", "校验超时（10s）", 10000, {}
        except Exception as exc:
            status, message, rt_ms, details = "error", f"校验异常: {str(exc)[:200]}", 0, {}

        if status == "ok":
            ok_count += 1
        elif status == "warning":
            warning_count += 1
        else:
            error_count += 1

        results.append(ServiceCheckResult(
            name=svc_name,
            display_name=svc_def["display_name"],
            status=status,
            message=message,
            response_time_ms=rt_ms,
            details=details,
        ).model_dump())

    checked_at = datetime.now(timezone.utc)
    resp = ServicesDiagnoseResult(
        kb_id=kb_ctx.kb_id,
        total=len(results),
        ok_count=ok_count,
        error_count=error_count,
        warning_count=warning_count,
        services=results,
        checked_at=checked_at,
    )

    # 持久化诊断结果到 KB config
    existing = kb_ctx.kb.config if isinstance(kb_ctx.kb.config, dict) else {}
    new_config = dict(existing)
    new_config["services_status"] = {
        "checked_at": checked_at.isoformat(),
        "total": len(results),
        "ok_count": ok_count,
        "error_count": error_count,
        "warning_count": warning_count,
        "services": {s["name"]: s for s in results},
    }
    kb_ctx.kb.config = new_config
    flag_modified(kb_ctx.kb, "config")
    await db.commit()

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
