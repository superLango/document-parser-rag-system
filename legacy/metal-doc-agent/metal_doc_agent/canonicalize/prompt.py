"""Prompt whitelist rendering for dictionary-assisted extraction."""

from __future__ import annotations

from .dictionary import DictionaryIndex

PLACEHOLDERS = ("${whitelist_section}", "${query_terms}", "${item_facets}")


def build_whitelist(
    index: DictionaryIndex,
    families: list[str] | None = None,
    *,
    max_items: int = 60,
) -> dict:
    selected = []
    for entry in index.dictionary.entries:
        if entry.status != "active" or entry.type not in {"category", "item"}:
            continue
        if families and entry.family not in families:
            continue
        selected.append(entry)
    selected.sort(key=lambda entry: (entry.type, entry.family or "", entry.business_name))
    selected = selected[:max_items]
    methods = [
        entry
        for entry in index.dictionary.entries
        if entry.status == "active" and entry.type == "method"
    ][:max_items]
    return {
        "items": [
            {
                "code": entry.business_code,
                "name": entry.business_name,
                "type": entry.type,
                "category": entry.category_name,
                "family": entry.family,
                "aliases": entry.aliases,
            }
            for entry in selected
        ],
        "methods": [
            {
                "code": entry.business_code,
                "name": entry.business_name,
                "standard_no": entry.standard_no,
            }
            for entry in methods
        ],
    }


def render_prompt(
    template: str,
    whitelist: dict,
    *,
    query_terms: list[str] | None = None,
    facets: dict[str, str] | None = None,
) -> str:
    lines = [
        f"- {item['code']} {item['name']}（{item['family'] or '未分类'}）"
        for item in whitelist.get("items", [])
    ]
    lines.extend(
        f"- {method['code']} {method['name']} {method.get('standard_no') or ''}".rstrip()
        for method in whitelist.get("methods", [])
    )
    query_text = "、".join(query_terms or [])
    facet_text = "；".join(
        f"{key}={value}" for key, value in (facets or {}).items()
    )
    rendered = template
    rendered = rendered.replace("${whitelist_section}", "\n".join(lines))
    rendered = rendered.replace("${query_terms}", query_text)
    rendered = rendered.replace("${item_facets}", facet_text)
    return rendered


def prompt_terms(whitelist: dict) -> set[str]:
    return {
        item["name"]
        for item in whitelist.get("items", [])
    } | {
        method["name"]
        for method in whitelist.get("methods", [])
    }
