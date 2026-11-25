"""S17 原生记录过滤：只保留与既有通道（S9）同 (类别,项目) 的原生记录，并按值键去重。

理由：原生通道精度高但"多而不精"。当原生记录的项目在既有通道中完全不存在时，
多属于模型把非规范内容（如热处理制度、自由文本）误当度量列，优先丢弃。
"""
from __future__ import annotations

import json
from typing import Any

from app_v3.eval.matcher import item_key, norm_grade, numbers


def _record_key(record: dict[str, Any]) -> tuple:
    return (
        str(record.get("category") or ""),
        item_key(record.get("item")),
        norm_grade(record.get("grade")),
        tuple(numbers(record.get("requirement"))),
    )


def filter_native_records(native: list[dict[str, Any]], base: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    base_items = {(str(record.get("category") or ""), item_key(record.get("item"))) for record in base}
    seen = {_record_key(record) for record in base}
    kept: list[dict[str, Any]] = []
    stats = {"native": len(native), "kept": 0, "dropped_item": 0, "dropped_duplicate": 0}
    for record in native:
        category = str(record.get("category") or "")
        item = item_key(record.get("item"))
        key = _record_key(record)
        if (category, item) not in base_items:
            stats["dropped_item"] += 1
            continue
        if key in seen:
            stats["dropped_duplicate"] += 1
            continue
        seen.add(key)
        kept.append(record)
    stats["kept"] = len(kept)
    return kept, stats


def filter_and_merge(base: list[dict[str, Any]], native: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    kept, stats = filter_native_records(native, base)
    return base + kept, stats
