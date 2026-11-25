"""冲突检测：同键不同值、重复记录。"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import Any

NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")


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
            summary = {"key": list(key), "records": [index for index, _ in items],
                       "values": [sorted(numbers) for _, numbers in items]}
            summaries.append(summary)
            for index, _ in items:
                diagnostics[index].append({
                    "code": "value_conflict", "field": "requirement", "severity": "error",
                    "message": "同一键（类别/项目/牌号/条件）存在不同要求值",
                })
        elif len(items) > 1:
            summaries.append({"key": list(key), "records": [index for index, _ in items],
                              "values": [sorted(numbers) for _, numbers in items], "duplicate": True})
    return dict(diagnostics), summaries
