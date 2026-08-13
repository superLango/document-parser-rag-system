"""E2：抽取领域配置解析器（配置串联，供 E3 流水线消费）。

把当前项目的 Schema / Prompt / 规则组 / 全局配置 / 术语集聚合为
ExtractionDomainConfig；不做默认合并（全局配置已含默认+覆盖合并）。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.glossary import TermBase
from app.services import extraction_config_service


@dataclass
class ExtractionDomainConfig:
    kb_id: str
    global_config: dict = field(default_factory=dict)
    schema_templates: list[dict] = field(default_factory=list)
    prompt_templates: list[dict] = field(default_factory=list)
    rule_groups: list[dict] = field(default_factory=list)
    term_bases: list[dict] = field(default_factory=list)


async def resolve(db: AsyncSession, kb_id) -> ExtractionDomainConfig:
    """解析 KB 完整抽取配置。"""
    global_cfg = await extraction_config_service.get_global_config(db, kb_id)
    schema_list = await extraction_config_service.list_schema_templates(db, kb_id)
    schema_templates = []
    for t in schema_list:
        detail = await extraction_config_service.get_schema_template(db, kb_id, uuid.UUID(str(t["id"])))
        if detail.get("is_active", True):
            schema_templates.append(detail)
    prompts = await extraction_config_service.list_prompts(db, kb_id)
    groups = await extraction_config_service.list_rule_groups(db, kb_id)
    rule_groups = []
    for g in groups:
        detail = await extraction_config_service.get_rule_group(db, kb_id, uuid.UUID(str(g["id"])))
        rule_groups.append(detail)
    tb_rows = (
        await db.execute(select(TermBase.id, TermBase.name).where(TermBase.kb_id == kb_id))
    ).all()
    term_bases = [{"id": str(i), "name": n} for i, n in tb_rows]
    return ExtractionDomainConfig(
        kb_id=str(kb_id),
        global_config=global_cfg.get("content", {}),
        schema_templates=schema_templates,
        prompt_templates=[p for p in prompts if p.get("is_active", True)],
        rule_groups=rule_groups,
        term_bases=term_bases,
    )
