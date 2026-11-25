"""表格程序 DSL 执行引擎（P1 WP1.2）。

确定性执行 melt/explode/pivot/rename/filter，产出可校验记录；不调用模型。
"""
from __future__ import annotations

import re
from typing import Any

from .ir import TableIR

DEFAULT_SKIP = {"", "-", "—", "–", "/", "不规定"}
DEFAULT_DELIMITERS = r"[、,，;；/|]+"


def _split_cell(value: str, pattern: str | None = None) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    return [part.strip() for part in re.split(pattern or DEFAULT_DELIMITERS, text) if part.strip()]


def execute_program(program: dict[str, Any], ir: TableIR) -> list[dict[str, Any]]:
    rows = [{"__row__": row_index, "cells": list(row)} for row_index, row in ir.data_rows]
    for step in program.get("steps") or []:
        op = str(step.get("op") or "")
        if op == "explode":
            column = int(step.get("column") or 0)
            pattern = step.get("delimiter")
            expanded: list[dict[str, Any]] = []
            for row in rows:
                parts = _split_cell(row["cells"][column] if column < len(row["cells"]) else "", pattern)
                if not parts:
                    continue
                for part in parts:
                    clone = {"__row__": row["__row__"], "cells": list(row["cells"])}
                    clone["cells"][column] = part
                    expanded.append(clone)
            rows = expanded
        elif op == "filter":
            skip = set(step.get("skip_values") or DEFAULT_SKIP)
            column = step.get("column")
            filtered = []
            for row in rows:
                if column is None:
                    filtered.append(row)
                    continue
                value = row["cells"][int(column)] if int(column) < len(row["cells"]) else ""
                if "delimiter" in step:
                    values = _split_cell(value, step.get("delimiter"))
                else:
                    values = [value]
                if any(str(item).strip() not in skip for item in values):
                    filtered.append(row)
            rows = filtered
        elif op == "melt":
            records: list[dict[str, Any]] = []
            id_columns = [int(column) for column in step.get("id_columns") or []]
            skip = set(step.get("skip_values") or DEFAULT_SKIP)
            for row in rows:
                for spec in step.get("value_columns") or []:
                    column = int(spec.get("column") or 0)
                    raw = str(row["cells"][column] if column < len(row["cells"]) else "").strip()
                    if raw in skip:
                        continue
                    key_values = {str(index): row["cells"][index] if index < len(row["cells"]) else ""
                                  for index in id_columns}
                    records.append({
                        "source_row": row["__row__"],
                        "source_column": column,
                        "key_values": key_values,
                        "raw": raw,
                        "measure": str(spec.get("measure") or ""),
                        "unit": str(spec.get("unit") or ""),
                        "operator": spec.get("operator"),
                        "conditions": dict(spec.get("conditions") or {}),
                        "category": str(spec.get("category") or ""),
                    })
            return records
        elif op == "rename":
            mapping = {int(key): str(value) for key, value in (step.get("mapping") or {}).items()}
            # rename 仅影响后续 spec，不改变行；由调用方在 program 中体现
            continue
        elif op == "pivot":
            records = []
            index_columns = [int(column) for column in step.get("index") or []]
            value_columns = [int(column) for column in step.get("values") or []]
            specs = {int(spec.get("column") or 0): spec for spec in step.get("value_columns") or []}
            for row in rows:
                key_values = {str(index): row["cells"][index] if index < len(row["cells"]) else ""
                              for index in index_columns}
                for column in value_columns:
                    raw = str(row["cells"][column] if column < len(row["cells"]) else "").strip()
                    if raw in DEFAULT_SKIP:
                        continue
                    spec = specs.get(column, {})
                    records.append({
                        "source_row": row["__row__"],
                        "source_column": column,
                        "key_values": key_values,
                        "raw": raw,
                        "measure": str(spec.get("measure") or ""),
                        "unit": str(spec.get("unit") or ""),
                        "operator": spec.get("operator"),
                        "conditions": dict(spec.get("conditions") or {}),
                        "category": str(spec.get("category") or ""),
                    })
            return records
        else:
            raise ValueError(f"unsupported op: {op}")
    return []


def records_to_flat(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把引擎记录转换为可评测/可验证的扁平记录。"""
    flat: list[dict[str, Any]] = []
    for record in records:
        key_values = record.get("key_values") or {}
        flat.append({
            "category": record.get("category") or "",
            "item": record.get("measure") or "",
            "grade": next(iter(key_values.values()), ""),
            "requirement": record.get("raw") or "",
            "unit": record.get("unit") or "",
            "conditions": record.get("conditions") or {},
            "source_table": "",
            "raw": record.get("raw"),
        })
    return flat
