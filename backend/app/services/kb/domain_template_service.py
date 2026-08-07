"""领域模板服务（方案 §7 配置中心 / §A.6 三层覆盖）。

提供领域模板的查询与初始化能力：
- ``list_templates`` / ``get_template``：查询内置模板列表与详情
- ``init_kb_from_template``：将模板配置写入 KB 专属领域配置表

初始化流程（``init_kb_from_template``）：
    1. 校验 template_code 存在
    2. 清理该 KB 旧配置（幂等，避免重复初始化产生脏数据）
    3. 写入 kb_categories + kb_category_enums
    4. 写入 kb_field_templates
    5. 写入 kb_regex_rules
    6. 合并模板 config_override 到 KnowledgeBase.config
    7. 若模板含 hook_template，写入 ``app/kb_hooks/{kb_id}/hooks.py``

事务策略：
- 配置写入在单个事务内完成，失败回滚
- config 合并与 Hook 文件写入在事务外执行（DB 提交后）

集成点：
- ``app.api.v1.endpoints.kbs.create_knowledge_base`` 在创建 KB 后调用本服务
- ``app.api.v1.endpoints.kb_config`` 提供模板列表查询端点（阶段 5）
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.domain_templates import TEMPLATES, get_template, list_templates
from app.models.kb_domain_config import (
    KbCategory,
    KbCategoryEnum,
    KbFieldTemplate,
    KbRegexRule,
)
from app.models.knowledge_base import KnowledgeBase

logger = get_logger(__name__)


# ============================================================
# 模板查询
# ============================================================
def list_available_templates() -> list[dict[str, Any]]:
    """列出全部可用领域模板摘要。

    Returns:
        list[dict]: 模板摘要列表，每项含 code/name/description/domain_code/
        category_count/regex_rule_count/has_hook。
    """
    return [tpl.to_summary() for tpl in list_templates()]


def get_template_detail(code: str) -> dict[str, Any] | None:
    """获取指定模板的完整详情。

    Args:
        code: 模板编码。

    Returns:
        模板详情字典，或 None（模板不存在）。
    """
    tpl = get_template(code)
    if tpl is None:
        return None
    return tpl.to_detail()


# ============================================================
# 模板初始化（落库到 KB 专属配置表）
# ============================================================
async def init_kb_from_template(
    kb_id: uuid.UUID,
    template_code: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """从领域模板初始化知识库领域配置。

    将模板的类别、字段模板、正则规则、字典配置写入 KB 专属配置表，
    并合并模板的 config_override 到 KnowledgeBase.config。
    若模板含 hook_template，同时创建初始 Hook 脚本文件。

    幂等性：若 KB 已有配置，先清理旧配置再写入，避免重复初始化产生脏数据。

    Args:
        kb_id: 知识库 ID。
        template_code: 模板编码。
        db: 异步数据库会话（RLS 已激活，写入自动按 kb_id 隔离）。

    Returns:
        dict: 初始化结果统计。

    Raises:
        ValueError: 模板编码不存在。
    """
    tpl = get_template(template_code)
    if tpl is None:
        raise ValueError(
            f"领域模板 '{template_code}' 不存在，可用模板: {list(TEMPLATES.keys())}"
        )

    logger.info(
        "开始从模板初始化知识库领域配置",
        kb_id=str(kb_id),
        template_code=template_code,
        template_name=tpl.name,
    )

    # 1. 清理旧配置（幂等）
    await _clear_kb_domain_config(db, kb_id)

    # 2. 写入领域配置表
    cat_count = await _write_categories(db, kb_id, tpl.categories)
    ft_count = await _write_field_templates(db, kb_id, tpl.field_templates)
    rr_count = await _write_regex_rules(db, kb_id, tpl.regex_rules)

    # 3. 合并 config_override 到 KnowledgeBase.config
    config_merged = await _merge_config_override(db, kb_id, tpl.config_override)

    # 4. 写入 Hook 脚本（若有）
    hook_written = False
    if tpl.hook_template:
        try:
            from app.kb_hooks.registry import write_kb_hook_script

            write_kb_hook_script(kb_id, tpl.hook_template)
            hook_written = True
        except Exception as err:  # noqa: BLE001
            logger.warning(
                "Hook 脚本写入失败（不影响主流程）",
                kb_id=str(kb_id),
                error=str(err),
            )

    await db.commit()

    result = {
        "template_code": template_code,
        "template_name": tpl.name,
        "categories_written": cat_count,
        "field_templates_written": ft_count,
        "regex_rules_written": rr_count,
        "config_override_merged": config_merged,
        "hook_script_written": hook_written,
    }

    logger.info("知识库领域配置初始化完成", kb_id=str(kb_id), **result)
    return result


# ============================================================
# 内部实现
# ============================================================
async def _clear_kb_domain_config(db: AsyncSession, kb_id: uuid.UUID) -> None:
    """清理 KB 的旧领域配置（幂等）。

    按外键依赖顺序删除：先删 enum（依赖 category）→ category →
    field_template / regex_rule。

    Args:
        db: 异步数据库会话。
        kb_id: 知识库 ID。
    """
    # 查询该 KB 的所有 category id（用于删 enum）
    cat_ids_stmt = select(KbCategory.id).where(KbCategory.kb_id == kb_id)
    cat_ids = [row[0] for row in (await db.execute(cat_ids_stmt)).all()]

    if cat_ids:
        await db.execute(
            delete(KbCategoryEnum).where(KbCategoryEnum.category_id.in_(cat_ids))
        )
    await db.execute(delete(KbCategory).where(KbCategory.kb_id == kb_id))
    await db.execute(delete(KbFieldTemplate).where(KbFieldTemplate.kb_id == kb_id))
    await db.execute(delete(KbRegexRule).where(KbRegexRule.kb_id == kb_id))

    logger.debug("已清理 KB 旧领域配置", kb_id=str(kb_id), old_categories=len(cat_ids))


async def _write_categories(
    db: AsyncSession,
    kb_id: uuid.UUID,
    categories: list,
) -> int:
    """写入类别定义与 enum 约束。

    Args:
        db: 异步数据库会话。
        kb_id: 知识库 ID。
        categories: CategoryDef 列表。

    Returns:
        int: 写入的类别数量。
    """
    count = 0
    for cat_def in categories:
        cat = KbCategory(
            kb_id=kb_id,
            name=cat_def.name,
            extraction_class=cat_def.extraction_class,
            description=cat_def.description or None,
            is_active=cat_def.is_active,
            sort_order=cat_def.sort_order,
            recall_filter_threshold=cat_def.recall_filter_threshold,
        )
        db.add(cat)
        await db.flush()  # 取 cat.id

        for enum_def in cat_def.enums:
            db.add(
                KbCategoryEnum(
                    category_id=cat.id,
                    field_name=enum_def.field_name,
                    enum_values=list(enum_def.enum_values),
                )
            )
        count += 1
    return count


async def _write_field_templates(
    db: AsyncSession,
    kb_id: uuid.UUID,
    field_templates: list,
) -> int:
    """写字段模板。"""
    count = 0
    for ft_def in field_templates:
        db.add(
            KbFieldTemplate(
                kb_id=kb_id,
                template_type=ft_def.template_type,
                fields=list(ft_def.fields),
                prompt=ft_def.prompt,
            )
        )
        count += 1
    return count


async def _write_regex_rules(
    db: AsyncSession,
    kb_id: uuid.UUID,
    regex_rules: list,
) -> int:
    """写候选项目正则规则。"""
    count = 0
    for rr_def in regex_rules:
        db.add(
            KbRegexRule(
                kb_id=kb_id,
                name=rr_def.name,
                pattern=rr_def.pattern,
                description=rr_def.description or None,
                enabled=True,
                sort_order=rr_def.sort_order,
            )
        )
        count += 1
    return count


async def _merge_config_override(
    db: AsyncSession,
    kb_id: uuid.UUID,
    config_override: dict[str, Any],
) -> bool:
    """将模板的 config_override 合并到 KnowledgeBase.config。

    采用深合并策略：模板配置覆盖 KB config 同名键，子字典递归合并。

    Args:
        db: 异步数据库会话。
        kb_id: 知识库 ID。
        config_override: 模板的配置覆盖项。

    Returns:
        bool: 是否发生了合并（config_override 非空时为 True）。
    """
    if not config_override:
        return False

    stmt = select(KnowledgeBase).where(KnowledgeBase.id == kb_id)
    kb = (await db.execute(stmt)).scalar_one_or_none()
    if kb is None:
        logger.warning("合并 config_override 失败：知识库不存在", kb_id=str(kb_id))
        return False

    existing = kb.config if isinstance(kb.config, dict) else {}
    merged = _deep_merge_dicts(existing, config_override)
    kb.config = merged
    return True


def _deep_merge_dicts(base: dict, override: dict) -> dict:
    """递归合并两个字典：override 覆盖 base 同名键，子字典递归合并。"""
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge_dicts(result[k], v)
        else:
            result[k] = v
    return result
