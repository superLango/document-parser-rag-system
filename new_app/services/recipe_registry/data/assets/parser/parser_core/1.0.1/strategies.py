"""Deterministic matrix strategies for tables that column bindings miss.

Ported from the legacy ``metal_doc_agent/extraction/matrix.py`` extractors and
rewritten against the sandbox ``TableGrid``/record contract.  The strategies are
pure functions over a table dict and are only invoked when the bound column
parser in :mod:`builtin` produced no records.

Strategy order (overridable via the recipe ``strategy_chain`` field):

1. ``property_matrix``      - properties as rows, temperature/direction columns
2. ``grade_property_matrix``- grades as rows, one column per property
3. ``property_rows``        - vertical ``Property | Value`` tables
4. ``hardness_minmax``      - hardness columns with min/max bounds
"""

from __future__ import annotations

import re
from typing import Any

try:  # imported as a package (tests)
    from .builtin import (
        MEASURE_ALIASES,
        SYMBOL_CANON,
        _detect_measure,
        _extract_unit,
        _grade_valid,
        _header_columns,
        _is_footnote_row,
        _parse_value,
        _split_grades,
        normalize,
        strip_footnote,
    )
except ImportError:  # flat runtime image (/engine)
    from builtin import (  # type: ignore[no-redef]
        MEASURE_ALIASES,
        SYMBOL_CANON,
        _detect_measure,
        _extract_unit,
        _grade_valid,
        _header_columns,
        _is_footnote_row,
        _parse_value,
        _split_grades,
        normalize,
        strip_footnote,
    )

DEFAULT_CHAIN = (
    "property_matrix",
    "grade_property_matrix",
    "property_rows",
    "hardness_minmax",
)

TEMPERATURE_RE = re.compile(r"(室温|常温|低温|高温|-?\d+(?:\.\d+)?\s*[℃°C])")
LABEL_HEADER_RE = re.compile(r"性能|检验项目|试验项目|项目|property|properties", re.IGNORECASE)
GRADE_HEADER_RE = re.compile(r"牌号|钢号|grade|designation|材料", re.IGNORECASE)
VALUE_HEADER_RE = re.compile(
    r"\b(?:value|requirement|limit|minimum|maximum|min|max)\b|值|要求|指标",
    re.IGNORECASE,
)
HARDNESS_HEADER_RE = re.compile(r"硬度|hardness|hbw?|hr[abc]|hv", re.IGNORECASE)
MIN_RE = re.compile(r"最小值|最小|(?<![a-z])min(?:imum)?(?![a-z])", re.IGNORECASE)
MAX_RE = re.compile(r"最大值|最大|(?<![a-z])max(?:imum)?(?![a-z])", re.IGNORECASE)
PROPERTY_HINT_RE = re.compile(
    r"tensile|yield|proof|elongation|reduction|hardness|impact|strength|"
    r"抗拉|屈服|伸长|收缩|硬度|冲击|延伸|持久|蠕变|弹性模量",
    re.IGNORECASE,
)
UNIT_LABEL_RE = re.compile(
    r"[（(]\s*(MPa|GPa|%|J|HBW?|HBS|HRC|HRB|HV)\s*[）)]", re.IGNORECASE
)
SKIP_VALUES = {"", "-", "—", "–", "/", "…", "..."}
DEFAULT_UNITS = {
    "Rm": "MPa",
    "Rp0.2": "MPa",
    "Rp1.0": "MPa",
    "ReH": "MPa",
    "ReL": "MPa",
    "A": "%",
    "Z": "%",
    "KV2": "J",
    "KU2": "J",
    "KU5": "J",
    "HB": "HBW",
    "HBW": "HBW",
    "HRC": "HRC",
    "HRB": "HRB",
    "HV": "HV",
}
HARDNESS_SYMBOL_RE = re.compile(r"hbw|hbs|hb|hrc|hrb|hv", re.IGNORECASE)


def _headers(table: dict[str, Any]) -> tuple[list[str], list[list[str]]]:
    return _header_columns(table)


def _label_measure(label: str) -> str:
    """Map a Chinese/English property label to the recipe measure symbol."""
    text = normalize(label)
    if not text:
        return ""
    text = re.sub(r"[（(].*?[）)]", "", text)
    best: tuple[str, int] | None = None
    for measure, aliases in MEASURE_ALIASES.items():
        for alias in (measure, *aliases):
            token = normalize(alias)
            if not token:
                continue
            if len(token) <= 4 and re.fullmatch(r"[a-z0-9.]+", token):
                # Short ASCII symbols (A, E, C, P, ReL, HBW...) must be
                # standalone tokens: "Other Elements" must not match "rel".
                if not re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", text):
                    continue
            elif token not in text:
                continue
            if best is None or len(token) > best[1]:
                best = (measure, len(token))
    return best[0] if best else ""


def _unit(header: str, label: str, measure: str) -> str:
    return _extract_unit(f"{header} {label}", None) or DEFAULT_UNITS.get(measure, "")


def _measure_allowed(ctx: dict[str, Any], measure: str) -> bool:
    """Only emit measures the routed recipe actually binds.

    Element aliases (H/N/O/Si/Ni...) exist in ``MEASURE_ALIASES`` for chemistry
    tables; without this gate a mechanical recipe would read a composition
    table as as a property matrix.
    """
    allowed = ctx.get("measures") or []
    return not allowed or measure in allowed


def _value(cell: str) -> dict[str, Any] | None:
    if (cell or "").strip() in SKIP_VALUES:
        return None
    parsed = _parse_value(cell, True)
    if parsed is None or parsed.get("value") is None:
        return None
    raw = str(parsed.get("raw") or "")
    if not parsed.get("operator"):
        if MAX_RE.search(raw):
            parsed["operator"] = "≤"
        elif MIN_RE.search(raw):
            parsed["operator"] = "≥"
    return parsed


def _grade_cell(cell: str) -> str:
    text = strip_footnote(cell or "").strip()
    if not text:
        return ""
    grades = [item for item in _split_grades(text) if _grade_valid(item, allow_numeric=True)]
    return grades[0] if grades else ""


def _build(
    table: dict[str, Any],
    ctx: dict[str, Any],
    *,
    row: list[str],
    row_index: int,
    col: int,
    grade: str,
    conditions: dict[str, str],
    measure: str,
    parsed: dict[str, Any],
    unit: str,
    column: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    table_id = str(table.get("table_id") or "unknown")
    page_no = int(table.get("page_no") or 0)
    block_id = str(table.get("block_id") or "")
    record_id = f"{table_id}-M{row_index + 1}-C{col + 1}"
    properties = {measure: dict(parsed)}
    properties[measure]["unit"] = unit
    properties[measure]["column"] = column
    record = {
        "record_id": record_id,
        "table_id": table_id,
        "block_id": block_id,
        "page_no": page_no,
        "row_index": row_index,
        "recipe_id": ctx.get("recipe_id") or "",
        "recipe_version": ctx.get("recipe_version") or "",
        "profile": ctx.get("profile") or "unknown",
        "grade": grade or "~",
        "grade_raw": None,
        "conditions": conditions,
        "condition_key": "|".join(
            sorted(normalize(value) for value in conditions.values() if value)
        ),
        "properties": properties,
        "evidence_refs": [record_id],
        "source": {
            "table_id": table_id,
            "block_id": block_id,
            "page_no": page_no,
            "row_index": row_index,
        },
    }
    evidence = {
        "evidence_id": record_id,
        "table_id": table_id,
        "block_id": block_id,
        "page_no": page_no,
        "row_index": row_index,
        "raw_row": list(row),
        "cells": {column: parsed.get("raw") or ""},
    }
    return record, evidence


def _row(data: list[list[str]], index: int) -> list[str]:
    return data[index] if index < len(data) else []


def property_matrix(
    table: dict[str, Any], ctx: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]] | None:
    """Read ``属性 x 温度/方向`` matrices into per-property records."""
    headers, data = _headers(table)
    if len(headers) < 2 or not data:
        return None
    label_col = next(
        (index for index, header in enumerate(headers) if LABEL_HEADER_RE.search(header)),
        None,
    )
    if label_col is None:
        return None
    condition_cols = [
        (index, match.group(1).strip())
        for index, header in enumerate(headers)
        if index != label_col
        for match in [TEMPERATURE_RE.search(header)]
        if match
    ]
    if not condition_cols:
        return None
    grade_col = next(
        (
            index
            for index, header in enumerate(headers)
            if index != label_col and GRADE_HEADER_RE.search(header)
        ),
        None,
    )
    records: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    for row_index in range(len(data)):
        row = _row(data, row_index)
        if _is_footnote_row(row):
            continue
        label = row[label_col] if label_col < len(row) else ""
        measure = _label_measure(label)
        if not measure or not _measure_allowed(ctx, measure):
            continue
        grade = _grade_cell(row[grade_col]) if grade_col is not None else ""
        for col, condition in condition_cols:
            cell = row[col] if col < len(row) else ""
            parsed = _value(cell)
            if parsed is None:
                continue
            record, item = _build(
                table,
                ctx,
                row=row,
                row_index=row_index,
                col=col,
                grade=grade,
                conditions={"温度": condition},
                measure=measure,
                parsed=parsed,
                unit=_unit(headers[col], label, measure),
                column=headers[col],
            )
            records.append(record)
            evidence.append(item)
    return (records, evidence) if records else None


def grade_property_matrix(
    table: dict[str, Any], ctx: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]] | None:
    """Read ``牌号 x 性能`` matrices where every property is its own column."""
    headers, data = _headers(table)
    if len(headers) < 3 or not data:
        return None
    measure_cols: list[tuple[int, str, str]] = []
    grade_col = next(
        (
            index
            for index, header in enumerate(headers)
            if GRADE_HEADER_RE.search(header)
        ),
        None,
    )
    for index, header in enumerate(headers):
        if index == grade_col:
            continue
        measure = _label_measure(header)
        if measure and _measure_allowed(ctx, measure):
            measure_cols.append((index, measure, header))
    if len(measure_cols) < 2:
        return None
    first_value = min(index for index, _, _ in measure_cols)
    if grade_col is None:
        grade_col = next(
            (
                index
                for index, header in enumerate(headers[:first_value])
                if GRADE_HEADER_RE.search(header)
            ),
            0,
        )
    records: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    for row_index in range(len(data)):
        row = _row(data, row_index)
        if _is_footnote_row(row):
            continue
        grade = _grade_cell(row[grade_col]) if grade_col < len(row) else ""
        if not grade:
            continue
        properties: dict[str, Any] = {}
        columns: dict[str, str] = {}
        cells: dict[str, str] = {}
        for col, measure, header in measure_cols:
            cell = row[col] if col < len(row) else ""
            parsed = _value(cell)
            if parsed is None:
                continue
            key = _detect_measure(header, measure)
            unit = _unit(header, "", measure)
            existing = properties.get(key)
            if existing is not None:
                # ASTM repeats every property in ksi and MPa; keep MPa.
                if existing.get("unit") == "MPa" and unit != "MPa":
                    continue
                if unit != "MPa" and existing.get("unit") != "MPa":
                    continue
            properties[key] = {
                "value": parsed.get("value"),
                "raw": parsed.get("raw"),
                "operator": parsed.get("operator"),
                "unit": unit,
                "column": header,
            }
            columns[key] = header
            cells[header] = parsed.get("raw") or ""
        if not properties:
            continue
        table_id = str(table.get("table_id") or "unknown")
        record_id = f"{table_id}-M{row_index + 1}"
        page_no = int(table.get("page_no") or 0)
        records.append(
            {
                "record_id": record_id,
                "table_id": table_id,
                "block_id": str(table.get("block_id") or ""),
                "page_no": page_no,
                "row_index": row_index,
                "recipe_id": ctx.get("recipe_id") or "",
                "recipe_version": ctx.get("recipe_version") or "",
                "profile": ctx.get("profile") or "unknown",
                "grade": grade,
                "grade_raw": None,
                "conditions": {},
                "condition_key": "",
                "properties": properties,
                "evidence_refs": [record_id],
                "source": {
                    "table_id": table_id,
                    "block_id": str(table.get("block_id") or ""),
                    "page_no": page_no,
                    "row_index": row_index,
                },
            }
        )
        evidence.append(
            {
                "evidence_id": record_id,
                "table_id": table_id,
                "block_id": str(table.get("block_id") or ""),
                "page_no": page_no,
                "row_index": row_index,
                "raw_row": list(row),
                "cells": cells,
            }
        )
    return (records, evidence) if records else None


def property_rows(
    table: dict[str, Any], ctx: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]] | None:
    """Read vertical ``Property | Value`` tables (AMS style)."""
    headers, data = _headers(table)
    if len(headers) < 2 or not data:
        return None
    label_col = next(
        (
            index
            for index, header in enumerate(headers)
            if re.search(r"\bpropert(?:y|ies)\b|性能|项目", header, re.IGNORECASE)
        ),
        None,
    )
    if label_col is None:
        return None
    value_col = next(
        (
            index
            for index, header in enumerate(headers)
            if index != label_col and VALUE_HEADER_RE.search(header)
        ),
        None,
    )
    if value_col is None:
        others = [index for index, header in enumerate(headers) if index != label_col and header]
        if len(others) != 1:
            return None
        value_col = others[0]
    records: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    for row_index in range(len(data)):
        row = _row(data, row_index)
        if _is_footnote_row(row):
            continue
        label = row[label_col] if label_col < len(row) else ""
        if not label or not PROPERTY_HINT_RE.search(label):
            continue
        measure = _label_measure(label)
        if not measure or not _measure_allowed(ctx, measure):
            continue
        cell = row[value_col] if value_col < len(row) else ""
        parsed = _value(cell)
        if parsed is None:
            continue
        record, item = _build(
            table,
            ctx,
            row=row,
            row_index=row_index,
            col=value_col,
            grade="",
            conditions={},
            measure=measure,
            parsed=parsed,
            unit=_unit(headers[value_col], label, measure),
            column=headers[value_col],
        )
        records.append(record)
        evidence.append(item)
    return (records, evidence) if records else None


def hardness_minmax(
    table: dict[str, Any], ctx: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]] | None:
    """Read hardness tables that carry explicit min/max columns."""
    headers, data = _headers(table)
    if len(headers) < 2 or not data:
        return None
    hardness_cols = [
        (index, header)
        for index, header in enumerate(headers)
        if HARDNESS_HEADER_RE.search(header)
    ]
    if not hardness_cols:
        return None
    min_cols = [(index, header) for index, header in hardness_cols if MIN_RE.search(header)]
    max_cols = [(index, header) for index, header in hardness_cols if MAX_RE.search(header)]
    if not min_cols and not max_cols:
        return None
    grade_col = next(
        (
            index
            for index, header in enumerate(headers)
            if index not in {col for col, _ in hardness_cols}
            and GRADE_HEADER_RE.search(header)
        ),
        0,
    )
    symbol_match = next(
        (
            match
            for _, header in hardness_cols
            for match in [HARDNESS_SYMBOL_RE.search(header)]
            if match
        ),
        None,
    )
    measure = SYMBOL_CANON.get(symbol_match.group(0).lower(), "HBW") if symbol_match else "HBW"
    if not _measure_allowed(ctx, measure):
        return None
    records: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    for row_index in range(len(data)):
        row = _row(data, row_index)
        if _is_footnote_row(row):
            continue
        grade = _grade_cell(row[grade_col]) if grade_col < len(row) else ""
        if not grade:
            continue
        minimum = _value(row[min_cols[0][0]]) if min_cols and min_cols[0][0] < len(row) else None
        maximum = _value(row[max_cols[0][0]]) if max_cols and max_cols[0][0] < len(row) else None
        if minimum is None and maximum is None:
            continue
        parsed: dict[str, Any]
        if minimum is not None and maximum is not None:
            parsed = {
                "value": minimum.get("value"),
                "raw": f"{minimum.get('value')}~{maximum.get('value')}",
                "operator": "range",
                "upper": maximum.get("value"),
            }
            column = min_cols[0][1]
        elif minimum is not None:
            parsed = dict(minimum)
            parsed["operator"] = parsed.get("operator") or "≥"
            column = min_cols[0][1]
        else:
            parsed = dict(maximum or {})
            parsed["operator"] = parsed.get("operator") or "≤"
            column = max_cols[0][1]
        record, item = _build(
            table,
            ctx,
            row=row,
            row_index=row_index,
            col=hardness_cols[0][0],
            grade=grade,
            conditions={},
            measure=measure,
            parsed=parsed,
            unit=_unit(column, "", measure),
            column=column,
        )
        records.append(record)
        evidence.append(item)
    return (records, evidence) if records else None


STRATEGIES = {
    "property_matrix": property_matrix,
    "grade_property_matrix": grade_property_matrix,
    "property_rows": property_rows,
    "hardness_minmax": hardness_minmax,
}


def run_strategy_chain(
    table: dict[str, Any],
    ctx: dict[str, Any],
    diagnostics: list[dict[str, Any]],
    chain: list[str] | tuple[str, ...] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]] | None:
    """Try strategies in order and return the first non-empty result."""
    table_id = str(table.get("table_id") or "unknown")
    for name in chain or DEFAULT_CHAIN:
        strategy = STRATEGIES.get(str(name))
        if strategy is None:
            continue
        try:
            result = strategy(table, ctx)
        except Exception as exc:  # noqa: BLE001 - one strategy must not fail the table
            diagnostics.append(
                {
                    "code": "STRATEGY_ERROR",
                    "message": f"strategy {name} failed for table {table_id}: {exc}",
                    "severity": "warning",
                    "detail": {"table_id": table_id, "strategy": name},
                }
            )
            continue
        if result:
            records, evidence = result
            diagnostics.append(
                {
                    "code": "STRATEGY_HIT",
                    "message": f"strategy {name} produced {len(records)} records",
                    "severity": "info",
                    "detail": {"table_id": table_id, "strategy": name},
                }
            )
            return records, evidence
        diagnostics.append(
            {
                "code": "STRATEGY_MISS",
                "message": f"strategy {name} found no records",
                "severity": "info",
                "detail": {"table_id": table_id, "strategy": name},
            }
        )
    return None
