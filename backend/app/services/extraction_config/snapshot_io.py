"""抽取配置版本快照的导出 / 导入 / 对比。

供「版本快照」功能使用：

- ``export_snapshot``：将知识库当前的全部抽取配置导出为可 JSON 序列化的快照。
- ``import_snapshot``：将快照全量重建（删除当前配置后按快照恢复，保留原始 id）。
- ``diff_snapshots``：对比两份快照，返回各配置域的差异清单（查看对比 / 回滚预警）。

快照覆盖 8 类配置（与「抽取配置中心」保持一致）：
全局配置 / 脚本 / 数据集 / Schema 模板 / 术语绑定 / Prompt 模板 / 规则 / 规则组。

为保证引用关系（``parent_id`` / ``template_id`` / ``script_id`` / ``category_id`` 等）
在重建后依旧成立，导入时保留原始 id，并按依赖顺序删除 / 重建。

执行上下文：函数接收调用方传入的 ``db`` 会话（该会话已由 ``get_kb_context``
执行 ``SET LOCAL app.current_kb``，RLS 已生效），删除 / 写入均按当前 kb_id 隔离。
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.extraction_config import (
    KbExtractionConfig,
    KbPromptCategory,
    KbPromptTemplate,
    KbRule,
    KbRuleGroup,
    KbRuleGroupItem,
    KbScript,
    KbTermBinding,
)
from app.models.schema_model import SchemaConfig, SchemaTemplate

# 快照覆盖的配置域（顺序即文档展示顺序）
SNAPSHOT_DOMAINS = (
    "global",
    "scripts",
    "schema_templates",
    "term_bindings",
    "prompt_templates",
    "rules",
    "rule_groups",
)

# 域的中文名（用于预警 / 对比展示）
DOMAIN_LABELS = {
    "global": "全局配置",
    "scripts": "处理脚本",
    "schema_templates": "Schema 模板",
    "term_bindings": "术语绑定",
    "prompt_templates": "Prompt 模板",
    "rules": "规则",
    "rule_groups": "后处理与校验规则组",
}


def _u(value: Any) -> str | None:
    """UUID / None → str / None，便于 JSON 序列化。"""
    return str(value) if value is not None else None


def _uid(value: Any) -> uuid.UUID | None:
    """str / UUID → uuid.UUID，用于重建。"""
    if value is None or value == "":
        return None
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


async def export_snapshot(db: AsyncSession, kb_id: Any) -> dict[str, Any]:
    """导出知识库当前全部抽取配置为快照 dict。

    Args:
        db: 已激活 RLS 的会话。
        kb_id: 知识库 ID。

    Returns:
        dict: 含 8 个配置域的完整快照。
    """
    kb = kb_id if isinstance(kb_id, uuid.UUID) else uuid.UUID(str(kb_id))
    snap: dict[str, Any] = {
        "global": {"content": {}, "enabled": True, "version": 1},
        "scripts": [],
        "schema_templates": [],
        "term_bindings": [],
        "prompt_templates": [],
        "rules": [],
        "rule_groups": [],
    }

    # 全局配置
    cfg = (
        await db.execute(
            select(KbExtractionConfig).where(KbExtractionConfig.kb_id == kb)
        )
    ).scalars().first()
    if cfg is not None:
        snap["global"] = {
            "content": cfg.content,
            "enabled": cfg.enabled,
            "version": cfg.version,
        }

    # 脚本
    scripts = (
        await db.execute(
            select(KbScript).where(KbScript.kb_id == kb).order_by(KbScript.created_at)
        )
    ).scalars().all()
    snap["scripts"] = [
        {
            "id": _u(s.id),
            "folder": s.folder,
            "name": s.name,
            "code": s.code,
            "params_schema": s.params_schema,
            "enabled": s.enabled,
            "sort_order": s.sort_order,
            "description": s.description,
        }
        for s in scripts
    ]

    # Schema 模板 + 配置节点
    templates = (
        await db.execute(
            select(SchemaTemplate)
            .where(SchemaTemplate.kb_id == kb)
            .order_by(SchemaTemplate.created_at)
        )
    ).scalars().all()
    for tpl in templates:
        configs = (
            await db.execute(
                select(SchemaConfig)
                .where(SchemaConfig.template_id == tpl.id)
                .order_by(SchemaConfig.sort_order)
            )
        ).scalars().all()
        snap["schema_templates"].append(
            {
                "id": _u(tpl.id),
                "name": tpl.name,
                "description": tpl.description,
                "is_active": tpl.is_active,
                "configs": [
                    {
                        "id": _u(c.id),
                        "parent_id": _u(c.parent_id),
                        "template_id": _u(c.template_id),
                        "node_type": c.node_type,
                        "name": c.name,
                        "description": c.description,
                        "schema_definition": c.schema_definition,
                        "sample_fields": c.sample_fields,
                        "is_active": c.is_active,
                        "sort_order": c.sort_order,
                        "return_type": c.return_type,
                        "extraction_strategy": c.extraction_strategy,
                        "query_mode": c.query_mode,
                        "fixed_query": c.fixed_query,
                        "confidence_threshold": c.confidence_threshold,
                        "top_k": c.top_k,
                        "datasets": c.datasets,
                        "name_source": c.name_source,
                        "name_term_base_id": _u(c.name_term_base_id),
                        "name_term_field": c.name_term_field,
                        "query_sources": c.query_sources,
                    }
                    for c in configs
                ],
            }
        )

    # 术语绑定
    bindings = (
        await db.execute(
            select(KbTermBinding)
            .where(KbTermBinding.kb_id == kb)
            .order_by(KbTermBinding.created_at)
        )
    ).scalars().all()
    snap["term_bindings"] = [
        {
            "id": _u(b.id),
            "schema_id": _u(b.schema_id),
            "field_name": b.field_name,
            "term_base_id": _u(b.term_base_id),
            "config": b.config,
        }
        for b in bindings
    ]

    # Prompt 模板 + 类别子表
    prompts = (
        await db.execute(
            select(KbPromptTemplate)
            .where(KbPromptTemplate.kb_id == kb)
            .order_by(KbPromptTemplate.created_at)
        )
    ).scalars().all()
    for pt in prompts:
        cats = (
            await db.execute(
                select(KbPromptCategory)
                .where(KbPromptCategory.prompt_template_id == pt.id)
                .order_by(KbPromptCategory.sort_order)
            )
        ).scalars().all()
        snap["prompt_templates"].append(
            {
                "id": _u(pt.id),
                "name": pt.name,
                "description": pt.description,
                "scope": pt.scope,
                "system_prompt": pt.system_prompt,
                "user_prompt": pt.user_prompt,
                "schema_template_id": _u(pt.schema_template_id),
                "is_active": pt.is_active,
                "categories": [
                    {
                        "id": _u(c.id),
                        "category_id": _u(c.category_id),
                        "user_prompt": c.user_prompt,
                        "sort_order": c.sort_order,
                    }
                    for c in cats
                ],
            }
        )

    # 规则
    rules = (
        await db.execute(
            select(KbRule).where(KbRule.kb_id == kb).order_by(KbRule.created_at)
        )
    ).scalars().all()
    snap["rules"] = [
        {
            "id": _u(r.id),
            "stage": r.stage,
            "rule_key": r.rule_key,
            "name": r.name,
            "description": r.description,
            "enabled": r.enabled,
            "sort_order": r.sort_order,
            "scope": r.scope,
            "params": r.params,
        }
        for r in rules
    ]

    # 规则组 + 规则项
    groups = (
        await db.execute(
            select(KbRuleGroup).where(KbRuleGroup.kb_id == kb).order_by(KbRuleGroup.created_at)
        )
    ).scalars().all()
    for g in groups:
        items = (
            await db.execute(
                select(KbRuleGroupItem)
                .where(KbRuleGroupItem.rule_group_id == g.id)
                .order_by(KbRuleGroupItem.sort_order)
            )
        ).scalars().all()
        snap["rule_groups"].append(
            {
                "id": _u(g.id),
                "name": g.name,
                "schema_template_id": _u(g.schema_template_id),
                "description": g.description,
                "items": [
                    {
                        "id": _u(i.id),
                        "category_id": _u(i.category_id),
                        "category_name": i.category_name,
                        "script_id": _u(i.script_id),
                        "stage": i.stage,
                        "sort_order": i.sort_order,
                    }
                    for i in items
                ],
            }
        )

    return snap


async def _delete_current(db: AsyncSession, kb_id: uuid.UUID) -> None:
    """按依赖顺序删除知识库当前全部抽取配置（子表先删，规避外键冲突）。"""
    # 规则组（级联 / 显式删规则项）
    await db.execute(delete(KbRuleGroupItem).where(KbRuleGroupItem.kb_id == kb_id))
    await db.execute(delete(KbRuleGroup).where(KbRuleGroup.kb_id == kb_id))
    # 脚本（规则项已删，脚本可安全删除）
    await db.execute(delete(KbScript).where(KbScript.kb_id == kb_id))
    # 术语绑定（引用 schema_configs / datasets）
    await db.execute(delete(KbTermBinding).where(KbTermBinding.kb_id == kb_id))
    # Prompt 类别 / 模板
    prompt_ids = (
        await db.execute(select(KbPromptTemplate.id).where(KbPromptTemplate.kb_id == kb_id))
    ).scalars().all()
    if prompt_ids:
        await db.execute(
            delete(KbPromptCategory).where(KbPromptCategory.prompt_template_id.in_(prompt_ids))
        )
    await db.execute(delete(KbPromptTemplate).where(KbPromptTemplate.kb_id == kb_id))
    # 规则
    await db.execute(delete(KbRule).where(KbRule.kb_id == kb_id))
    # Schema 配置节点 / 模板（级联）
    await db.execute(delete(SchemaConfig).where(SchemaConfig.kb_id == kb_id))
    await db.execute(delete(SchemaTemplate).where(SchemaTemplate.kb_id == kb_id))
    # 全局配置
    await db.execute(delete(KbExtractionConfig).where(KbExtractionConfig.kb_id == kb_id))
    await db.flush()


async def import_snapshot(db: AsyncSession, kb_id: Any, snap: dict[str, Any]) -> None:
    """全量重建：删除当前配置后，按快照恢复（保留原始 id）。"""
    kb = kb_id if isinstance(kb_id, uuid.UUID) else uuid.UUID(str(kb_id))
    await _delete_current(db, kb)

    # 1. 全局
    g = snap.get("global") or {}
    db.add(
        KbExtractionConfig(
            kb_id=kb,
            enabled=bool(g.get("enabled", True)),
            content=g.get("content") or {},
            version=int(g.get("version", 1)),
        )
    )
    await db.flush()

    # 2. 脚本（规则组规则项引用）
    for s in snap.get("scripts") or []:
        db.add(
            KbScript(
                id=_uid(s.get("id")),
                kb_id=kb,
                folder=s.get("folder", "post"),
                name=s.get("name") or "未命名脚本",
                code=s.get("code") or "",
                params_schema=s.get("params_schema") or [],
                enabled=bool(s.get("enabled", True)),
                sort_order=int(s.get("sort_order", 0)),
                description=s.get("description"),
            )
        )
    await db.flush()

    # 4. Schema 模板 + 配置节点（先类别后字段，保证 parent_id 可解析）
    for tpl in snap.get("schema_templates") or []:
        template = SchemaTemplate(
            id=_uid(tpl.get("id")),
            kb_id=kb,
            name=tpl.get("name") or "未命名模板",
            description=tpl.get("description"),
            is_active=bool(tpl.get("is_active", True)),
        )
        db.add(template)
        await db.flush()
        configs = tpl.get("configs") or []
        for _cfg in configs:
            if _cfg.get("node_type") == "category":
                db.add(SchemaConfig(
                    id=_uid(_cfg.get("id")),
                    kb_id=kb,
                    parent_id=_uid(_cfg.get("parent_id")),
                    template_id=template.id,
                    node_type="category",
                    name=_cfg.get("name") or "未命名类别",
                    description=_cfg.get("description"),
                    schema_definition=_cfg.get("schema_definition") or [],
                    sample_fields=_cfg.get("sample_fields") or {},
                    is_active=bool(_cfg.get("is_active", True)),
                    sort_order=int(_cfg.get("sort_order", 0)),
                    return_type=_cfg.get("return_type") or "array",
                    extraction_strategy=_cfg.get("extraction_strategy") or "auto",
                    query_mode=_cfg.get("query_mode") or "fixed",
                    fixed_query=_cfg.get("fixed_query"),
                    confidence_threshold=_cfg.get("confidence_threshold"),
                    top_k=_cfg.get("top_k"),
                    datasets=_cfg.get("datasets") or [],
                    name_source=_cfg.get("name_source") or "manual",
                    name_term_base_id=_uid(_cfg.get("name_term_base_id")),
                    name_term_field=_cfg.get("name_term_field"),
                    query_sources=_cfg.get("query_sources") or [],
                ))
        await db.flush()
        for _cfg in configs:
            if _cfg.get("node_type") == "field":
                db.add(SchemaConfig(
                    id=_uid(_cfg.get("id")),
                    kb_id=kb,
                    parent_id=_uid(_cfg.get("parent_id")),
                    template_id=template.id,
                    node_type="field",
                    name=_cfg.get("name") or "未命名字段",
                    description=_cfg.get("description"),
                    schema_definition=_cfg.get("schema_definition") or [],
                    sample_fields=_cfg.get("sample_fields") or {},
                    is_active=bool(_cfg.get("is_active", True)),
                    sort_order=int(_cfg.get("sort_order", 0)),
                    return_type=_cfg.get("return_type") or "array",
                    extraction_strategy=_cfg.get("extraction_strategy") or "auto",
                    query_mode=_cfg.get("query_mode") or "fixed",
                    fixed_query=_cfg.get("fixed_query"),
                    confidence_threshold=_cfg.get("confidence_threshold"),
                    top_k=_cfg.get("top_k"),
                    datasets=_cfg.get("datasets") or [],
                    name_source=_cfg.get("name_source") or "manual",
                    name_term_base_id=_uid(_cfg.get("name_term_base_id")),
                    name_term_field=_cfg.get("name_term_field"),
                    query_sources=_cfg.get("query_sources") or [],
                ))
    await db.flush()

    # 5. 术语绑定（引用 schema_configs / datasets）
    for b in snap.get("term_bindings") or []:
        db.add(
            KbTermBinding(
                id=_uid(b.get("id")),
                kb_id=kb,
                schema_id=_uid(b.get("schema_id")),
                field_name=b.get("field_name") or "",
                term_base_id=_uid(b.get("term_base_id")),
                config=b.get("config") or {},
            )
        )
    await db.flush()

    # 6. Prompt 模板 + 类别子表（引用 schema_template_id / schema_configs）
    for pt in snap.get("prompt_templates") or []:
        prompt = KbPromptTemplate(
            id=_uid(pt.get("id")),
            kb_id=kb,
            name=pt.get("name") or "未命名模板",
            description=pt.get("description"),
            scope=pt.get("scope") or "simple",
            system_prompt=pt.get("system_prompt") or "",
            user_prompt=pt.get("user_prompt"),
            schema_template_id=_uid(pt.get("schema_template_id")),
            is_active=bool(pt.get("is_active", True)),
        )
        db.add(prompt)
        await db.flush()
        for c in pt.get("categories") or []:
            db.add(
                KbPromptCategory(
                    id=_uid(c.get("id")),
                    kb_id=kb,
                    prompt_template_id=prompt.id,
                    category_id=_uid(c.get("category_id")),
                    user_prompt=c.get("user_prompt") or "",
                    sort_order=int(c.get("sort_order", 0)),
                )
            )
    await db.flush()

    # 7. 规则
    for r in snap.get("rules") or []:
        db.add(
            KbRule(
                id=_uid(r.get("id")),
                kb_id=kb,
                stage=r.get("stage") or "post",
                rule_key=r.get("rule_key") or "unknown",
                name=r.get("name") or "未命名规则",
                description=r.get("description"),
                enabled=bool(r.get("enabled", False)),
                sort_order=int(r.get("sort_order", 0)),
                scope=r.get("scope") or {},
                params=r.get("params") or {},
            )
        )
    await db.flush()

    # 8. 规则组 + 规则项（引用 schema_templates / schema_configs / scripts）
    for g in snap.get("rule_groups") or []:
        group = KbRuleGroup(
            id=_uid(g.get("id")),
            kb_id=kb,
            name=g.get("name"),
            schema_template_id=_uid(g.get("schema_template_id")),
            description=g.get("description"),
        )
        db.add(group)
        await db.flush()
        for i in g.get("items") or []:
            db.add(
                KbRuleGroupItem(
                    id=_uid(i.get("id")),
                    kb_id=kb,
                    rule_group_id=group.id,
                    category_id=_uid(i.get("category_id")),
                    category_name=i.get("category_name") or "",
                    script_id=_uid(i.get("script_id")),
                    stage=i.get("stage") or "post",
                    sort_order=int(i.get("sort_order", 0)),
                )
            )
    await db.flush()


def _rec_key(rec: dict[str, Any]) -> str:
    """差异对比的记录标识：优先 name，其次 id。"""
    name = rec.get("name")
    if name:
        return str(name)
    return str(rec.get("id") or "")


def diff_snapshots(current: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
    """对比当前快照与目标快照，返回各配置域的差异清单。

    返回结构::

        {
          "changed": bool,
          "total": {"added": n, "removed": n, "modified": n},
          "domains": {
            "scripts": {"label": "处理脚本", "added": [...], "removed": [...], "modified": [...]},
            ...
          }
        }
    """
    domains: dict[str, Any] = {}
    total_added = total_removed = total_modified = 0

    for domain in SNAPSHOT_DOMAINS:
        cur = current.get(domain)
        tgt = target.get(domain)
        if domain == "global":
            # 全局配置为单条 dict，整体比较
            modified = []
            if cur != tgt:
                modified = ["全局配置"]
            if modified:
                total_modified += 1
            domains[domain] = {
                "label": DOMAIN_LABELS[domain],
                "added": [],
                "removed": [],
                "modified": modified,
            }
            continue

        cur_list = cur if isinstance(cur, list) else []
        tgt_list = tgt if isinstance(tgt, list) else []
        cur_map = {_rec_key(c): c for c in cur_list}
        tgt_map = {_rec_key(t): t for t in tgt_list}

        added = [k for k in tgt_map if k not in cur_map]
        removed = [k for k in cur_map if k not in tgt_map]
        modified = [
            k for k in tgt_map
            if k in cur_map and (k in added or k in removed) is False and cur_map[k] != tgt_map[k]
        ]
        total_added += len(added)
        total_removed += len(removed)
        total_modified += len(modified)
        domains[domain] = {
            "label": DOMAIN_LABELS[domain],
            "added": added,
            "removed": removed,
            "modified": modified,
        }

    changed = (total_added + total_removed + total_modified) > 0
    return {
        "changed": changed,
        "total": {"added": total_added, "removed": total_removed, "modified": total_modified},
        "domains": domains,
    }