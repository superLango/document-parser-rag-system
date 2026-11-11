"""Deterministic extraction for condition-matrix tables.

Impact tables store KV2 as ``temperature x direction`` columns; carbon
equivalent tables store CEV/Pcm as ``thickness range`` columns. Language models
tend to collapse these wide matrices, so the bound columns are assembled here.
"""

from __future__ import annotations

import re
from typing import Any

from ..contracts import (
    ColumnBindingResult,
    DocumentMeta,
    Evidence,
    ExtractedValue,
    Record,
    TableGrid,
)
from ..tablegrid.normalize import (
    apply_default_comparator,
    canonical_element,
    canonical_property,
    clean_text,
    is_footnote_row,
    looks_like_grade,
    resolve_element_label_from_notes,
)
from .base import ExtractionOutput

TARGET_PROPERTIES = {"KV2", "KU2", "CEV", "Pcm"}
DIRECTIONS = {"纵向", "横向", "切向", "径向", "轴向"}
TEMPERATURE_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*[℃°C]")
THICKNESS_RE = re.compile(
    r"^(?:[<>≤≥]\s*)?\d+(?:\.\d+)?(?:\s*[~～-]\s*\d+(?:\.\d+)?)?$"
)
VALUE_RE = re.compile(r"^\s*([<>≤≥]?)\s*(\d+(?:\.\d+)?)(?:[a-zA-Z])?\s*$")
SKIP_VALUES = {"", "-", "—", "/"}
FOOTNOTE_TAIL_RE = re.compile(r"(?<=[0-9A-Z])[a-z°*]$")

# Row-oriented mechanical matrices (性能 × 温度) are common in manufacturing
# outlines. They are not covered by column recipes, so they are parsed
# deterministically from the row label and condition headers.
PROPERTY_MATRIX_PROFILES = {"mechanical_properties"}
CONDITION_HEADER_RE = re.compile(r"(室温|常温|高温|低温|-?\d+(?:\.\d+)?\s*[℃°C])")
LABEL_HEADER_MARKERS = ("性能", "property", "properties")
GRADE_HEADER_MARKERS = ("牌号", "grade")
UNIT_LABEL_RE = re.compile(
    r"[（(]\s*(MPa|GPa|%|J|HBW?|HBS|HRC|HRB|HV)\s*[）)]", re.IGNORECASE
)
MATRIX_VALUE_RE = re.compile(
    r"^\s*(≥|≤|>|<|>=|<=)?\s*(\d+(?:\.\d+)?)"
    r"(?:\s*[~～-]\s*(\d+(?:\.\d+)?))?\s*(?:[A-Za-z%]{0,8})?\s*$"
)
UNIT_DEFAULTS = {
    "Rm": "MPa",
    "Rp0.2": "MPa",
    "ReH": "MPa",
    "A": "%",
    "Z": "%",
    "KV2": "J",
    "KU2": "J",
    "HB": "HB",
    "HRB": "HRB",
    "HRC": "HRC",
    "HV": "HV",
}
NUMBER_TOKEN = r"\d+(?:\.\d+)?"
ELEMENT_VALUE_RE = re.compile(
    r"^\s*(?P<prefix>≥|≤|>|<|>=|<=)?\s*"
    rf"(?P<low>{NUMBER_TOKEN})"
    rf"(?:\s*(?:to|~|～|-)\s*(?P<high>{NUMBER_TOKEN}))?"
    r"\s*(?P<suffix>max\.?|min\.?)?\s*"
    r"(?:\([^)]*\))?\s*(?:[*a-zA-Z]{0,3})?\s*$",
    re.IGNORECASE,
)
PROPERTY_VALUE_RE = re.compile(
    r"^\s*(?P<prefix>≥|≤|>|<|>=|<=)?\s*"
    rf"(?P<low>{NUMBER_TOKEN})"
    rf"(?:\s*(?:to|~|～|-)\s*(?P<high>{NUMBER_TOKEN}))?"
    r"\s*(?P<suffix>max\.?|min\.?)?\s*"
    r"(?P<unit>ksi|MPa|GPa|%|HBW?|HBS|HRC|HRB|HV)?\s*$",
    re.IGNORECASE,
)
ELEMENT_LABEL_RE = re.compile(
    r"(?:元素|element|elements|alloying\s*elements?|chemical\s*elements?)",
    re.IGNORECASE,
)
GRADE_MARKERS = (
    "grade", "designation", "牌号", "钢级", "级别", "质量等级",
)
PROPERTY_HINT_RE = re.compile(
    r"tensile|yield|proof|elongation|reduction\s+of\s+area|hardness|impact|"
    r"strength|抗拉|屈服|伸长|收缩|硬度|冲击|塑性延伸|延伸强度|残余延伸",
    re.IGNORECASE,
)
CJK_RE = re.compile(r"[\u4e00-\u9fff]")
NON_PROPERTY_HEADER_RE = re.compile(
    r"尺寸|直径|厚度|长度|宽度|毛坯|"
    r"diameter|thickness|width|length",
    re.IGNORECASE,
)
REPORTED_ELEMENTS_RE = re.compile(
    r"values?\s+of\s+(?P<elements>.+?)\s+(?:are|is)\s+to\s+be\s+reported",
    re.IGNORECASE,
)


ELEMENT_MIN_COLUMN_RE = re.compile(
    r"最小值|最小|(?<![A-Za-z])min(?:imum)?(?![A-Za-z])", re.IGNORECASE
)
ELEMENT_MAX_COLUMN_RE = re.compile(
    r"最大值|最大|(?<![A-Za-z])max(?:imum)?(?![A-Za-z])", re.IGNORECASE
)


def _header_label(header_paths: list[list[str]], column: int) -> str:
    if 0 <= column < len(header_paths):
        return clean_text(
            " ".join(part for part in header_paths[column] if clean_text(part))
        )
    return ""


def _analysis_from_headers(
    header_paths: list[list[str]], column: int
) -> str | None:
    """Return 熔炼分析/成品分析 for an element-row value column."""

    text = _header_label(header_paths, column).lower()
    if "成品" in text or "product analysis" in text:
        return "成品分析"
    if "熔炼" in text or "heat analysis" in text:
        return "熔炼分析"
    return None


def reported_elements_from_notes(notes: list[str]) -> list[str]:
    """Elements a footnote says must be reported without a limit.

    ``* The Values of Copper, Columbium (Niobium) and Boron are to be
    reported but no limits applies`` is a real composition requirement; without
    this the schema loses Cu/Nb/B entirely.
    """

    elements: list[str] = []
    for note in notes:
        match = REPORTED_ELEMENTS_RE.search(clean_text(note))
        if match is None:
            continue
        for part in re.split(r",|、|;|\band\b|/", match.group("elements")):
            element = canonical_element(part)
            if element and element not in elements:
                elements.append(element)
    return elements


def reported_element_records(
    table_id: str,
    page_no: int,
    doc_id: str,
    notes: list[tuple[str, int | None, int | None]],
    existing: set[str],
) -> tuple[list[Record], list[Evidence]]:
    """Build text records for elements only named in a "to be reported" note."""

    records: list[Record] = []
    evidence: list[Evidence] = []
    seen: set[str] = set()
    for index, (raw, row, col) in enumerate(notes):
        text = clean_text(raw)
        if not text:
            continue
        for element in reported_elements_from_notes([text]):
            if element in existing or element in seen:
                continue
            seen.add(element)
            evidence_id = (
                f"ev:{doc_id}:{table_id}:r{row}:c{col}"
                if row is not None and col is not None
                else f"ev:{doc_id}:{table_id}:note{index}"
            )
            records.append(
                Record(
                    record_id=f"rec-{table_id}-note{index}-{element}",
                    source_table_id=table_id,
                    grade="",
                    condition="化学成分",
                    properties={
                        element: ExtractedValue(
                            raw="to be reported",
                            text="to be reported",
                            comparator="text",
                            evidence_id=evidence_id,
                        )
                    },
                )
            )
            if not any(item.evidence_id == evidence_id for item in evidence):
                evidence.append(
                    Evidence(
                        evidence_id=evidence_id,
                        page_no=page_no,
                        table_id=table_id,
                        row=row,
                        col=col,
                        quote=text,
                        artifact_uri="pages.json",
                    )
                )
    return records, evidence


def _footnote_notes(
    table: TableGrid,
) -> list[tuple[str, int | None, int | None]]:
    notes: list[tuple[str, int | None, int | None]] = []
    seen: set[str] = set()
    for note in table.footnotes or []:
        text = clean_text(note)
        if text and text not in seen:
            seen.add(text)
            notes.append((text, None, None))
    for row_index, row in enumerate(table.rows):
        if row_index < table.header_rows:
            continue
        if not (
            is_footnote_row(row)
            or bool(row and clean_text(row[0]).startswith("*"))
        ):
            continue
        for col, raw in enumerate(row):
            text = clean_text(raw)
            if text and text not in seen:
                seen.add(text)
                notes.append((text, row_index, col))
    return notes


def _looks_like_element_cell(text: str) -> bool:
    value = clean_text(text)
    if not value or len(value) > 24 or re.search(r"\d", value):
        return False
    return canonical_element(value) is not None


def _is_value_token(text: str) -> bool:
    """Numeric/limit tokens can appear in a header row that is really data."""

    value = clean_text(text)
    if not value or value in SKIP_VALUES:
        return True
    if re.fullmatch(r"[<>≤≥]?\s*[\d.,~\-]+", value):
        return True
    return ELEMENT_VALUE_RE.match(value) is not None


def _element_columns(
    rows: list[list[str]], header_paths: list[list[str]], header_rows: int
) -> list[int]:
    """Locate every element-label column, including side-by-side blocks.

    IN718 chemistry sheets repeat ``元素 | 最小值 | 最大值`` twice on one row;
    only column 0 used to be read, so the whole right-hand half (B/Cu/Ca/Pb/
    Sn/Se/Bi/Ag) was missing from the result.
    """

    width = max((len(row) for row in rows), default=0)
    columns = [
        column
        for column in range(width)
        if any(
            ELEMENT_LABEL_RE.fullmatch(clean_text(part))
            for part in (
                header_paths[column] if column < len(header_paths) else []
            )
        )
    ]
    if columns:
        return sorted(set(columns))
    # A real header row proves this is a grade-row table (steel grade groups
    # such as "Mn"/"Cr" would otherwise look like element labels).
    header_cells = [
        clean_text(part)
        for path in header_paths
        for part in path
        if clean_text(part)
    ]
    if header_cells and any(
        not _looks_like_element_cell(cell) and not _is_value_token(cell)
        for cell in header_cells
    ):
        return []
    # Header-less continuation page: infer label columns from the data itself.
    # Row 0 is included because it is often the first data row when no header
    # was detected.
    for column in range(width):
        samples = [
            clean_text(row[column])
            for row in rows
            if column < len(row) and clean_text(row[column])
        ]
        if len(samples) < 2:
            continue
        hits = sum(1 for sample in samples if _looks_like_element_cell(sample))
        if hits >= 2 and hits >= len(samples) * 0.6:
            columns.append(column)
    return columns


def _bound_header_kind(header: str) -> str | None:
    text = clean_text(header)
    if ELEMENT_MIN_COLUMN_RE.search(text):
        return "min"
    if ELEMENT_MAX_COLUMN_RE.search(text):
        return "max"
    return None


def _numeric_value(parsed: dict[str, Any] | None) -> float | None:
    if parsed is None or parsed.get("comparator") == "text":
        return None
    if parsed.get("lower") is not None:
        return parsed["lower"]
    return parsed.get("value")


def _first_bound(
    cells: list[tuple[int, str]]
) -> tuple[dict[str, Any], str, int] | None:
    for column, cell in cells:
        parsed = _parse_element_value(cell)
        if parsed is not None:
            return parsed, cell, column
    return None


def _combine_min_max(
    low: tuple[dict[str, Any], str, int] | None,
    high: tuple[dict[str, Any], str, int] | None,
) -> tuple[dict[str, Any], str] | None:
    """Collapse an explicit minimum/maximum pair into one interval."""

    if low is None and high is None:
        return None
    quotes = [item[1] for item in (low, high) if item is not None]
    quote = " ~ ".join(quotes)
    lower = _numeric_value(low[0]) if low else None
    upper = _numeric_value(high[0]) if high else None
    if lower is not None and upper is not None:
        lower, upper = sorted((lower, upper))
        if lower == upper:
            return {"comparator": "eq", "value": lower, "raw": quote}, quote
        return {
            "comparator": "range",
            "lower": lower,
            "upper": upper,
            "raw": quote,
        }, quote
    if lower is not None:
        return {"comparator": "min", "value": lower, "raw": quotes[0]}, quote
    if upper is not None:
        return {"comparator": "max", "value": upper, "raw": quotes[-1]}, quote
    parsed = low or high
    assert parsed is not None
    return parsed[0], quote


def extract_element_rows(
    *,
    table_id: str,
    page_no: int,
    doc_id: str,
    rows: list[list[str]],
    header_paths: list[list[str]],
    header_rows: int,
    notes: str,
) -> ExtractionOutput | None:
    """Read chemistry facts from every element block of one table."""

    width = max((len(row) for row in rows), default=0)
    element_columns = _element_columns(rows, header_paths, header_rows)
    if not element_columns:
        return None
    # A continuation page has no header; the grid then stores its first data
    # row in header_paths, so that row must not be skipped.
    header_is_data = any(
        _looks_like_element_cell(_header_label(header_paths, column))
        for column in element_columns
    )
    start = 0 if header_is_data else max(header_rows, 0)
    blocks: dict[int, list[int]] = {}
    for position, column in enumerate(element_columns):
        end = (
            element_columns[position + 1]
            if position + 1 < len(element_columns)
            else width
        )
        blocks[column] = list(range(column + 1, end))

    records: list[Record] = []
    evidence: list[Evidence] = []

    def emit(
        element: str,
        row_index: int,
        column: int,
        parsed: dict[str, Any],
        *,
        analysis: str | None,
        quote: str,
    ) -> None:
        evidence_id = f"ev:{doc_id}:{table_id}:r{row_index}:c{column}"
        unit = None if parsed.get("comparator") == "text" else "%"
        records.append(
            Record(
                record_id=f"rec-{table_id}-r{row_index}-c{column}",
                source_table_id=table_id,
                grade="",
                condition="成品分析" if analysis == "成品分析" else "化学成分",
                facets={"analysis": analysis} if analysis else {},
                properties={
                    element: ExtractedValue(
                        unit=unit,
                        evidence_id=evidence_id,
                        **parsed,
                    )
                },
            )
        )
        evidence.append(
            Evidence(
                evidence_id=evidence_id,
                page_no=page_no,
                table_id=table_id,
                row=row_index,
                col=column,
                quote=quote,
                artifact_uri="pages.json",
            )
        )

    for row_index in range(start, len(rows)):
        row = rows[row_index]
        if is_footnote_row(row):
            continue
        for element_column in element_columns:
            if element_column >= len(row):
                continue
            label = clean_text(row[element_column])
            if not label or len(label) > 24:
                continue
            element = resolve_element_label_from_notes(label, notes)
            if not element:
                continue
            cells = [
                (column, clean_text(row[column]))
                for column in blocks[element_column]
                if column < len(row)
                and clean_text(row[column])
                and clean_text(row[column]) not in SKIP_VALUES
            ]
            if not cells:
                continue
            if header_is_data:
                kinds: dict[int, str | None] = {column: None for column, _ in cells}
            else:
                kinds = {
                    column: _bound_header_kind(_header_label(header_paths, column))
                    for column, _ in cells
                }
            lows = [
                (column, cell)
                for column, cell in cells
                if kinds[column] == "min"
            ]
            highs = [
                (column, cell)
                for column, cell in cells
                if kinds[column] == "max"
            ]
            plains = [
                (column, cell)
                for column, cell in cells
                if kinds[column] is None
            ]
            if not lows and not highs and header_is_data and len(plains) >= 2:
                # No header survives: the block is still (minimum, maximum).
                lows, highs = [plains[0]], [plains[1]]
                plains = plains[2:]
            if lows or highs:
                low = _first_bound(lows)
                high = _first_bound(highs)
                combined = _combine_min_max(low, high)
                if combined is not None:
                    parsed, quote = combined
                    # Point evidence at the cell that actually parsed. The
                    # first column of a minimum block is often "--", and using
                    # it here produced an evidence/quote mismatch.
                    column = (low or high)[2]
                    emit(
                        element,
                        row_index,
                        column,
                        parsed,
                        analysis=None,
                        quote=quote,
                    )
            melt_value: dict[str, Any] | None = None
            for column, cell in plains:
                parsed = _parse_element_value(cell)
                if parsed is None:
                    continue
                analysis = (
                    None
                    if header_is_data
                    else _analysis_from_headers(header_paths, column)
                )
                if analysis == "成品分析":
                    if melt_value is not None and parsed == melt_value:
                        # 成品分析往往与熔炼分析逐项相同；只有不同值才需要
                        # 单独保留，否则每个元素都会重复一条记录。
                        continue
                elif melt_value is not None:
                    # 只取第一条熔炼分析/默认值列，保持旧行为。
                    continue
                emit(
                    element,
                    row_index,
                    column,
                    parsed,
                    analysis=analysis,
                    quote=cell,
                )
                if analysis != "成品分析":
                    melt_value = parsed
    if not records:
        return None
    return ExtractionOutput(records=records, evidence=evidence)


def extract_transposed_block_rows(
    table: TableGrid, document: DocumentMeta
) -> ExtractionOutput | None:
    """Read chemistry tables that alternate ``元素`` and ``含量`` rows.

    GJB 713 table 2 prints ``元素 | C | Mn | ...`` followed by
    ``含量 | ≤0.08 | ≤0.35 | ...`` in the same grid.
    """

    rows = table.rows
    if not rows:
        return None
    records: list[Record] = []
    evidence: list[Evidence] = []
    indices = [0] + list(range(table.header_rows, len(rows)))
    for index in indices:
        if index + 1 >= len(rows):
            continue
        label_row = rows[index]
        value_row = rows[index + 1]
        if not label_row or not value_row:
            continue
        if not ELEMENT_ROW_LABEL_RE.fullmatch(clean_text(label_row[0])):
            continue
        if not VALUE_ROW_LABEL_RE.match(clean_text(value_row[0])):
            continue
        seen: set[str] = set()
        for column in range(1, min(len(label_row), len(value_row))):
            element = canonical_element(label_row[column])
            if not element or element in seen:
                continue
            cell = clean_text(value_row[column])
            parsed = _parse_element_value(cell) if cell else None
            if parsed is None:
                continue
            seen.add(element)
            evidence_id = (
                f"ev:{document.doc_id}:{table.table_id}:r{index + 1}:c{column}"
            )
            records.append(
                Record(
                    record_id=f"rec-{table.table_id}-r{index + 1}-c{column}",
                    source_table_id=table.table_id,
                    grade="",
                    condition="化学成分",
                    properties={
                        element: ExtractedValue(
                            unit=None if parsed.get("comparator") == "text" else "%",
                            evidence_id=evidence_id,
                            **parsed,
                        )
                    },
                )
            )
            evidence.append(
                Evidence(
                    evidence_id=evidence_id,
                    page_no=table.page_no,
                    table_id=table.table_id,
                    row=index + 1,
                    col=column,
                    quote=cell,
                    artifact_uri="pages.json",
                )
            )
    if not records:
        return None
    return ExtractionOutput(records=records, evidence=evidence)


def extract_element_matrix(
    table: TableGrid, document: DocumentMeta
) -> ExtractionOutput | None:
    """Read a key-value chemistry table (element names in rows).

    Imported specifications often list ``Carbon, Max | 0.22`` in rows instead
    of grade rows. Models tend to copy footnotes into the value, so the numeric
    cell is parsed deterministically and non-numeric cells are skipped.
    """

    if table.profile != "chemical_composition":
        return None
    output = extract_element_rows(
        table_id=table.table_id,
        page_no=table.page_no,
        doc_id=document.doc_id,
        rows=table.rows,
        header_paths=table.header_paths,
        header_rows=table.header_rows,
        notes=_table_notes(table),
    )
    if output is None:
        output = extract_transposed_block_rows(table, document)
    if output is None:
        output = extract_grade_element_rows(table, document)
    if output is None:
        return None
    existing = {key for record in output.records for key in record.properties}
    extra_records, extra_evidence = reported_element_records(
        table.table_id,
        table.page_no,
        document.doc_id,
        _footnote_notes(table),
        existing,
    )
    output.records.extend(extra_records)
    output.evidence.extend(extra_evidence)
    return output


def _table_notes(table: TableGrid) -> str:
    parts = list(table.footnotes or [])
    if table.caption:
        parts.append(table.caption)
    for row in table.rows[table.header_rows :]:
        if is_footnote_row(row):
            parts.extend(cell for cell in row if cell)
    return clean_text(" ".join(parts))


ELEMENT_TEXT_RE = re.compile(
    r"refer|see\s+table|见\s*表|按\s*表|提供数据|提供实测|实测|报出|记录",
    re.IGNORECASE,
)
ELEMENT_ROW_LABEL_RE = re.compile(r"^(?:元素|element)$", re.IGNORECASE)
VALUE_ROW_LABEL_RE = re.compile(
    r"^(?:含量|成分|化学成分|要求|composition|content)",
    re.IGNORECASE,
)


HARDNESS_VALUE_RE = re.compile(
    r"(?P<scale>HBW?|HBS|HRC|HRB|HV)?\s*(?P<marker>[<>≤≥]?)\s*"
    r"(?P<value>\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
GRADE_HEADER_MARKERS = (
    "牌号", "grade", "designation", "材料", "material", "钢级",
)


def _hardness_bound(header: str) -> tuple[str | None, str] | None:
    text = clean_text(header).lower()
    if not any(
        marker in text
        for marker in ("hardness", "硬度", "布氏", "洛氏", "维氏")
    ) and not re.search(r"\b(hb|hbw|hbs|hrc|hrb|hv)\b", text):
        return None
    bound = None
    if re.search(r"minimum|\bmin\b|最小", text):
        bound = "min"
    elif re.search(r"maximum|\bmax\b|最大", text):
        bound = "max"
    if bound is None:
        return None
    scale = None
    if "brinell" in text or "布氏" in text or re.search(r"\b(hb|hbw|hbs)\b", text):
        scale = "HB"
    elif "rockwell" in text or "洛氏" in text or re.search(r"\b(hrc|hrb)\b", text):
        scale = "HRC"
    elif "vickers" in text or "维氏" in text or re.search(r"\bhv\b", text):
        scale = "HV"
    return scale, bound


def extract_hardness_rows(
    *,
    table_id: str,
    page_no: int,
    doc_id: str,
    rows: list[list[str]],
    header_paths: list[list[str]],
    header_rows: int,
) -> ExtractionOutput | None:
    """Read ``minimum/maximum hardness`` columns as one interval.

    ``Table 5: Hardness Values`` gives one row with *Minimum Brinell* and
    *Maximum Brinell* columns. Two separate limits duplicate the property and
    lose the interval meaning, so the pair becomes ``lower/upper`` with
    ``comparator="range"``.
    """

    headers = [
        " ".join(clean_text(part) for part in path if clean_text(part))
        for path in header_paths
    ]
    start = max(header_rows, 0)
    if (
        not headers
        or len(headers) < 2
        or any(len(header) > 40 for header in headers)
    ):
        headers = [clean_text(cell) for cell in (rows[0] if rows else [])]
        start = 1
    if not headers:
        return None
    bounds: list[tuple[int, str | None, str]] = []
    for index, header in enumerate(headers):
        found = _hardness_bound(header)
        if found is not None:
            bounds.append((index, found[0], found[1]))
    if not bounds:
        return None
    grade_col = next(
        (
            index
            for index, header in enumerate(headers)
            if any(marker in header.lower() for marker in GRADE_HEADER_MARKERS)
        ),
        None,
    )
    records: list[Record] = []
    evidence: list[Evidence] = []
    for row_index in range(start, len(rows)):
        row = rows[row_index]
        if is_footnote_row(row):
            continue
        grade = (
            clean_text(row[grade_col])
            if grade_col is not None and grade_col < len(row)
            else ""
        )
        found: dict[str, dict[str, tuple[float, str, int]]] = {}
        for column, header_scale, comparator in bounds:
            if column >= len(row):
                continue
            cell = clean_text(row[column])
            if not cell or cell in SKIP_VALUES:
                continue
            match = HARDNESS_VALUE_RE.search(cell)
            if match is None:
                continue
            scale = (match.group("scale") or header_scale or "HB").upper()
            scale = {"HBW": "HB", "HBS": "HB"}.get(scale, scale)
            marker = match.group("marker")
            if marker in {"≥", ">"}:
                comparator = "min"
            elif marker in {"≤", "<"}:
                comparator = "max"
            found.setdefault(scale, {})[comparator] = (
                float(match.group("value")),
                cell,
                column,
            )
        for scale, pair in found.items():
            low = pair.get("min")
            high = pair.get("max")
            quote = " ~ ".join(item[1] for item in (low, high) if item is not None)
            column = (low or high)[2]  # type: ignore[index]
            if low is not None and high is not None:
                lower, upper = sorted((low[0], high[0]))
                if lower == upper:
                    parsed: dict[str, Any] = {
                        "comparator": "eq",
                        "value": lower,
                        "raw": quote,
                    }
                else:
                    parsed = {
                        "comparator": "range",
                        "lower": lower,
                        "upper": upper,
                        "raw": quote,
                    }
                condition = "区间"
            elif low is not None:
                parsed = {"comparator": "min", "value": low[0], "raw": low[1]}
                condition = "最小值"
            else:
                assert high is not None
                parsed = {"comparator": "max", "value": high[0], "raw": high[1]}
                condition = "最大值"
            evidence_id = f"ev:{doc_id}:{table_id}:r{row_index}:c{column}"
            records.append(
                Record(
                    record_id=f"rec-{table_id}-r{row_index}-c{column}",
                    source_table_id=table_id,
                    grade=grade,
                    condition=condition,
                    properties={
                        scale: ExtractedValue(
                            unit=scale,
                            evidence_id=evidence_id,
                            **parsed,
                        )
                    },
                )
            )
            evidence.append(
                Evidence(
                    evidence_id=evidence_id,
                    page_no=page_no,
                    table_id=table_id,
                    row=row_index,
                    col=column,
                    quote=quote,
                    artifact_uri="pages.json",
                )
            )
    if not records:
        return None
    return ExtractionOutput(records=records, evidence=evidence)


def extract_hardness_minmax(
    table: TableGrid, document: DocumentMeta
) -> ExtractionOutput | None:
    return extract_hardness_rows(
        table_id=table.table_id,
        page_no=table.page_no,
        doc_id=document.doc_id,
        rows=table.rows,
        header_paths=table.header_paths,
        header_rows=table.header_rows,
    )


def normalize_decimal_commas(text: str) -> str:
    """Convert ISO/European decimal commas without touching thousands.

    ``5,5 to 6,75`` -> ``5.5 to 6.75`` and ``0,015`` -> ``0.015``, while
    ``1,000`` stays a thousands separator.
    """

    text = re.sub(r"(?<![0-9.])0,(\d{1,3})(?!\d)", r"0.\1", text)
    return re.sub(r"(?<=[1-9]),(\d{1,2})(?!\d)", r".\1", text)


def _parse_element_value(cell: str) -> dict[str, Any] | None:
    text = clean_text(cell)
    if not text:
        return None
    text = normalize_decimal_commas(text)
    # Unit annotations such as "0.05(500ppm)" are part of the limit, not text.
    text = re.sub(r"\s*\([^)]*\)\s*", "", text)
    if re.fullmatch(r"(?:remainder|balance|bal\.?|余|余量)", text, re.IGNORECASE):
        # ASTM/ISO write "remainder"/"balance" for the matrix element.
        return {"comparator": "text", "raw": text, "text": "余量"}
    if ELEMENT_TEXT_RE.search(text):
        # A pointer ("Refer Table 1A") or a delivery placeholder ("提供数据")
        # is a text requirement, not a missing composition limit.
        return {"comparator": "text", "raw": text, "text": text}
    if re.search(r"[A-Za-z]{3,}", text) and not re.search(
        r"\b(?:max|min)\.?\b", text, re.IGNORECASE
    ):
        # Free-text footnotes are not composition limits.
        return None
    text = re.sub(r"\s*%\s*$", "", text)
    match = ELEMENT_VALUE_RE.match(text)
    if match is None:
        return None
    marker = (match.group("prefix") or "").replace(">=", "≥").replace("<=", "≤")
    suffix = (match.group("suffix") or "").lower().rstrip(".")
    low = match.group("low")
    high = match.group("high")
    if high is not None:
        return {
            "comparator": "range",
            "raw": f"{low}~{high}",
            "lower": float(low),
            "upper": float(high),
        }
    comparator = "max"
    if marker in {"≥", ">"} or suffix == "min":
        comparator = "min"
    elif marker in {"≤", "<"} or suffix == "max":
        comparator = "max"
    raw = f"{marker}{low}" if marker else low
    return {
        "comparator": comparator,
        "raw": raw,
        "value": float(low),
    }


def extract_property_matrix(
    table: TableGrid, document: DocumentMeta
) -> ExtractionOutput | None:
    """Read a ``性能 × 温度`` matrix into per-property records."""

    if table.profile not in PROPERTY_MATRIX_PROFILES:
        return None
    headers, start = _matrix_headers(table)
    if len(headers) < 2:
        return None
    label_col = next(
        (
            index
            for index, header in enumerate(headers)
            if any(marker in header.lower() for marker in LABEL_HEADER_MARKERS)
        ),
        None,
    )
    if label_col is None:
        # A test-plan table (检验项目/试验方法) is not a property matrix even
        # though it may carry a temperature column.
        return None
    condition_cols: list[tuple[int, str]] = []
    for index, header in enumerate(headers):
        if index == label_col:
            continue
        match = CONDITION_HEADER_RE.search(header)
        if match:
            condition_cols.append((index, _normalize_condition(match.group(1))))
    if not condition_cols:
        return None
    grade_col = next(
        (
            index
            for index, header in enumerate(headers)
            if any(marker in header.lower() for marker in GRADE_HEADER_MARKERS)
        ),
        None,
    )

    records: list[Record] = []
    evidence: list[Evidence] = []
    for row_index in range(start, len(table.rows)):
        row = table.rows[row_index]
        if is_footnote_row(row) or label_col >= len(row):
            continue
        label = clean_text(row[label_col])
        prop = canonical_property(label)
        if not prop:
            continue
        unit = _label_unit(label, prop)
        for column, condition in condition_cols:
            if column >= len(row):
                continue
            cell = clean_text(row[column])
            if cell in SKIP_VALUES:
                continue
            parsed = _parse_matrix_value(cell, prop, label)
            if parsed is None:
                continue
            grade = (
                clean_text(row[grade_col])
                if grade_col is not None and grade_col < len(row)
                else ""
            )
            evidence_id = (
                f"ev:{document.doc_id}:{table.table_id}:r{row_index}:c{column}"
            )
            records.append(
                Record(
                    record_id=f"rec-{table.table_id}-r{row_index}-c{column}",
                    source_table_id=table.table_id,
                    grade=grade,
                    condition=condition,
                    properties={
                        prop: ExtractedValue(
                            unit=unit,
                            condition=condition,
                            evidence_id=evidence_id,
                            **parsed,
                        )
                    },
                )
            )
            evidence.append(
                Evidence(
                    evidence_id=evidence_id,
                    page_no=table.page_no,
                    table_id=table.table_id,
                    row=row_index,
                    col=column,
                    quote=cell,
                    artifact_uri="pages.json",
                )
            )
    if not records:
        return None
    return ExtractionOutput(records=records, evidence=evidence)


def _matrix_headers(table: TableGrid) -> tuple[list[str], int]:
    headers = [
        " ".join(clean_text(part) for part in path if clean_text(part))
        for path in table.header_paths
    ]
    if headers and len(headers) >= 2 and not any(len(header) > 120 for header in headers):
        return headers, table.header_rows
    if table.rows:
        return [clean_text(cell) for cell in table.rows[0]], 1
    return [], 0


def _merge_subheader(
    table: TableGrid, headers: list[str], start: int
) -> tuple[list[str], int]:
    """Promote a data row that is actually the second header line.

    OCR sometimes reports ``header_rows=1`` for two-line headers; the element
    or property names then sit in the first data row (``P``, ``S``, ``Cu``...).
    """

    if start >= len(table.rows):
        return headers, start
    row = table.rows[start]
    header_hits = sum(
        1
        for header in headers
        if canonical_element(clean_text(header)) or canonical_property(clean_text(header))
    )
    row_hits = sum(
        1
        for cell in row
        if canonical_element(clean_text(cell)) or canonical_property(clean_text(cell))
    )
    if row_hits < 2 or row_hits <= header_hits:
        return headers, start
    merged: list[str] = []
    for index, header in enumerate(headers):
        cell = clean_text(row[index]) if index < len(row) else ""
        if cell and cell.lower() not in header.lower():
            merged.append(f"{header} {cell}".strip())
        else:
            merged.append(header)
    return merged, start + 1


def _normalize_condition(value: str) -> str:
    text = clean_text(value).replace(" ", "")
    if text in {"常温", "室温"}:
        return "室温"
    return text


def _label_unit(label: str, prop: str) -> str:
    match = UNIT_LABEL_RE.search(label)
    if match:
        unit = match.group(1)
        upper = unit.upper()
        if upper.startswith("HB"):
            return "HB"
        if upper in {"HRB", "HRC", "HV", "MPA", "GPA", "J", "%"}:
            return "MPa" if upper == "MPA" else ("GPa" if upper == "GPA" else upper)
        return unit
    return UNIT_DEFAULTS.get(prop, "")


def _parse_matrix_value(
    cell: str, prop: str, label: str
) -> dict[str, Any] | None:
    text = clean_text(cell)
    if "提供数据" in text or "实测" in text or text in {"报出", "记录"}:
        return {"comparator": "text", "raw": text, "text": text}
    match = MATRIX_VALUE_RE.match(text)
    if match is None:
        return None
    marker = (match.group(1) or "").replace(">=", "≥").replace("<=", "≤")
    low = match.group(2)
    high = match.group(3)
    if high is not None:
        return {
            "comparator": "range",
            "raw": f"{low}~{high}",
            "lower": float(low),
            "upper": float(high),
        }
    parsed: dict[str, object] = {"comparator": "eq", "value": float(low)}
    if marker in {"≥", ">"}:
        parsed["comparator"] = "min"
    elif marker in {"≤", "<"}:
        parsed["comparator"] = "max"
    parsed = apply_default_comparator(
        parsed, property_key=prop, header_path=[label]
    )
    parsed["raw"] = f"{marker}{low}" if marker else low
    return parsed


def extract_bound_matrix(
    table: TableGrid,
    binding: ColumnBindingResult,
    document: DocumentMeta,
) -> ExtractionOutput | None:
    measures = [
        item
        for item in binding.bindings
        if item.role == "measure" and item.property in TARGET_PROPERTIES
    ]
    if not measures:
        return None
    row_keys = [item for item in binding.bindings if item.role == "row_key"]
    grade_col = next(
        (
            item.column
            for item in row_keys
            if any(key in " ".join(item.header_path) for key in ("牌号", "钢级"))
        ),
        None,
    )
    if grade_col is None:
        return None
    quality_col = next(
        (
            item.column
            for item in row_keys
            if "质量等级" in " ".join(item.header_path)
        ),
        None,
    )

    records: list[Record] = []
    evidence: list[Evidence] = []
    for row_index in range(table.header_rows, len(table.rows)):
        row = table.rows[row_index]
        if is_footnote_row(row) or grade_col >= len(row):
            continue
        grades = _combine_grades(
            clean_text(row[grade_col]),
            clean_text(row[quality_col]) if quality_col is not None and quality_col < len(row) else "",
        )
        if not grades:
            continue
        for measure in measures:
            if measure.column >= len(row):
                continue
            cell = clean_text(row[measure.column])
            if cell in SKIP_VALUES:
                continue
            match = VALUE_RE.match(cell)
            if not match:
                continue
            comparator = _comparator(match.group(1), measure.property)
            condition = _condition(measure.header_path, measure.property)
            unit = (
                "J"
                if measure.property in {"KV2", "KU2"}
                else (measure.unit or "%")
            )
            for grade_index, grade in enumerate(grades):
                suffix = f"-g{grade_index}" if len(grades) > 1 else ""
                evidence_id = (
                    f"ev:{document.doc_id}:{table.table_id}:"
                    f"r{row_index}:c{measure.column}{suffix}"
                )
                records.append(
                    Record(
                        record_id=(
                            f"rec-{table.table_id}-r{row_index}-c{measure.column}{suffix}"
                        ),
                        source_table_id=table.table_id,
                        grade=grade,
                        condition=condition,
                        properties={
                            measure.property: ExtractedValue(
                                raw=match.group(2),
                                value=float(match.group(2)),
                                unit=unit,
                                comparator=comparator,
                                condition=condition,
                                evidence_id=evidence_id,
                            )
                        },
                    )
                )
                evidence.append(
                    Evidence(
                        evidence_id=evidence_id,
                        page_no=table.page_no,
                        table_id=table.table_id,
                        row=row_index,
                        col=measure.column,
                        quote=cell,
                        artifact_uri="pages.json",
                    )
                )
    if not records:
        return None
    return ExtractionOutput(records=records, evidence=evidence)


def merge_matrix_output(
    records: list[Record], output: ExtractionOutput, table_id: str
) -> tuple[list[Record], bool]:
    """Merge matrix rows into the table's existing records.

    Returns the updated records and whether the previous evidence for the table
    must be dropped. Real condition matrices (temperature x direction, thickness
    bands) are authoritative and replace the model's collapsed rows; a plain
    single-column measure only augments the row already extracted for that grade.
    """
    if any(row.condition for row in output.records):
        kept = [row for row in records if row.source_table_id != table_id]
        kept.extend(output.records)
        return kept, True
    by_grade = {
        row.grade: row
        for row in records
        if row.source_table_id == table_id and row.grade
    }
    for row in output.records:
        existing = by_grade.get(row.grade) if row.grade else None
        if existing is None:
            records.append(row)
            if row.grade:
                by_grade[row.grade] = row
        else:
            existing.properties.update(row.properties)
    return records, False


def _combine_grades(grade: str, quality: str) -> list[str]:
    """Expand ``grade x quality level`` cells into individual grade names.

    Footnote letters are glued to the cell text by the OCR layer
    (``Q355a<sup>a</sup>`` -> ``Q355a``), and quality-level cells may list
    several levels (``B、C、D、E、F``); both are expanded here.
    """
    parts = [_strip_footnote(part) for part in re.split(r"[、,，]", grade)]
    parts = [part for part in parts if part]
    qualities = [_strip_footnote(part) for part in re.split(r"[、,，]", quality)]
    qualities = [part for part in qualities if part and part not in {"-", "—"}]
    if not parts:
        return []
    if not qualities:
        return list(dict.fromkeys(parts))
    grades: list[str] = []
    for part in parts:
        for level in qualities:
            grades.append(part if part.endswith(level) else f"{part}{level}")
    return list(dict.fromkeys(grades))


def _strip_footnote(text: str) -> str:
    return FOOTNOTE_TAIL_RE.sub("", text.strip())


def _comparator(marker: str, prop: str) -> str:
    if marker in {"≥", ">"}:
        return "min"
    if marker in {"≤", "<"}:
        return "max"
    return "min" if prop in {"KV2", "KU2"} else "max"


def _condition(path: list[str], prop: str) -> str | None:
    text = " ".join(path)
    if prop in {"KV2", "KU2"}:
        temperature = TEMPERATURE_RE.search(text)
        direction = next(
            (clean_text(part) for part in reversed(path) if clean_text(part) in DIRECTIONS),
            None,
        )
        if temperature and direction:
            return f"{temperature.group(1)}℃/{direction}"
        if temperature:
            return f"{temperature.group(1)}℃"
        return direction
    for part in reversed(path):
        label = _strip_footnote(clean_text(part))
        if label and THICKNESS_RE.match(label):
            return label
    return None


def _header_bound(header: str) -> str | None:
    text = clean_text(header).lower()
    if "不大于" in text or "不超过" in text or "最高" in text:
        return "max"
    if "不小于" in text or "不低于" in text or "最低" in text:
        return "min"
    if re.search(r"(?:maximum|max)\.?", text):
        return "max"
    if re.search(r"(?:minimum|min)\.?", text):
        return "min"
    return None


def _header_unit(header: str, prop: str | None = None) -> str:
    text = clean_text(header).lower()
    if "gpa" in text:
        return "GPa"
    if "mpa" in text:
        return "MPa"
    if "ksi" in text:
        return "ksi"
    if "%" in text:
        return "%"
    match = re.search(r"\b(hbw?|hbs|hrc|hrb|hv)\b", text)
    if match:
        value = match.group(1).upper()
        return {"HBW": "HB", "HBS": "HB"}.get(value, value)
    if prop:
        return UNIT_DEFAULTS.get(prop, "")
    return ""


def _element_value_for_header(cell: str, header: str) -> dict[str, Any] | None:
    parsed = _parse_element_value(cell)
    if parsed is None or parsed.get("comparator") in {"range", "text"}:
        return parsed
    bound = _header_bound(header)
    if bound and not re.match(r"^\s*[<>≤≥]", clean_text(cell)):
        parsed["comparator"] = bound
    return parsed


def _parse_property_value(
    cell: str, prop: str, unit: str, bound: str | None
) -> dict[str, Any] | None:
    text = clean_text(cell)
    if not text or text in SKIP_VALUES or text in {"...", "…"}:
        return None
    if text.lower() in {"not applicable", "n/a", "na", "--"}:
        return None
    parenthetical = re.search(r"\(([^)]*mpa[^)]*)\)", text, re.IGNORECASE)
    if parenthetical:
        # ASTM lists ksi first and MPa in brackets; MPa is the platform unit.
        text = parenthetical.group(1)
        unit = "MPa"
    text = normalize_decimal_commas(text)
    if re.search(r"[A-Za-z]{3,}", text) and not re.search(
        r"\b(?:maximum|minimum|max|min|ksi|mpa)\b", text, re.IGNORECASE
    ):
        return None
    text = re.sub(r"\s*%\s*$", "", text)
    match = PROPERTY_VALUE_RE.match(text)
    if match is None:
        return None
    prefix = (match.group("prefix") or "").replace(">=", "≥").replace("<=", "≤")
    suffix = (match.group("suffix") or "").lower().rstrip(".")
    found_unit = match.group("unit")
    if found_unit:
        upper = found_unit.upper()
        unit = {"MPA": "MPa", "GPA": "GPa"}.get(upper, upper)
        if unit in {"HBW", "HBS"}:
            unit = "HB"
    unit = unit or UNIT_DEFAULTS.get(prop, "")
    low = match.group("low")
    high = match.group("high")
    if high is not None:
        return {
            "comparator": "range",
            "raw": f"{low}~{high}",
            "lower": float(low),
            "upper": float(high),
            "unit": unit,
        }
    comparator = "min"
    if not prefix and not suffix and not bound:
        comparator = (
            "max" if prop in {"HB", "HBS", "HRB", "HRC", "HV"} else "min"
        )
    if prefix in {"≥", ">"} or suffix == "min" or bound == "min":
        comparator = "min"
    elif prefix in {"≤", "<"} or suffix == "max" or bound == "max":
        comparator = "max"
    return {
        "comparator": comparator,
        "raw": f"{prefix}{low}" if prefix else low,
        "value": float(low),
        "unit": unit,
    }


def _grade_column(headers: list[str]) -> int | None:
    for index, header in enumerate(headers):
        text = header.lower()
        if any(marker in text for marker in GRADE_MARKERS):
            return index
    return None


def _value_columns(
    headers: list[str], kind: str
) -> list[tuple[int, str, str]]:
    columns: list[tuple[int, str, str]] = []
    for index, header in enumerate(headers):
        text = clean_text(header)
        if not text:
            continue
        if kind == "element":
            if PROPERTY_HINT_RE.search(text):
                continue
            value = canonical_element(text)
        else:
            if (
                CJK_RE.search(text)
                or not PROPERTY_HINT_RE.search(text)
                or NON_PROPERTY_HEADER_RE.search(text)
            ):
                continue
            value = canonical_property(text)
        if value:
            columns.append((index, value, text))
    return columns


def _row_label(
    row: list[str], label_columns: list[int], grade_col: int | None
) -> tuple[str, str | None]:
    grade = ""
    if grade_col is not None and grade_col < len(row):
        grade = clean_text(row[grade_col])
    labels = [
        clean_text(row[column])
        for column in label_columns
        if column != grade_col and column < len(row) and clean_text(row[column])
    ]
    condition = " / ".join(labels[:3]) if labels and not grade else None
    return grade, condition


def extract_grade_element_rows(
    table: TableGrid, document: DocumentMeta
) -> ExtractionOutput | None:
    """Read a grade-row chemistry table (``Grade | C | Mn | ...``).

    ASTM/ISO chemistry tables put elements in columns and grades in rows; the
    element-row reader above only understands the transposed layout.
    """

    headers, start = _matrix_headers(table)
    headers, start = _merge_subheader(table, headers, start)
    if len(headers) < 3:
        return None
    columns = _value_columns(headers, "element")
    if len(columns) < 2:
        return None
    first_value = min(column for column, _, _ in columns)
    label_columns = [index for index in range(first_value) if clean_text(headers[index])]
    if not label_columns:
        return None
    grade_col = _grade_column(headers)
    if grade_col is not None and grade_col >= first_value:
        grade_col = None

    records: list[Record] = []
    evidence: list[Evidence] = []
    header_labels = {clean_text(header).lower() for header in headers if header}
    for row_index in range(start, len(table.rows)):
        row = table.rows[row_index]
        if is_footnote_row(row):
            continue
        grade, condition = _row_label(row, label_columns, grade_col)
        if grade and (
            grade.lower() in header_labels or len(grade) > 40
        ):
            continue
        properties: dict[str, ExtractedValue] = {}
        for column, element, header in columns:
            if column >= len(row):
                continue
            cell = clean_text(row[column])
            if not cell or cell in SKIP_VALUES:
                continue
            parsed = _element_value_for_header(cell, header)
            if parsed is None:
                continue
            evidence_id = (
                f"ev:{document.doc_id}:{table.table_id}:r{row_index}:c{column}"
            )
            properties[element] = ExtractedValue(
                unit=None if parsed.get("comparator") == "text" else "%",
                evidence_id=evidence_id,
                **parsed,
            )
            evidence.append(
                Evidence(
                    evidence_id=evidence_id,
                    page_no=table.page_no,
                    table_id=table.table_id,
                    row=row_index,
                    col=column,
                    quote=cell,
                    artifact_uri="pages.json",
                )
            )
        if not properties:
            continue
        records.append(
            Record(
                record_id=f"rec-{table.table_id}-r{row_index}",
                source_table_id=table.table_id,
                grade=grade,
                condition=condition,
                properties=properties,
            )
        )
    if not records:
        return None
    return ExtractionOutput(records=records, evidence=evidence)


TAIL_COMPARATOR_RE = re.compile(r"^(?:不大于|不小于|不超过|不低于|[<>≤≥])$")
# 部分 GJB 表把同一牌号的 I 组/II 组性能并排写在两段列里
# （``… | I组 | Rm | ReL | A | Z | KU2 | HB | II组 | Rm | …``）。
GROUP_LABEL_RE = re.compile(
    r"^(?:[ⅠⅡⅢⅣⅤⅥIVXivx]+|\d+|[一二三四五六七八九十]+|第[一二三四五六七八九十]+)组$"
)
PROPERTY_ORDER = {
    "Rm": 0,
    "Rp0.2": 1,
    "ReL": 1,
    "ReH": 1,
    "A": 2,
    "A50mm": 2,
    "Z": 3,
    "KV2": 4,
    "KU1": 4,
    "KU2": 4,
    "KU5": 4,
    "HB": 5,
    "HRB": 5,
    "HRC": 5,
    "HV": 5,
}


def extract_grade_property_tail(
    table: TableGrid, document: DocumentMeta
) -> ExtractionOutput | None:
    """Recover property values from messy Chinese heat-treatment tables.

    GB/T 3077 table 3 mixes size, quench/temper temperatures and cooling media
    between the grade and the properties; OCR sometimes shifts those cells by
    one or two columns. The property block itself is always the numeric tail of
    the row, so it is aligned from the right instead of by absolute column.
    """

    if table.profile != "mechanical_properties":
        return None
    headers, start = _matrix_headers(table)
    if len(headers) < 4:
        return None
    grade_col = _grade_column(headers)
    if grade_col is None:
        return None
    columns: list[tuple[int, str, str]] = []
    for index, header in enumerate(headers):
        if index == grade_col:
            continue
        if not PROPERTY_HINT_RE.search(header) or NON_PROPERTY_HEADER_RE.search(header):
            continue
        prop = canonical_property(header)
        if prop:
            columns.append((index, prop, header))
    if len(columns) < 2 or not any(CJK_RE.search(h) for _, _, h in columns):
        return None
    canonical_columns = sorted(
        columns, key=lambda item: (PROPERTY_ORDER.get(item[1], 99), item[0])
    )
    first_property = min(column for column, _, _ in columns)
    label_columns = [
        index for index in range(first_property) if clean_text(headers[index])
    ]

    records: list[Record] = []
    evidence: list[Evidence] = []
    header_labels = {clean_text(header).lower() for header in headers if header}
    for row_index in range(start, len(table.rows)):
        row = table.rows[row_index]
        if is_footnote_row(row) or grade_col >= len(row):
            continue
        grade = clean_text(row[grade_col])
        if (
            not grade
            or grade.lower() in header_labels
            or len(grade) > 20
            or not looks_like_grade(grade)
        ):
            continue
        blocks = [
            (offset, clean_text(row[offset]))
            for offset in range(grade_col + 1, len(row))
            if GROUP_LABEL_RE.fullmatch(clean_text(row[offset]))
        ]
        if blocks:
            block_records, block_evidence = _extract_block_segments(
                table,
                document,
                row_index,
                row,
                headers,
                grade,
                grade_col,
                canonical_columns,
                blocks,
            )
            if block_records:
                records.extend(block_records)
                evidence.extend(block_evidence)
                continue
        tokens: list[tuple[str, int]] = []
        for offset in range(len(row) - 1, grade_col, -1):
            header = headers[offset] if offset < len(headers) else ""
            if (
                header
                and NON_PROPERTY_HEADER_RE.search(header)
                and canonical_property(header) is None
            ):
                # 尺寸/几何列（直径、厚度）是标签而不是性能值。把它算进数值
                # 尾部会让整行性能值左移一列（GB/T 4423 出现 A=125%）。
                break
            text = clean_text(row[offset])
            if not text:
                continue
            if TAIL_COMPARATOR_RE.fullmatch(text):
                continue
            if text in SKIP_VALUES or text in {"--", "—"}:
                tokens.append(("na", offset))
                continue
            if _parse_property_value(text, "Rm", "", None) is None:
                break
            tokens.append((text, offset))
        if len(tokens) < 2:
            continue
        # Tokens were collected right-to-left; keep only the rightmost block
        # that fits the property columns.
        tokens = tokens[: len(columns)]
        candidates = []
        for targets in (
            columns[-len(tokens) :],
            canonical_columns[-len(tokens) :],
        ):
            properties, cell_evidence = _assign_tail_values(
                table, document, row_index, tokens, targets
            )
            candidates.append((properties, cell_evidence))
        # 表头与单元格本身对齐时，按列直读是最可靠的读数。数值尾部对齐只是
        # OCR 错列时的兜底，两者一起交给语义评分选择。
        candidates.append(
            _assign_direct_values(table, document, row_index, row, columns)
        )
        # Prefer the order that satisfies property semantics (Rm >= Rp, A/Z in
        # percent, hardness above 100). Ties keep the header order.
        properties, cell_evidence = min(
            candidates,
            key=lambda item: (
                _tail_mapping_score(item[0]),
                -len(item[0]),
            ),
        )
        if len(properties) < 2:
            continue
        evidence.extend(cell_evidence)
        labels = [
            clean_text(row[index])
            for index in label_columns
            if index != grade_col
            and index < len(row)
            and clean_text(row[index])
        ]
        records.append(
            Record(
                record_id=f"rec-{table.table_id}-r{row_index}",
                source_table_id=table.table_id,
                grade=grade,
                condition=" / ".join(labels[:3]) if labels else None,
                properties=properties,
            )
        )
    if not records:
        return None
    return ExtractionOutput(records=records, evidence=evidence)


def _extract_block_segments(
    table: TableGrid,
    document: DocumentMeta,
    row_index: int,
    row: list[str],
    headers: list[str],
    grade: str,
    grade_col: int,
    canonical_columns: list[tuple[int, str, str]],
    blocks: list[tuple[int, str]],
) -> tuple[list[Record], list[Evidence]]:
    """Split a row that carries several side-by-side property blocks.

    GJB 1951A writes ``… | I组 | Rm | ReL | A | Z | KU2 | HB | II组 | …`` on
    one row; each block restarts at Rm, so the right-aligned tail alone cannot
    tell the blocks apart and shifted every property left.
    """

    bounds = [grade_col] + [offset for offset, _ in blocks] + [len(row)]
    conditions: list[str | None] = [None] + [label for _, label in blocks]
    records: list[Record] = []
    evidence: list[Evidence] = []
    for index in range(len(bounds) - 1):
        start, end = bounds[index] + 1, bounds[index + 1]
        tokens: list[tuple[str, int]] = []
        for offset in range(end - 1, start - 1, -1):
            text = clean_text(row[offset])
            if not text:
                continue
            if TAIL_COMPARATOR_RE.fullmatch(text):
                continue
            if text in SKIP_VALUES:
                tokens.append(("na", offset))
                continue
            if _parse_property_value(text, "Rm", "", None) is None:
                break
            tokens.append((text, offset))
        while tokens and tokens[-1][0] == "na":
            tokens.pop()
        if not tokens:
            continue
        targets = canonical_columns[: len(tokens)]
        properties, cell_evidence = _assign_tail_values(
            table, document, row_index, tokens, targets
        )
        if len(properties) < 2:
            continue
        evidence.extend(cell_evidence)
        suffix = "" if not records else f"-b{len(records)}"
        records.append(
            Record(
                record_id=f"rec-{table.table_id}-r{row_index}{suffix}",
                source_table_id=table.table_id,
                grade=grade,
                condition=conditions[index],
                properties=properties,
            )
        )
    return records, evidence


def _assign_tail_values(
    table: TableGrid,
    document: DocumentMeta,
    row_index: int,
    tokens: list[tuple[str, int]],
    targets: list[tuple[int, str, str]],
) -> tuple[dict[str, ExtractedValue], list[Evidence]]:
    properties: dict[str, ExtractedValue] = {}
    evidence: list[Evidence] = []
    for (_column, prop, header), (token, token_col) in zip(
        targets, reversed(tokens)
    ):
        if token == "na":
            continue
        parsed = _parse_property_value(
            token, prop, _header_unit(header, prop), _header_bound(header)
        )
        if parsed is None:
            continue
        value_unit = parsed.pop("unit", None) or _header_unit(header, prop)
        evidence_id = (
            f"ev:{document.doc_id}:{table.table_id}:r{row_index}:c{token_col}"
        )
        properties[prop] = ExtractedValue(
            unit=value_unit,
            evidence_id=evidence_id,
            **parsed,
        )
        evidence.append(
            Evidence(
                evidence_id=evidence_id,
                page_no=table.page_no,
                table_id=table.table_id,
                row=row_index,
                col=token_col,
                quote=token,
                artifact_uri="pages.json",
            )
        )
    return properties, evidence


def _assign_direct_values(
    table: TableGrid,
    document: DocumentMeta,
    row_index: int,
    row: list[str],
    columns: list[tuple[int, str, str]],
) -> tuple[dict[str, ExtractedValue], list[Evidence]]:
    """Read each property from the column its header names."""

    properties: dict[str, ExtractedValue] = {}
    evidence: list[Evidence] = []
    for column, prop, header in columns:
        if column >= len(row):
            continue
        cell = clean_text(row[column])
        if not cell or cell in SKIP_VALUES or TAIL_COMPARATOR_RE.fullmatch(cell):
            continue
        unit = _header_unit(header, prop)
        parsed = _parse_property_value(cell, prop, unit, _header_bound(header))
        if parsed is None:
            continue
        value_unit = parsed.pop("unit", None) or unit
        evidence_id = (
            f"ev:{document.doc_id}:{table.table_id}:r{row_index}:c{column}"
        )
        properties[prop] = ExtractedValue(
            unit=value_unit,
            evidence_id=evidence_id,
            **parsed,
        )
        evidence.append(
            Evidence(
                evidence_id=evidence_id,
                page_no=table.page_no,
                table_id=table.table_id,
                row=row_index,
                col=column,
                quote=cell,
                artifact_uri="pages.json",
            )
        )
    return properties, evidence


def _tail_number(value: ExtractedValue | None) -> float | None:
    if value is None:
        return None
    if value.comparator == "range":
        return value.lower if value.lower is not None else value.upper
    return value.value


def _tail_mapping_score(properties: dict[str, ExtractedValue]) -> int:
    score = 0
    rm = _tail_number(properties.get("Rm"))
    rp = _tail_number(
        properties.get("Rp0.2")
        or properties.get("ReL")
        or properties.get("ReH")
    )
    if rm is not None and rp is not None and rm < rp:
        score += 3
    if rm is not None and not 50 <= rm <= 3000:
        score += 1
    if rp is not None and not 20 <= rp <= 2500:
        score += 1
    for prop in ("A", "A50mm", "Z"):
        number = _tail_number(properties.get(prop))
        if number is not None and not 0 <= number <= 100:
            score += 3
    for prop in ("HB", "HBS", "HRB", "HRC", "HV"):
        number = _tail_number(properties.get(prop))
        if number is not None and not 30 <= number <= 800:
            score += 2
    for prop in ("KV2", "KU2", "KU1", "KU5"):
        number = _tail_number(properties.get(prop))
        if number is not None and not 0 <= number <= 500:
            score += 1
    return score


def extract_grade_property_matrix(
    table: TableGrid, document: DocumentMeta
) -> ExtractionOutput | None:
    """Read a grade-row mechanical table (``Grade | Rm | Rp0.2 | A ...``)."""

    if table.profile != "mechanical_properties":
        return None
    headers, start = _matrix_headers(table)
    headers, start = _merge_subheader(table, headers, start)
    if len(headers) < 3:
        return None
    columns = _value_columns(headers, "property")
    if len(columns) < 2:
        return None
    first_value = min(column for column, _, _ in columns)
    label_columns = [index for index in range(first_value) if clean_text(headers[index])]
    if not label_columns:
        return None
    grade_col = _grade_column(headers)
    if grade_col is not None and grade_col >= first_value:
        grade_col = None

    records: list[Record] = []
    evidence: list[Evidence] = []
    header_labels = {clean_text(header).lower() for header in headers if header}
    for row_index in range(start, len(table.rows)):
        row = table.rows[row_index]
        if is_footnote_row(row):
            continue
        grade, condition = _row_label(row, label_columns, grade_col)
        if grade and (
            grade.lower() in header_labels or len(grade) > 40
        ):
            continue
        properties: dict[str, ExtractedValue] = {}
        for column, prop, header in columns:
            if column >= len(row):
                continue
            cell = clean_text(row[column])
            if not cell or cell in SKIP_VALUES:
                continue
            unit = _header_unit(header, prop)
            parsed = _parse_property_value(
                cell, prop, unit, _header_bound(header)
            )
            if parsed is None:
                continue
            value_unit = parsed.pop("unit", None) or unit
            existing = properties.get(prop)
            if existing is not None:
                # ASTM repeats every property in ksi and MPa; keep MPa.
                if existing.unit == "MPa" and value_unit != "MPa":
                    continue
                if value_unit != "MPa" and existing.unit != "MPa":
                    continue
            evidence_id = (
                f"ev:{document.doc_id}:{table.table_id}:r{row_index}:c{column}"
            )
            properties[prop] = ExtractedValue(
                unit=value_unit,
                evidence_id=evidence_id,
                **parsed,
            )
            evidence.append(
                Evidence(
                    evidence_id=evidence_id,
                    page_no=table.page_no,
                    table_id=table.table_id,
                    row=row_index,
                    col=column,
                    quote=cell,
                    artifact_uri="pages.json",
                )
            )
        if not properties:
            continue
        records.append(
            Record(
                record_id=f"rec-{table.table_id}-r{row_index}",
                source_table_id=table.table_id,
                grade=grade,
                condition=condition,
                properties=properties,
            )
        )
    if not records:
        return None
    return ExtractionOutput(records=records, evidence=evidence)


def extract_property_rows(
    table: TableGrid, document: DocumentMeta
) -> ExtractionOutput | None:
    """Read a vertical ``Property | Value`` mechanical table (AMS style)."""

    headers, start = _matrix_headers(table)
    headers, start = _merge_subheader(table, headers, start)
    if len(headers) < 2:
        return None
    label_col = next(
        (
            index
            for index, header in enumerate(headers)
            if re.search(r"\bpropert(?:y|ies)\b", header, re.IGNORECASE)
        ),
        None,
    )
    if label_col is None:
        return None
    value_col = next(
        (
            index
            for index, header in enumerate(headers)
            if index != label_col
            and re.search(
                r"\b(?:value|requirement|limit|minimum|maximum)\b",
                header,
                re.IGNORECASE,
            )
        ),
        None,
    )
    if value_col is None:
        others = [index for index in range(len(headers)) if index != label_col]
        if len(others) != 1:
            return None
        value_col = others[0]

    records: list[Record] = []
    evidence: list[Evidence] = []
    for row_index in range(start, len(table.rows)):
        row = table.rows[row_index]
        if is_footnote_row(row) or max(label_col, value_col) >= len(row):
            continue
        label = clean_text(row[label_col])
        if not label or not PROPERTY_HINT_RE.search(label):
            continue
        prop = canonical_property(label)
        if not prop:
            continue
        cell = clean_text(row[value_col])
        if not cell or cell in SKIP_VALUES:
            continue
        unit = _header_unit(f"{label} {headers[value_col]}", prop)
        parsed = _parse_property_value(cell, prop, unit, _header_bound(label))
        if parsed is None:
            continue
        value_unit = parsed.pop("unit", None) or unit
        evidence_id = (
            f"ev:{document.doc_id}:{table.table_id}:r{row_index}:c{value_col}"
        )
        records.append(
            Record(
                record_id=f"rec-{table.table_id}-r{row_index}",
                source_table_id=table.table_id,
                grade="",
                properties={
                    prop: ExtractedValue(
                        unit=value_unit,
                        evidence_id=evidence_id,
                        **parsed,
                    )
                },
            )
        )
        evidence.append(
            Evidence(
                evidence_id=evidence_id,
                page_no=table.page_no,
                table_id=table.table_id,
                row=row_index,
                col=value_col,
                quote=cell,
                artifact_uri="pages.json",
            )
        )
    if not records:
        return None
    return ExtractionOutput(records=records, evidence=evidence)