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
        ELEMENT_SYMBOLS,
        MEASURE_ALIASES,
        SYMBOL_CANON,
        _condition_key,
        _detect_measure,
        _element_symbol,
        _extract_unit,
        _grade_valid,
        _header_columns,
        _header_text,
        _is_footnote_row,
        _parse_value,
        _placeholder_grade,
        _split_grades,
        normalize,
        strip_footnote,
    )
except ImportError:  # flat runtime image (/engine)
    from builtin import (  # type: ignore[no-redef]
        ELEMENT_SYMBOLS,
        MEASURE_ALIASES,
        SYMBOL_CANON,
        _condition_key,
        _detect_measure,
        _element_symbol,
        _extract_unit,
        _grade_valid,
        _header_columns,
        _header_text,
        _is_footnote_row,
        _parse_value,
        _placeholder_grade,
        _split_grades,
        normalize,
        strip_footnote,
    )

DEFAULT_CHAIN = (
    "nonrecord",
    "property_matrix",
    "grade_property_matrix",
    "grade_property_tail",
    "property_rows",
    "hardness_minmax",
    "element_matrix",
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
CJK_RE = re.compile(r"[\u4e00-\u9fff]")
NON_PROPERTY_HEADER_RE = re.compile(
    r"尺寸|直径|厚度|长度|宽度|毛坯|diameter|thickness|width|length",
    re.IGNORECASE,
)
TAIL_COMPARATOR_RE = re.compile(r"^(?:不大于|不小于|不超过|不低于|[<>≤≥])$")
# 公差/允许偏差类表格不是性能记录表，命中后直接阻断策略链。
# 注意：单独的“成品分析/Product Analysis”是化学分析条件列，不能作为阻断依据。
NONRECORD_RE = re.compile(
    r"公差|允许偏差|permissible\s+variation|tolerance",
    re.IGNORECASE,
)
# 版本修订记录表是文档元数据，不是性能/成分记录表。
REVISION_HEADER_RE = re.compile(
    r"更改内容|更改说明|更改人|更改单号|修订|版本号|版次|会签|实施日期|修改范围|"
    r"职责|部门|签字",
    re.IGNORECASE,
)
INSPECTION_HEADER_RE = re.compile(
    r"取样|抽样|试验方法|检验方法|检验规则|复验|检测频次", re.IGNORECASE
)
DIMENSION_HEADER_RE = re.compile(
    r"外径|壁厚|厚度|长度|宽度|高度|尺寸|重量|直径|"
    r"diameter|thickness|length|width|weight",
    re.IGNORECASE,
)
ELEMENT_LABEL_RE = re.compile(r"^(?:元素|element)$", re.IGNORECASE)
PROPERTY_ORDER = {
    "Rm": 0,
    "Rp0.2": 1,
    "Rp1.0": 1,
    "ReL": 1,
    "ReH": 1,
    "A": 2,
    "Z": 3,
    "KV2": 4,
    "KU2": 4,
    "KU5": 4,
    "HB": 5,
    "HBW": 5,
    "HRB": 5,
    "HRC": 5,
    "HV": 5,
}


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
    if not text or _placeholder_grade(text):
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


def nonrecord_reason(table: dict[str, Any]) -> str:
    """Return a reason when the table must never produce records."""
    table_profile = str(table.get("profile") or "").strip().lower()
    if table_profile in {"inspection", "classification", "dimension"}:
        return f"table_profile:{table_profile}"
    headers, _ = _headers(table)
    caption = str(table.get("caption") or "")
    probe = " ".join([caption, *headers])
    if NONRECORD_RE.search(probe):
        return "tolerance_or_analysis"
    revision_hits = sum(1 for header in headers if REVISION_HEADER_RE.search(header))
    if revision_hits >= 2:
        return "revision_history"
    return ""


def nonrecord(
    table: dict[str, Any], ctx: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]] | None:
    """Block tables that are not performance/composition records.

    Tolerance, product-analysis and inspection tables can look numeric, but
    they must not produce grade-property records (ASTM page-4 Table 1 was the
    motivating case).  Returning an empty tuple stops the strategy chain.
    """
    headers, _ = _headers(table)
    caption = str(table.get("caption") or "")
    probe = " ".join([caption, *headers])
    if nonrecord_reason(table):
        return [], []
    looks_like_property = any(PROPERTY_HINT_RE.search(header) for header in headers) or any(
        _label_measure(header) for header in headers
    )
    if INSPECTION_HEADER_RE.search(probe) and not looks_like_property:
        return [], []
    dimension_headers = sum(
        1 for header in headers if DIMENSION_HEADER_RE.search(header)
    )
    if (
        len(headers) >= 2
        and dimension_headers >= max(2, len(headers) // 2)
        and not looks_like_property
    ):
        return [], []
    return None


def _tail_score(properties: dict[str, Any]) -> int:
    """Penalty for a tail-to-property alignment that violates semantics."""
    score = 0
    tensile = properties.get("Rm")
    yield_strength = (
        properties.get("Rp0.2")
        or properties.get("Rp1.0")
        or properties.get("ReL")
        or properties.get("ReH")
    )
    if tensile and yield_strength:
        if float(tensile.get("value") or 0) < float(yield_strength.get("value") or 0):
            score += 2
    for key in ("A", "Z"):
        value = properties.get(key)
        if value is not None:
            number = float(value.get("value") or 0)
            if not 0 <= number <= 100:
                score += 1
    for key in ("HB", "HBW", "HRB", "HRC", "HV"):
        value = properties.get(key)
        if value is not None and float(value.get("value") or 0) < 50:
            score += 1
    return score


def _properties_from_tail(
    row: list[str],
    grade_col: int,
    targets: list[tuple[int, str, str]],
) -> dict[str, Any]:
    tokens: list[tuple[int, dict[str, Any]]] = []
    for offset in range(len(row) - 1, grade_col, -1):
        text = str(row[offset] or "").strip()
        if not text or TAIL_COMPARATOR_RE.fullmatch(text):
            continue
        if text in SKIP_VALUES:
            continue
        parsed = _value(text)
        if parsed is None:
            break
        tokens.append((offset, parsed))
    if len(tokens) < 2:
        return {}
    tokens = list(reversed(tokens[: len(targets)]))
    properties: dict[str, Any] = {}
    for (_offset, parsed), (_, measure, header) in zip(
        tokens, targets[-len(tokens) :], strict=True
    ):
        properties[measure] = {
            "value": parsed.get("value"),
            "raw": parsed.get("raw"),
            "operator": parsed.get("operator"),
            "unit": _unit(header, "", measure),
            "column": header,
        }
    return properties


def _properties_by_column(
    row: list[str], columns: list[tuple[int, str, str]]
) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    for col, measure, header in columns:
        if col >= len(row):
            continue
        parsed = _value(row[col])
        if parsed is None:
            continue
        properties[measure] = {
            "value": parsed.get("value"),
            "raw": parsed.get("raw"),
            "operator": parsed.get("operator"),
            "unit": _unit(header, "", measure),
            "column": header,
        }
    return properties


def grade_property_tail(
    table: dict[str, Any], ctx: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]] | None:
    """Recover rows whose property cells are shifted left/right by OCR.

    The property block is the numeric tail of the row, so values are aligned
    from the right and the candidate that satisfies property semantics wins
    over the absolute header positions.
    """
    headers, data = _headers(table)
    if len(headers) < 4 or not data:
        return None
    profile = str(ctx.get("profile") or "")
    if profile and profile != "mechanical_properties":
        return None
    grade_col = next(
        (index for index, header in enumerate(headers) if GRADE_HEADER_RE.search(header)),
        None,
    )
    if grade_col is None:
        return None
    columns: list[tuple[int, str, str]] = []
    for index, header in enumerate(headers):
        if index == grade_col or NON_PROPERTY_HEADER_RE.search(header):
            continue
        if not PROPERTY_HINT_RE.search(header):
            continue
        measure = _label_measure(header)
        if measure and _measure_allowed(ctx, measure):
            columns.append((index, measure, header))
    if len(columns) < 3 or not any(CJK_RE.search(header) for _, _, header in columns):
        return None
    ordered = sorted(
        columns, key=lambda item: (PROPERTY_ORDER.get(item[1], 99), item[0])
    )
    first_property = min(index for index, _, _ in columns)
    label_columns = [
        index
        for index in range(grade_col + 1, first_property)
        if index < len(headers) and headers[index]
    ]
    records: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    for row_index in range(len(data)):
        row = _row(data, row_index)
        if _is_footnote_row(row) or grade_col >= len(row):
            continue
        grade = _grade_cell(row[grade_col])
        if not grade:
            continue
        candidates = [
            _properties_from_tail(row, grade_col, ordered),
            _properties_by_column(row, columns),
        ]
        scored = [
            (index, item) for index, item in enumerate(candidates) if len(item) >= 3
        ]
        properties = min(
            scored,
            key=lambda pair: (_tail_score(pair[1]), -len(pair[1]), pair[0]),
            default=(0, {}),
        )[1]
        if len(properties) < 2:
            continue
        labels = [
            str(row[index]).strip()
            for index in label_columns
            if index < len(row) and str(row[index]).strip()
        ]
        table_id = str(table.get("table_id") or "unknown")
        record_id = f"{table_id}-GT{row_index + 1}"
        page_no = int(table.get("page_no") or 0)
        block_id = str(table.get("block_id") or "")
        conditions = {"状态": " / ".join(labels[:3])} if labels else {}
        records.append(
            {
                "record_id": record_id,
                "table_id": table_id,
                "block_id": block_id,
                "page_no": page_no,
                "row_index": row_index,
                "recipe_id": ctx.get("recipe_id") or "",
                "recipe_version": ctx.get("recipe_version") or "",
                "profile": ctx.get("profile") or "unknown",
                "grade": grade,
                "grade_raw": None,
                "conditions": conditions,
                "condition_key": _condition_key(conditions),
                "properties": properties,
                "evidence_refs": [record_id],
                "source": {
                    "table_id": table_id,
                    "block_id": block_id,
                    "page_no": page_no,
                    "row_index": row_index,
                },
            }
        )
        evidence.append(
            {
                "evidence_id": record_id,
                "table_id": table_id,
                "block_id": block_id,
                "page_no": page_no,
                "row_index": row_index,
                "raw_row": list(row),
                "cells": {
                    header: properties[measure].get("raw") or ""
                    for _, measure, header in columns
                    if measure in properties
                },
            }
        )
    return (records, evidence) if records else None


def element_matrix(
    table: dict[str, Any], ctx: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]] | None:
    """Read transposed chemistry tables (element names as rows)."""
    headers, data = _headers(table)
    if len(headers) < 2 or not data:
        return None
    measures = [str(item) for item in ctx.get("measures") or []]
    profile = str(ctx.get("profile") or "")
    if profile != "chemical_composition" and not any(
        measure in ELEMENT_SYMBOLS for measure in measures
    ):
        return None
    first = normalize(headers[0]) if headers else ""
    element_rows = sum(
        1 for row in data[:8] if row and _element_symbol(str(row[0]))
    )
    has_element_label = bool(ELEMENT_LABEL_RE.search(first))
    header_grades = [
        strip_footnote(str(header)).strip()
        for header in headers[1:]
        if str(header).strip()
    ]
    grades_valid = bool(header_grades) and all(
        _grade_valid(grade, allow_numeric=True) for grade in header_grades
    )
    if not has_element_label and not (element_rows >= 3 and grades_valid):
        return None
    table_id = str(table.get("table_id") or "unknown")
    page_no = int(table.get("page_no") or 0)
    block_id = str(table.get("block_id") or "")
    records: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    for col in range(1, len(headers)):
        header = str(headers[col] or "")
        grade = strip_footnote(header).strip()
        if not grade:
            continue
        conditions: dict[str, str] = {}
        if _placeholder_grade(grade) or not _grade_valid(grade, allow_numeric=True):
            # "Min"/"Max"/"元素含量..." label a limit block, not a grade.
            grade = "~"
            conditions = {"依据": _header_text(header)}
        properties: dict[str, Any] = {}
        cells: dict[str, str] = {}
        for _row_index, row in enumerate(data):
            if _is_footnote_row(row) or not row:
                continue
            element = _element_symbol(str(row[0]))
            if not element or not _measure_allowed(ctx, element):
                continue
            if col >= len(row):
                continue
            parsed = _value(row[col])
            if parsed is None:
                continue
            unit = _extract_unit(headers[col], None) or (
                "%" if profile == "chemical_composition" else ""
            )
            properties[element] = {
                "value": parsed.get("value"),
                "raw": parsed.get("raw"),
                "operator": parsed.get("operator"),
                "unit": unit,
                "column": headers[col],
            }
            cells[element] = parsed.get("raw") or ""
        if len(properties) < 2:
            continue
        record_id = f"{table_id}-E{col}"
        records.append(
            {
                "record_id": record_id,
                "table_id": table_id,
                "block_id": block_id,
                "page_no": page_no,
                "row_index": 0,
                "recipe_id": ctx.get("recipe_id") or "",
                "recipe_version": ctx.get("recipe_version") or "",
                "profile": ctx.get("profile") or "unknown",
                "grade": grade,
                "grade_raw": None,
                "conditions": conditions,
                "condition_key": _condition_key(conditions),
                "properties": properties,
                "evidence_refs": [record_id],
                "source": {
                    "table_id": table_id,
                    "block_id": block_id,
                    "page_no": page_no,
                    "row_index": 0,
                },
            }
        )
        evidence.append(
            {
                "evidence_id": record_id,
                "table_id": table_id,
                "block_id": block_id,
                "page_no": page_no,
                "row_index": 0,
                "raw_row": [str(row[0]) for row in data if row],
                "cells": cells,
            }
        )
    return (records, evidence) if records else None


STRATEGIES = {
    "nonrecord": nonrecord,
    "property_matrix": property_matrix,
    "grade_property_matrix": grade_property_matrix,
    "grade_property_tail": grade_property_tail,
    "property_rows": property_rows,
    "hardness_minmax": hardness_minmax,
    "element_matrix": element_matrix,
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
        if str(name) == "nonrecord":
            if result is not None:
                diagnostics.append(
                    {
                        "code": "STRATEGY_BLOCKED",
                        "message": f"non-record table {table_id} blocked by {name}",
                        "severity": "info",
                        "detail": {"table_id": table_id, "strategy": name},
                    }
                )
                return [], []
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
