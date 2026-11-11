"""Deterministic built-in recipe engine.

Only the Python standard library is used: this file is copied into the
sandbox runtime image and executed with a read-only root filesystem.
"""

from __future__ import annotations

import re
from typing import Any

FOOTNOTE_RE = re.compile(r"[①-⑳]|\[\d+\]|\(\d+\)|（\d+）|\*+$")
NUMBER_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")
UNIT_RE = re.compile(r"^[A-Za-z%‰°℃Ωμ]+(?:\.[A-Za-z]+)?$")
GRADE_MAX_LEN = 64

MEASURE_ALIASES: dict[str, list[str]] = {
    "Rm": ["抗拉强度", "拉伸强度", "rm", "σb"],
    "Rp0.2": ["屈服强度", "rp0.2", "σ0.2", "屈服"],
    "Rp1.0": ["屈服强度", "rp1.0", "σ1.0"],
    "A": ["断后伸长率", "伸长率", "延伸率", "δs", "δ5"],
    "Z": ["断面收缩率", "收缩率", "ψ"],
    "KU2": ["冲击吸收能量", "冲击功", "ku2", "kv2"],
    "KV2": ["冲击吸收能量", "冲击功", "kv2", "ku2"],
    "KU5": ["冲击吸收能量", "冲击功", "ku5"],
    "HB": ["布氏硬度", "硬度", "hb"],
    "HBW": ["布氏硬度", "硬度", "hbw"],
    "HRC": ["洛氏硬度", "hrc"],
    "HV": ["维氏硬度", "hv"],
    "持久时间": ["持久时间", "持久"],
    "Re": ["屈服强度", "re", "rel"],
}

CONDITION_TOKENS = ("规格", "尺寸", "方向", "试验温度", "温度", "状态", "热处理", "取样", "厚度")
DEFAULT_ROW_KEY = ("牌号", "钢号", "grade", "材料牌号")


def normalize(text: str) -> str:
    return re.sub(r"\s+", "", text or "").lower()


def strip_footnote(text: str) -> str:
    return FOOTNOTE_RE.sub("", (text or "").strip()).strip()


def _header_columns(table: dict[str, Any]) -> tuple[list[str], list[list[str]]]:
    rows = table.get("rows") or []
    header_rows = int(table.get("header_rows") or 1)
    paths = table.get("header_paths") or []
    n_cols = int(table.get("n_cols") or 0)

    if paths:
        headers = [" / ".join(part for part in p if part) for p in paths]
        # TableGrid.rows keeps the header rows; header_paths describes them.
        data = rows[header_rows:] if header_rows > 0 else rows
        return headers, data
    if not rows:
        return [], []
    header_rows = max(1, min(header_rows, len(rows)))
    width = n_cols or max(len(r) for r in rows)
    headers = []
    for col in range(width):
        parts = []
        for row in rows[:header_rows]:
            if col < len(row) and row[col] and row[col] not in parts:
                parts.append(row[col])
        headers.append(" / ".join(parts))
    data = rows[header_rows:]
    return headers, data


def _iter_blocks(table: dict[str, Any]):
    """Yield (block_id, headers, data_rows) for a table or its blocks."""
    headers, data = _header_columns(table)
    if headers and data:
        yield table.get("block_id") or "", headers, data
        return
    for block in table.get("blocks") or []:
        block_table = {
            "rows": block.get("rows") or [],
            "header_rows": block.get("header_rows") or 1,
            "header_paths": block.get("header_paths") or [],
            "n_cols": len(block.get("rows", [[]])[0]) if block.get("rows") else 0,
        }
        block_headers, block_data = _header_columns(block_table)
        if block_headers:
            yield block.get("block_id") or "", block_headers, block_data


def _find_column(headers: list[str], aliases: list[str], used: set[int]) -> int | None:
    normalized = [normalize(h) for h in headers]
    for alias in aliases:
        token = normalize(alias)
        if not token or len(token) < 2:
            continue
        for idx, header in enumerate(normalized):
            if idx in used:
                continue
            if token in header:
                return idx
    return None


def _extract_unit(header: str, explicit: str | None) -> str:
    if "/" in header:
        tail = header.rsplit("/", 1)[-1].strip()
        if tail and len(tail) <= 12 and UNIT_RE.match(tail):
            return tail
    return explicit.strip() if explicit else ""


def _parse_value(cell: str, strip_marks: bool) -> dict[str, Any] | None:
    raw = strip_footnote(cell) if strip_marks else (cell or "").strip()
    if not raw:
        return None
    match = NUMBER_RE.search(raw)
    value = float(match.group()) if match else None
    operator = None
    for candidate in ("≥", "≤", ">", "<", "～", "~"):
        if candidate in raw:
            operator = candidate
            break
    return {"value": value, "raw": raw, "operator": operator}


def _measure_aliases(measure: str) -> list[str]:
    aliases = list(MEASURE_ALIASES.get(measure, []))
    if len(measure) >= 2:
        aliases.insert(0, measure)
    return aliases


def _is_footnote_row(cells: list[str]) -> bool:
    text = "".join(cells).strip()
    if not text:
        return True
    return text.startswith(("注", "注：", "说明", "备注")) or bool(
        re.match(r"^[①-⑳]", text)
    )


def parse_table(
    table: dict[str, Any],
    manifest: dict[str, Any] | None,
    assignment: dict[str, Any] | None,
    diagnostics: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    table_id = str(table.get("table_id") or "unknown")
    page_no = int(table.get("page_no") or 0)
    recipe_id = str((assignment or {}).get("recipe_id") or (manifest or {}).get("recipe_id") or "")
    recipe_version = str(
        (assignment or {}).get("version") or (manifest or {}).get("version") or ""
    )
    profile = str((manifest or {}).get("profile") or table.get("profile") or "unknown")
    bindings = (manifest or {}).get("bindings") or {}
    rules = (manifest or {}).get("rules") or {}
    strip_marks = bool(rules.get("strip_footnote_marks", True))
    units = table.get("units") or []

    records: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    record_count = 0
    row_total = 0

    for block_id, headers, data_rows in _iter_blocks(table):
        used: set[int] = set()
        row_key_tokens = list(bindings.get("row_key") or []) or list(DEFAULT_ROW_KEY)
        key_col = _find_column(headers, row_key_tokens, set())
        if key_col is None:
            diagnostics.append(
                {
                    "code": "ROW_KEY_NOT_FOUND",
                    "message": f"table {table_id} has no row-key column",
                    "severity": "warning",
                    "detail": {"table_id": table_id, "headers": headers},
                }
            )
            key_col = 0
        used.add(key_col)

        measure_cols: dict[str, int] = {}
        for measure in (bindings.get("measures") or {}):
            col = _find_column(headers, _measure_aliases(str(measure)), used)
            if col is None:
                diagnostics.append(
                    {
                        "code": "MEASURE_COLUMN_MISSING",
                        "message": f"measure {measure} not found in table {table_id}",
                        "severity": "warning",
                        "detail": {"table_id": table_id, "measure": str(measure)},
                    }
                )
                continue
            used.add(col)
            measure_cols[str(measure)] = col

        condition_cols: dict[str, int] = {}
        for token in bindings.get("conditions") or []:
            col = _find_column(headers, [str(token)], used)
            if col is not None:
                used.add(col)
                condition_cols[str(token)] = col

        for row_index, row in enumerate(data_rows):
            row_total += 1
            if _is_footnote_row(row):
                continue
            grade_cell = row[key_col] if key_col < len(row) else ""
            grade = strip_footnote(grade_cell) if strip_marks else (grade_cell or "").strip()
            if not grade or len(grade) > GRADE_MAX_LEN:
                diagnostics.append(
                    {
                        "code": "ROW_SKIPPED",
                        "message": "row skipped: empty or invalid row key",
                        "severity": "info",
                        "detail": {"table_id": table_id, "row_index": row_index},
                    }
                )
                continue

            conditions = {
                name: strip_footnote(row[col])
                for name, col in sorted(condition_cols.items())
                if col < len(row) and strip_footnote(row[col])
            }
            properties: dict[str, Any] = {}
            for measure, col in sorted(measure_cols.items()):
                cell = row[col] if col < len(row) else ""
                parsed = _parse_value(cell, strip_marks)
                if parsed is None:
                    continue
                explicit_unit = units[0] if len(units) == 1 else None
                parsed["unit"] = _extract_unit(headers[col], explicit_unit)
                parsed["column"] = headers[col]
                properties[measure] = parsed

            record_count += 1
            record_id = f"{table_id}-R{row_index + 1}"
            record = {
                "record_id": record_id,
                "table_id": table_id,
                "block_id": block_id,
                "page_no": page_no,
                "row_index": row_index,
                "recipe_id": recipe_id,
                "recipe_version": recipe_version,
                "profile": profile,
                "grade": grade,
                "conditions": conditions,
                "properties": properties,
                "evidence_refs": [record_id],
                "source": {
                    "table_id": table_id,
                    "block_id": block_id,
                    "page_no": page_no,
                    "row_index": row_index,
                },
            }
            records.append(record)
            evidence.append(
                {
                    "evidence_id": record_id,
                    "table_id": table_id,
                    "block_id": block_id,
                    "page_no": page_no,
                    "row_index": row_index,
                    "raw_row": list(row),
                    "cells": {
                        headers[idx]: row[idx]
                        for idx in range(min(len(headers), len(row)))
                        if row[idx]
                    },
                }
            )

    if not records:
        diagnostics.append(
            {
                "code": "NO_RECORDS",
                "message": f"table {table_id} produced no records",
                "severity": "warning",
                "detail": {"table_id": table_id},
            }
        )

    summary = {
        "table_id": table_id,
        "page_no": page_no,
        "profile": profile,
        "recipe_id": recipe_id,
        "recipe_version": recipe_version,
        "rows": row_total,
        "records": len(records),
    }
    return records, evidence, summary
