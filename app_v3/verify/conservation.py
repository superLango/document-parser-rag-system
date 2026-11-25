"""值守恒：记录值必须能在来源表中找到。"""
from __future__ import annotations

import re
from typing import Any

ROW_RE = re.compile(r"-R(\d+)-C\d+")
NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")


def _table_id(record: dict[str, Any]) -> str:
    if record.get("source_table"):
        return str(record["source_table"])
    evidence = record.get("evidence") or {}
    if isinstance(evidence, dict) and evidence.get("table_id"):
        return str(evidence["table_id"])
    ref = (evidence.get("requirement") or {}).get("ref") if isinstance(evidence, dict) else {}
    if isinstance(ref, dict) and ref.get("table_id"):
        return str(ref["table_id"])
    return ""


def _row_index(record: dict[str, Any]) -> int | None:
    if isinstance(record.get("row_index"), int):
        return int(record["row_index"])
    match = ROW_RE.search(str(record.get("record_id") or ""))
    return int(match.group(1)) if match else None


def _raw_value(record: dict[str, Any]) -> str:
    audit = record.get("audit") or {}
    if isinstance(audit, dict) and audit.get("raw"):
        return str(audit["raw"])
    requirement = str(record.get("requirement") or "")
    requirement = re.sub(r"^[≥≤<>=\s]+", "", requirement)
    return requirement


def validate_conservation(record: dict[str, Any], tables: dict[str, Any]) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    if str(record.get("category") or "") == "标准信息":
        return diagnostics
    table_id = _table_id(record)
    row_index = _row_index(record)
    table = tables.get(table_id)
    if table is None or row_index is None:
        return diagnostics
    rows = table.get("rows") or []
    if row_index >= len(rows):
        diagnostics.append({"code": "row_out_of_range", "field": "row", "severity": "error",
                            "message": f"行号越界: {row_index}"})
        return diagnostics
    row_values = [str(cell) for cell in rows[row_index]]
    raw = _raw_value(record)
    if not raw:
        return diagnostics
    raw_numbers = set(NUMBER_RE.findall(raw))
    row_numbers = set(NUMBER_RE.findall(" ".join(row_values)))
    if raw_numbers and not raw_numbers.issubset(row_numbers):
        diagnostics.append({"code": "value_not_in_source", "field": "requirement", "severity": "error",
                            "message": f"记录值不在来源行中: {raw[:40]}"})
    elif raw and raw not in " ".join(row_values) and not raw_numbers:
        diagnostics.append({"code": "value_not_in_source", "field": "requirement", "severity": "warn",
                            "message": f"记录原值未精确命中来源行: {raw[:40]}"})
    return diagnostics
