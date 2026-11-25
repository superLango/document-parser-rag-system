"""牌号脚注清理：OCR 常见牌号尾部脚注字母（如 BZn9-29f → BZn9-29）。

规则：仅当去掉尾部单个小写字母后仍是合法牌号形态时，作为主牌号；原值保留别名。
"""
from __future__ import annotations

import re
from typing import Any

from app_v3.normalize.grade import parse_grade_cell

FOOTNOTE_SUFFIX_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9.\-]*\d[A-Za-z0-9.\-]*?)([a-z])$")


def clean_grade(value: str) -> tuple[str, str]:
    """返回 (清理后牌号, 原值别名或空字符串)。"""
    text = str(value or "").strip()
    if not text:
        return "", ""
    match = FOOTNOTE_SUFFIX_RE.match(text)
    if not match:
        return text, ""
    base = match.group(1)
    # 清理后必须能解析为牌号，避免误删有效字母
    if not parse_grade_cell(base, header="牌号").get("grades"):
        return text, ""
    return base, text


def cleanup_record_grades(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    stats = {"total": len(records), "cleaned": 0, "examples": []}
    for record in records:
        output = dict(record)
        grade = str(record.get("grade") or "")
        new_grade, alias = clean_grade(grade)
        if alias and new_grade != grade:
            output["grade"] = new_grade
            aliases = list(record.get("grade_aliases") or [])
            aliases.append(alias)
            output["grade_aliases"] = list(dict.fromkeys(aliases))
            output["audit"] = dict(record.get("audit") or {})
            output["audit"]["grade_cleanup"] = {"from": grade, "to": new_grade}
            stats["cleaned"] += 1
            if len(stats["examples"]) < 10:
                stats["examples"].append({"record_id": record.get("record_id"), "from": grade, "to": new_grade})
        cleaned.append(output)
    return cleaned, stats
