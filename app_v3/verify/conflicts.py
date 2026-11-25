"""冲突检测：同键不同值、重复记录。"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import Any

ROW_RE = re.compile(r"-R(\d+)-C\d+")
NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
CONDITIONAL_CATEGORIES = {"室温拉伸", "高温拉伸", "冲击试验", "硬度试验", "持久试验", "蠕变试验",
                          "弯曲试验", "高倍", "热处理制度"}
CONDITION_FIELDS = ("试验温度", "试样状态", "尺寸厚度", "方向", "位置")


def _has_conditions(record: dict[str, Any]) -> bool:
    conditions = record.get("conditions") or {}
    return any(str(conditions.get(field) or "").strip() for field in CONDITION_FIELDS)


def _location(record: dict[str, Any]) -> tuple[str, int | None]:
    table_id = str(record.get("source_table") or "")
    if not table_id:
        evidence = record.get("evidence") or {}
        ref = (evidence.get("requirement") or {}).get("ref") if isinstance(evidence, dict) else {}
        if isinstance(ref, dict):
            table_id = str(ref.get("table_id") or "")
    match = ROW_RE.search(str(record.get("record_id") or ""))
    row = int(match.group(1)) if match else None
    return table_id, row


def _key(record: dict[str, Any]) -> tuple:
    return (
        str(record.get("category") or ""),
        str(record.get("item") or ""),
        str(record.get("grade") or ""),
        json.dumps(record.get("conditions") or {}, sort_keys=True, ensure_ascii=False),
    )


def detect_conflicts(records: list[dict[str, Any]]) -> tuple[dict[int, list[dict[str, Any]]], list[dict[str, Any]]]:
    """返回 (index -> diagnostics, 冲突摘要列表)。"""
    groups: dict[tuple, list[tuple[int, set[str]]]] = defaultdict(list)
    for index, record in enumerate(records):
        numbers = set(NUMBER_RE.findall(str(record.get("requirement") or "")))
        groups[_key(record)].append((index, numbers))
    diagnostics: dict[int, list[dict[str, Any]]] = defaultdict(list)
    summaries: list[dict[str, Any]] = []
    for key, items in groups.items():
        value_sets = {frozenset(numbers) for _, numbers in items}
        if len(items) > 1 and len(value_sets) > 1:
            group_records = [records[index] for index, _ in items]
            category = str(key[0] or "")
            insufficient = category in CONDITIONAL_CATEGORIES and not all(_has_conditions(record) for record in group_records)
            locations = {_location(record) for record in group_records}
            same_row = len(locations) == 1 and None not in {row for _, row in locations}
            if same_row:
                code = "same_row_value_conflict"
                severity = "warn"
            elif insufficient:
                code = "value_conflict_insufficient_conditions"
                severity = "warn"
            else:
                code = "value_conflict"
                severity = "error"
            summary = {"key": list(key), "records": [index for index, _ in items],
                       "values": [sorted(numbers) for _, numbers in items],
                       "severity": severity}
            summaries.append(summary)
            for index, _ in items:
                diagnostics[index].append({
                    "code": code, "field": "requirement", "severity": severity,
                    "message": "同一键存在不同要求值" + ("（条件不足，先复核条件）" if insufficient else ""),
                })
        elif len(items) > 1:
            summaries.append({"key": list(key), "records": [index for index, _ in items],
                              "values": [sorted(numbers) for _, numbers in items], "duplicate": True})
    return dict(diagnostics), summaries
