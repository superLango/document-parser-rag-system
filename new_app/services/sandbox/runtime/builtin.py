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
GRADE_SENTENCE_CHARS = ("。", "；", "，", "：", ";")
ELEMENT_RE = re.compile(r"^[A-Z][a-z]?$")

MEASURE_ALIASES: dict[str, list[str]] = {
    "Rm": ["抗拉强度", "拉伸强度", "σb"],
    "Rp0.2": ["屈服强度", "规定塑性延伸强度", "σ0.2"],
    "Rp1.0": ["屈服强度", "σ1.0"],
    "ReH": ["上屈服强度", "屈服强度"],
    "ReL": ["下屈服强度", "屈服强度"],
    "A": ["断后伸长率", "伸长率", "延伸率", "δs", "δ5"],
    "Z": ["断面收缩率", "收缩率", "ψ"],
    "KU2": ["冲击吸收能量", "冲击功", "kv2"],
    "KV2": ["冲击吸收能量", "冲击功", "ku2"],
    "KU5": ["冲击吸收能量", "冲击功"],
    "HB": ["布氏硬度", "硬度", "hbw"],
    "HBW": ["布氏硬度", "硬度", "hb"],
    "HRC": ["洛氏硬度"],
    "HRB": ["洛氏硬度"],
    "HV": ["维氏硬度"],
    "持久时间": ["持久时间", "持久强度", "持久"],
    "KIC": ["断裂韧性"],
    "CEV": ["碳当量"],
    "Pcm": ["焊接裂纹敏感性"],
    "Fe": ["铁"],
    "Si": ["硅"],
    "Mn": ["锰"],
    "P": ["磷"],
    "S": ["硫"],
    "Ni": ["镍"],
    "Cr": ["铬"],
    "Mo": ["钼"],
    "Cu": ["铜"],
    "Al": ["铝"],
    "Ti": ["钛"],
    "V": ["钒"],
    "Nb": ["铌"],
    "N": ["氮"],
    "O": ["氧"],
    "H": ["氢"],
    "B": ["硼"],
    "W": ["钨"],
    "Co": ["钴"],
    "Zr": ["锆"],
    "Ta": ["钽"],
    "Re": ["铼"],
    "Sn": ["锡"],
    "As": ["砷"],
    "Pb": ["铅"],
    "Sb": ["锑"],
    "Bi": ["铋"],
    "Ca": ["钙"],
    "Mg": ["镁"],
    "Zn": ["锌"],
    "Ce": ["铈"],
    "La": ["镧"],
    "Y": ["钇"],
    "Nd": ["钕"],
    "Se": ["硒"],
    "Te": ["碲"],
    "Ag": ["银"],
}

# Header symbols are authoritative: a column labelled KV2 must stay KV2 even
# when the recipe binds KU2 (and HBW must not be relabelled HB, etc.).
SYMBOL_CANON: dict[str, str] = {name.lower(): name for name in MEASURE_ALIASES}
SYMBOL_CANON.update(
    {
        "rel": "ReL",
        "reh": "ReH",
        "σb": "Rm",
        "σ0.2": "Rp0.2",
        "σ1.0": "Rp1.0",
        "δs": "A",
        "δ5": "A",
        "ψ": "Z",
    }
)
# ``Re`` is rhenium in chemistry but yield strength in mechanical tables; the
# recipe binding decides which one applies.
SYMBOL_CANON.pop("re", None)
SYMBOL_RE = re.compile(r"[A-Za-z]+(?:[0-9]+(?:\.[0-9]+)?)?")

ELEMENT_SYMBOLS = {
    "H", "B", "C", "N", "O", "F", "Na", "Mg", "Al", "Si", "P", "S", "K",
    "Ca", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn", "Ga", "Ge",
    "As", "Se", "Sr", "Y", "Zr", "Nb", "Mo", "Ag", "Cd", "In", "Sn", "Sb",
    "Te", "Ba", "La", "Ce", "Nd", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er",
    "Yb", "Ta", "W", "Re", "Pb", "Bi", "Th", "U",
}

CONDITION_TOKENS = ("规格", "尺寸", "方向", "试验温度", "温度", "状态", "热处理", "取样", "厚度")
DEFAULT_ROW_KEY = (
    "牌号",
    "钢号",
    "grade",
    "材料牌号",
    "常用材料",
    "钢种",
    "材料",
    "合金牌号",
    "材料名称",
)


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


def _header_parts(header: str) -> list[str]:
    return [part for part in re.split(r"[/\s()（）,，;；]+", normalize(header)) if part]


def _alias_matches(header: str, token: str) -> bool:
    """Short ASCII symbols must match a whole header component.

    ``hb`` must not match ``hbw`` and ``c`` must not match ``cr``; Chinese
    aliases keep substring matching because headers often add qualifiers.
    """
    if len(token) <= 3 or not re.search(r"[\u4e00-\u9fff]", token):
        return token in _header_parts(header)
    return token in header


def _find_column(headers: list[str], aliases: list[str], used: set[int]) -> int | None:
    normalized = [normalize(h) for h in headers]
    for alias in aliases:
        token = normalize(alias)
        if not token:
            continue
        for idx, header in enumerate(normalized):
            if idx in used:
                continue
            if _alias_matches(header, token):
                return idx
    return None


def _detect_measure(header: str, bound: str) -> str:
    """Return the symbol printed in the header when it is a known measure."""
    text = normalize(header)
    # Drop the unit tail so ``抗拉强度/N/mm2`` is not mistaken for nitrogen.
    if "/" in text:
        text = text.rsplit("/", 1)[0]
    for symbol in SYMBOL_RE.findall(text):
        canonical = SYMBOL_CANON.get(symbol)
        if canonical:
            return canonical
    return bound


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
    # Single-letter element symbols (C, P, S, N, ...) must be searchable too.
    aliases.insert(0, measure)
    return list(dict.fromkeys(aliases))


def _grade_valid(grade: str, *, allow_numeric: bool = False) -> bool:
    if not grade or len(grade) > GRADE_MAX_LEN:
        return False
    if any(mark in grade for mark in GRADE_SENTENCE_CHARS):
        return False
    if grade.startswith(("注", "说明", "备注")):
        return False
    if not re.search(r"[A-Za-z\u4e00-\u9fff]", grade):
        # Numeric grades (45, 20, 65Mn style) are valid only when the column
        # was explicitly identified as the row key.
        return allow_numeric and bool(re.fullmatch(r"\d{1,6}", grade))
    return True


def _is_footnote_row(cells: list[str]) -> bool:
    text = "".join(cells).strip()
    if not text:
        return True
    return text.startswith(("注", "注：", "说明", "备注")) or bool(
        re.match(r"^[①-⑳]", text)
    )


def _element_symbol(text: str) -> str:
    cleaned = strip_footnote(text).strip()
    if ELEMENT_RE.fullmatch(cleaned) and cleaned in ELEMENT_SYMBOLS:
        return cleaned
    base = re.sub(r"\(.*?\)|（.*?）|[%％]", "", cleaned).strip()
    if ELEMENT_RE.fullmatch(base) and base in ELEMENT_SYMBOLS:
        return base
    tokens = re.findall(r"[A-Z][a-z]?", base)
    if len(tokens) == 1 and tokens[0] in ELEMENT_SYMBOLS:
        return tokens[0]
    return ""


def _grade_from_header(header: str) -> str:
    text = strip_footnote(header)
    text = text.split("/")[-1].strip() or text
    text = re.sub(r"^(牌号|钢号|grade|材料牌号)\s*", "", text, flags=re.IGNORECASE)
    return text.strip()


def _parse_element_table(
    table: dict[str, Any],
    *,
    table_id: str,
    page_no: int,
    profile: str,
    recipe_id: str,
    recipe_version: str,
    strip_marks: bool,
    units: list[str],
    diagnostics: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Parse chemical tables that are organised by element instead of by grade.

    Two layouts are supported: element labels in the first column (values per
    condition column) and element labels in the header (values per row group).
    """
    records: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    row_total = 0
    explicit_unit = units[0] if len(units) == 1 else None

    for block_id, headers, data_rows in _iter_blocks(table):
        row_total += len(data_rows)
        if not headers or not data_rows:
            continue

        element_row_layout = any(
            _element_symbol(row[0])
            for row in data_rows[:8]
            if row and str(row[0] or "").strip()
        )
        if element_row_layout:
            for col in range(1, len(headers)):
                condition = _grade_from_header(headers[col]) or f"col{col + 1}"
                properties: dict[str, Any] = {}
                cells: dict[str, str] = {}
                for row in data_rows:
                    symbol = _element_symbol(row[0] if row else "")
                    if not symbol or col >= len(row):
                        continue
                    parsed = _parse_value(row[col], strip_marks)
                    if parsed is None:
                        continue
                    parsed["unit"] = _extract_unit(headers[col], explicit_unit)
                    parsed["column"] = headers[col]
                    properties[symbol] = parsed
                    cells[symbol] = row[col]
                if not properties:
                    continue
                record_id = f"{table_id}-C{col + 1}"
                records.append(
                    {
                        "record_id": record_id,
                        "table_id": table_id,
                        "block_id": block_id,
                        "page_no": page_no,
                        "row_index": col - 1,
                        "recipe_id": recipe_id,
                        "recipe_version": recipe_version,
                        "profile": profile,
                        "grade": "~",
                        "conditions": {"依据": condition},
                        "properties": properties,
                        "evidence_refs": [record_id],
                        "source": {
                            "table_id": table_id,
                            "block_id": block_id,
                            "page_no": page_no,
                            "row_index": col - 1,
                        },
                    }
                )
                evidence.append(
                    {
                        "evidence_id": record_id,
                        "table_id": table_id,
                        "block_id": block_id,
                        "page_no": page_no,
                        "row_index": col - 1,
                        "raw_row": list(cells.values()),
                        "cells": cells,
                    }
                )
            continue

        element_cols = [
            (idx, _element_symbol(header)) for idx, header in enumerate(headers[1:], start=1)
        ]
        element_cols = [(idx, symbol) for idx, symbol in element_cols if symbol]
        if not element_cols:
            diagnostics.append(
                {
                    "code": "ELEMENT_COLUMNS_NOT_FOUND",
                    "message": f"table {table_id} has no element labels",
                    "severity": "warning",
                    "detail": {"table_id": table_id, "headers": headers},
                }
            )
            continue
        for row_index, row in enumerate(data_rows):
            if _is_footnote_row(row):
                continue
            label = strip_footnote(row[0] if row else "") or "含量"
            if not _grade_valid(label):
                continue
            properties = {}
            cells = {}
            for col, symbol in element_cols:
                if col >= len(row):
                    continue
                parsed = _parse_value(row[col], strip_marks)
                if parsed is None:
                    continue
                parsed["unit"] = _extract_unit(headers[col], explicit_unit)
                parsed["column"] = headers[col]
                properties[symbol] = parsed
                cells[symbol] = row[col]
            if not properties:
                continue
            record_id = f"{table_id}-R{row_index + 1}"
            records.append(
                {
                    "record_id": record_id,
                    "table_id": table_id,
                    "block_id": block_id,
                    "page_no": page_no,
                    "row_index": row_index,
                    "recipe_id": recipe_id,
                    "recipe_version": recipe_version,
                    "profile": profile,
                    "grade": "~",
                    "conditions": {"依据": label},
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
                    "cells": cells,
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


def _parse_chemical_columns(
    table: dict[str, Any],
    *,
    table_id: str,
    page_no: int,
    profile: str,
    recipe_id: str,
    recipe_version: str,
    strip_marks: bool,
    units: list[str],
    diagnostics: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Fallback for grade-less chemical tables (element columns, one data row)."""
    records: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    row_total = 0
    explicit_unit = units[0] if len(units) == 1 else None
    for block_id, headers, data_rows in _iter_blocks(table):
        row_total += len(data_rows)
        element_cols = [
            (idx, symbol)
            for idx, header in enumerate(headers)
            if (symbol := _element_symbol(header))
        ]
        if len(element_cols) < 3:
            continue
        for row_index, row in enumerate(data_rows):
            if _is_footnote_row(row):
                continue
            properties: dict[str, Any] = {}
            cells: dict[str, str] = {}
            for col, symbol in element_cols:
                if col >= len(row):
                    continue
                parsed = _parse_value(row[col], strip_marks)
                if parsed is None:
                    continue
                parsed["unit"] = _extract_unit(headers[col], explicit_unit)
                parsed["column"] = headers[col]
                properties[symbol] = parsed
                cells[symbol] = row[col]
            if len(properties) < 2:
                continue
            record_id = f"{table_id}-R{row_index + 1}"
            records.append(
                {
                    "record_id": record_id,
                    "table_id": table_id,
                    "block_id": block_id,
                    "page_no": page_no,
                    "row_index": row_index,
                    "recipe_id": recipe_id,
                    "recipe_version": recipe_version,
                    "profile": profile,
                    "grade": "~",
                    "conditions": {},
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
                    "cells": cells,
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
    if rules.get("transposed"):
        return _parse_element_table(
            table,
            table_id=table_id,
            page_no=page_no,
            profile=profile,
            recipe_id=recipe_id,
            recipe_version=recipe_version,
            strip_marks=strip_marks,
            units=units,
            diagnostics=diagnostics,
        )

    records: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    record_count = 0
    row_total = 0
    explicit_unit = units[0] if len(units) == 1 else None

    for block_id, headers, data_rows in _iter_blocks(table):
        used: set[int] = set()
        row_key_tokens = list(
            dict.fromkeys([*(bindings.get("row_key") or []), *DEFAULT_ROW_KEY])
        )
        key_col = _find_column(headers, row_key_tokens, set())
        key_found = key_col is not None
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
        pending: list[str] = []
        # Pass 1: exact symbols win, so HB never steals HBW (and C never Cr).
        for measure in (bindings.get("measures") or {}):
            col = _find_column(headers, [str(measure)], used)
            if col is None:
                pending.append(str(measure))
                continue
            used.add(col)
            measure_cols[str(measure)] = col
        # Pass 2: alias matching for columns without an explicit symbol.
        for measure in pending:
            col = _find_column(headers, _measure_aliases(measure), used)
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
            measure_cols[measure] = col

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
            if not _grade_valid(grade, allow_numeric=key_found):
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
                if (
                    profile == "chemical_composition"
                    and parsed.get("value") is not None
                    and float(parsed["value"]) < 0
                ):
                    # Composition tolerances are not composition values.
                    continue
                parsed["unit"] = _extract_unit(headers[col], explicit_unit)
                parsed["column"] = headers[col]
                # Trust the symbol printed in the header (KV2 vs KU2, HBW vs HB).
                properties[_detect_measure(headers[col], measure)] = parsed

            if profile == "chemical_composition" and not properties:
                continue

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

    if not records and profile == "chemical_composition":
        # Composition tables often have no grade column (single specification).
        return _parse_chemical_columns(
            table,
            table_id=table_id,
            page_no=page_no,
            profile=profile,
            recipe_id=recipe_id,
            recipe_version=recipe_version,
            strip_marks=strip_marks,
            units=units,
            diagnostics=diagnostics,
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
