"""L1 table repair: validated, bounded spec applied to an OCR table copy."""

from __future__ import annotations

import copy
import re
from typing import Any

ALLOWED_KEYS = {"header_rows", "replace_rows", "patch_cells", "delete_rows"}
MAX_ROWS = 80
MAX_CELLS = 200
NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")


def _table_text(table: dict[str, Any]) -> str:
    parts = [str(table.get("caption") or "")]
    for row in table.get("rows") or []:
        parts.extend(str(cell) for cell in row)
    for path in table.get("header_paths") or []:
        parts.extend(str(cell) for cell in path)
    return " ".join(parts)


def _as_index(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def validate_table_repair_spec(
    spec: dict[str, Any] | None, table: dict[str, Any]
) -> tuple[dict[str, Any] | None, list[str]]:
    """Validate a model-proposed table repair; reject fabricated or out-of-range edits."""
    if not isinstance(spec, dict):
        return None, ["spec 不是对象"]
    rows = table.get("rows") if isinstance(table.get("rows"), list) else []
    n_rows = len(rows)
    n_cols = max((len(row) for row in rows), default=0)
    source_numbers = set(NUMBER_RE.findall(_table_text(table)))
    problems: list[str] = []
    clean: dict[str, Any] = {}

    unknown = set(spec) - ALLOWED_KEYS
    if unknown:
        problems.append("不支持的字段：" + ",".join(sorted(unknown)))

    header_rows = spec.get("header_rows")
    if header_rows is not None:
        index = _as_index(header_rows)
        if index is None or index < 0 or index > n_rows:
            problems.append("header_rows 越界")
        else:
            clean["header_rows"] = index

    replace_rows = spec.get("replace_rows")
    if isinstance(replace_rows, list):
        # Tolerate [{"row_index": 1, "cells": [...]}] as well as {"1": [...]}.
        replace_rows = {
            str(item.get("row_index")): item.get("cells")
            for item in replace_rows
            if isinstance(item, dict) and item.get("row_index") is not None
        }
    if replace_rows is not None:
        if not isinstance(replace_rows, dict):
            problems.append("replace_rows 不是对象")
        else:
            parsed: dict[str, list[str]] = {}
            for key, value in list(replace_rows.items())[:MAX_ROWS]:
                index = _as_index(key)
                if index is None or index < 0 or index >= n_rows:
                    problems.append(f"replace_rows 行号越界：{key}")
                    continue
                if not isinstance(value, list) or not value:
                    problems.append(f"replace_rows[{key}] 不是非空数组")
                    continue
                if len(value) > max(n_cols, 1) + 4:
                    problems.append(f"replace_rows[{key}] 列数超限")
                    continue
                parsed[str(index)] = [str(cell) for cell in value]
            clean["replace_rows"] = parsed

    patch_cells = spec.get("patch_cells")
    if patch_cells is not None:
        if not isinstance(patch_cells, dict):
            problems.append("patch_cells 不是对象")
        else:
            parsed_cells: dict[str, dict[str, str]] = {}
            total = 0
            for row_key, cells in list(patch_cells.items())[:MAX_ROWS]:
                row_index = _as_index(row_key)
                if row_index is None or row_index < 0 or row_index >= n_rows:
                    problems.append(f"patch_cells 行号越界：{row_key}")
                    continue
                if not isinstance(cells, dict):
                    problems.append(f"patch_cells[{row_key}] 不是对象")
                    continue
                parsed_row: dict[str, str] = {}
                for col_key, value in cells.items():
                    col_index = _as_index(col_key)
                    if col_index is None or col_index < 0 or col_index >= max(n_cols, 1) + 4:
                        problems.append(f"patch_cells 列号越界：{row_key}/{col_key}")
                        continue
                    parsed_row[str(col_index)] = str(value)
                    total += 1
                parsed_cells[str(row_index)] = parsed_row
            if total > MAX_CELLS:
                problems.append(f"patch_cells 超过 {MAX_CELLS} 个单元格")
            clean["patch_cells"] = parsed_cells

    delete_rows = spec.get("delete_rows")
    if delete_rows is not None:
        if not isinstance(delete_rows, list):
            problems.append("delete_rows 不是数组")
        else:
            parsed_delete = []
            for item in delete_rows:
                index = _as_index(item)
                if index is None or index < 0 or index >= n_rows:
                    problems.append(f"delete_rows 行号越界：{item}")
                    continue
                parsed_delete.append(index)
            if parsed_delete and len(parsed_delete) >= n_rows:
                problems.append("delete_rows 不能删除全部数据行")
            clean["delete_rows"] = sorted(set(parsed_delete))

    introduced: set[str] = set()
    for value in (clean.get("replace_rows") or {}).values():
        for cell in value:
            introduced.update(NUMBER_RE.findall(cell))
    for cells in (clean.get("patch_cells") or {}).values():
        for cell in cells.values():
            introduced.update(NUMBER_RE.findall(cell))
    fabricated = sorted(number for number in introduced if number not in source_numbers)
    if fabricated:
        problems.append("编造源表不存在的数据：" + ",".join(fabricated[:5]))

    if problems:
        return None, problems
    return clean, []


def apply_table_repair(table: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    """Return a repaired copy of the table (never mutates the original)."""
    repaired = copy.deepcopy(table)
    repaired["_original_table_id"] = table.get("table_id")
    rows = [
        list(row)
        for row in (repaired.get("rows") if isinstance(repaired.get("rows"), list) else [])
    ]
    if "header_rows" in spec:
        repaired["header_rows"] = spec["header_rows"]
    for row_key, row in (spec.get("replace_rows") or {}).items():
        index = int(row_key)
        if 0 <= index < len(rows):
            rows[index] = list(row)
    for row_key, cells in (spec.get("patch_cells") or {}).items():
        index = int(row_key)
        if not (0 <= index < len(rows)):
            continue
        for col_key, value in cells.items():
            col = int(col_key)
            while len(rows[index]) <= col:
                rows[index].append("")
            rows[index][col] = value
    for index in sorted(spec.get("delete_rows") or [], reverse=True):
        if 0 <= index < len(rows):
            rows.pop(index)
    repaired["rows"] = rows
    repaired["n_rows"] = len(rows)
    return repaired


def extract_table_repair(
    patch: dict[str, Any] | None, default_table_id: str = ""
) -> tuple[str, dict[str, Any] | None]:
    """Read a table repair payload from a proposal patch in any supported shape."""
    if not isinstance(patch, dict):
        return default_table_id, None
    payload = patch.get("table_repair")
    if isinstance(payload, dict):
        return str(payload.get("table_id") or default_table_id), (
            payload.get("spec") if isinstance(payload.get("spec"), dict) else None
        )
    if patch.get("operator") == "table_repair.add":
        params = patch.get("params") or {}
        return str(params.get("table_id") or default_table_id), (
            params.get("spec") if isinstance(params.get("spec"), dict) else None
        )
    if isinstance(patch.get("spec"), dict):
        return default_table_id, patch["spec"]
    return default_table_id, None


def apply_table_repair_to_ocr(
    ocr: dict[str, Any], table_id: str, spec: dict[str, Any]
) -> dict[str, Any]:
    """Return an OCR payload copy with one table repaired."""
    payload = copy.deepcopy(ocr)
    for table in payload.get("tables") or []:
        if str(table.get("table_id") or "") != table_id:
            continue
        repaired = apply_table_repair(table, spec)
        repaired["table_id"] = table_id
        table.clear()
        table.update(repaired)
        payload["_table_repair"] = {"table_id": table_id, "spec": spec}
        return payload
    raise ValueError(f"table not found: {table_id}")
