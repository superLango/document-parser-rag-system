"""E3 Prompt 渲染（对齐前端 PromptEditor 占位符语义）。"""

from __future__ import annotations

import json
import re

from app.core.exceptions import BusinessException
from app.services.extraction.term_base_loader import field_values


def _find_prompt(cfg, template_id: str, category_id: str):
    for p in cfg.prompt_templates:
        if p.get("schema_template_id") != template_id:
            continue
        for c in p.get("categories") or []:
            if c.get("category_id") == category_id:
                return p.get("system_prompt", ""), c.get("user_prompt", "")
    return None


def build_field_defs(target) -> str:
    lines = []
    for f in target.fields or []:
        desc = f.get("description") or f.get("name", "")
        line = f"- {f.get('name')}: {desc}"
        if f.get("required"):
            line += "（必填）"
        lines.append(line)
    return "\n".join(lines)


def render_category(cfg, target, context: str) -> tuple[str, str]:
    """返回 (system, user)，未绑定 Prompt 时抛错。"""
    resolved = _find_prompt(cfg, target.template_id, target.category_id)
    if resolved is None:
        raise BusinessException(
            message=f"未配置类别「{target.feature}」的 Prompt 模板，请先在 Prompt 模板中配置"
        )
    system, user = resolved
    schema_json = json.dumps(target.schema, ensure_ascii=False) if target.schema else ""
    field_map = {f.get("name"): f for f in target.fields if f.get("name")}
    system_values = {
        "feature": target.feature,
        "category_name": target.feature,
        "context": context,
        "field_defs": build_field_defs(target),
        "format_instruction": "只输出 JSON，不要输出解释。",
        "whitelist_section": "",
        "prev_brands_section": "",
        "query_terms": "、".join(target.query_terms or []),
        "feature_descript": target.description,
        "return_type": target.return_type or "array",
        "schema": schema_json,
    }

    def sub(match: re.Match) -> str:
        raw = match.group(1).strip()
        if "." in raw:
            label, attr = raw.split(".", 1)
            if label in (target.term_data or {}):
                vals = field_values(target.term_data[label], attr)
                if vals:
                    return f"[{', '.join(vals)}]"
                return match.group(0)
            if label in field_map:
                f = field_map[label]
                attr_val = {
                    "类型": f.get("type", ""),
                    "必填": "是" if f.get("required") else "否",
                    "描述": f.get("description", ""),
                    "示例": f.get("example", "") or "",
                    "枚举": "",
                    "术语集": "",
                }.get(attr)
                if attr_val is not None:
                    return str(attr_val)
            return match.group(0)
        if raw in field_map:
            return raw
        if raw in system_values:
            return str(system_values[raw])
        return match.group(0)

    def render(text: str) -> str:
        return re.sub(r"\$\{([^{}]+)\}", sub, text or "")

    return render(system), render(user)
