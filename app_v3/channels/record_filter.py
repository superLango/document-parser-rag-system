"""S17 记录质量过滤：冻结口径 v2 记录 + 原生记录的合并规则。"""
from __future__ import annotations

import re
from typing import Any

from app_v3.channels.native_filter import filter_native_records
from app_v3.eval.matcher import grade_match, item_key, numbers

INVALID_GRADE_RE = re.compile(r"^[A-Za-z0-9.\-+/ ]+$|^[\u4e00-\u9fff]+$")


def valid_record(record: dict[str, Any]) -> bool:
    requirement = str(record.get("requirement") or "")
    if "--" in requirement or "—" in requirement:
        return False
    if "text" in requirement.lower() or "牌号" in requirement:
        return False
    grade = str(record.get("grade") or "").strip()
    if not grade:
        return False
    return bool(INVALID_GRADE_RE.fullmatch(grade))


def strong_native_dedupe(native: list[dict[str, Any]], base: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """同(类别,项目,数值)且牌号兼容的原生记录视为 base 已覆盖。"""
    kept: list[dict[str, Any]] = []
    for record in native:
        category = str(record.get("category") or "")
        item = item_key(record.get("item"))
        nums = tuple(numbers(record.get("requirement")))
        grade = str(record.get("grade") or "")
        duplicate = False
        for existing in base:
            if str(existing.get("category") or "") != category or item_key(existing.get("item")) != item:
                continue
            if tuple(numbers(existing.get("requirement"))) != nums:
                continue
            if grade_match(str(existing.get("grade") or ""), grade) or grade_match(grade, str(existing.get("grade") or "")):
                duplicate = True
                break
        if not duplicate:
            kept.append(record)
    return kept


def merge_quality(base: list[dict[str, Any]], native: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    base_valid = [record for record in base if valid_record(record)]
    native_valid = [record for record in native if valid_record(record)]
    native_supported, stats = filter_native_records(native_valid, base_valid)
    native_kept = strong_native_dedupe(native_supported, base_valid)
    stats["native"] = len(native)
    stats["native_valid"] = len(native_valid)
    stats["kept"] = len(native_kept)
    stats["base_valid"] = len(base_valid)
    return base_valid + native_kept, stats
