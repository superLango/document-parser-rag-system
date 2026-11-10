"""IR-backed deterministic matrix extraction (P6-B).

The first extractor wired to the unified table IR. It reads grade, quality and
measure cells from :class:`TableIR` instead of re-parsing ``TableGrid.rows``,
but follows the legacy :func:`extract_bound_matrix` rules cell for cell. The
pipeline runs both paths and records a diff, so the IR is proven equivalent
before it is allowed to replace the legacy reader.
"""

from __future__ import annotations

from typing import Any

from ..contracts import (
    ColumnBindingResult,
    DocumentMeta,
    Evidence,
    ExtractedValue,
    Record,
    TableIR,
)
from ..tablegrid.normalize import (
    canonical_property,
    clean_text,
)
from .base import ExtractionOutput
from .matrix import (
    CONDITION_HEADER_RE,
    GRADE_HEADER_MARKERS,
    LABEL_HEADER_MARKERS,
    PROPERTY_MATRIX_PROFILES,
    SKIP_VALUES,
    TARGET_PROPERTIES,
    VALUE_RE,
    _combine_grades,
    _comparator,
    _condition,
    _label_unit,
    _normalize_condition,
    _parse_matrix_value,
    extract_element_rows,
    extract_hardness_rows,
    reported_element_records,
)


def extract_element_matrix_ir(
    ir: TableIR, document: DocumentMeta
) -> ExtractionOutput | None:
    """Read an element-row chemistry table from the IR.

    Delegates to the same reader as :func:`extract_element_matrix`, so the
    dual-run diff can prove the IR carries the same chemistry facts as the
    grid, including side-by-side element blocks and min/max ranges.
    """

    if ir.profile != "chemical_composition":
        return None
    output = extract_element_rows(
        table_id=ir.table_id,
        page_no=ir.page_no,
        doc_id=document.doc_id,
        rows=_row_matrix(ir),
        header_paths=ir.header_paths,
        header_rows=ir.header_rows,
        notes=_notes(ir),
    )
    if output is None:
        return None
    existing = {key for record in output.records for key in record.properties}
    extra_records, extra_evidence = reported_element_records(
        ir.table_id,
        ir.page_no,
        document.doc_id,
        _note_cells(ir),
        existing,
    )
    output.records.extend(extra_records)
    output.evidence.extend(extra_evidence)
    return output


def _note_cells(ir: TableIR) -> list[tuple[str, int | None, int | None]]:
    notes: list[tuple[str, int | None, int | None]] = []
    seen: set[str] = set()
    for cell in ir.cells:
        if cell.raw_role != "footnote":
            continue
        text = clean_text(cell.text)
        if text and text not in seen:
            seen.add(text)
            notes.append((text, cell.row, cell.col))
    for note in ir.footnotes:
        text = clean_text(note)
        if text and text not in seen:
            seen.add(text)
            notes.append((text, None, None))
    return notes


def _notes(ir: TableIR) -> str:
    parts = list(ir.footnotes)
    if ir.caption:
        parts.append(ir.caption)
    parts.extend(cell.text for cell in ir.cells if cell.raw_role == "footnote")
    return clean_text(" ".join(parts))


def extract_bound_matrix_ir(
    ir: TableIR,
    binding: ColumnBindingResult,
    document: DocumentMeta,
) -> ExtractionOutput | None:
    """Read a condition matrix from the IR with legacy-compatible output."""

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

    rows = _rows(ir)
    footnote_rows = {
        cell.row for cell in ir.cells if cell.raw_role == "footnote"
    }
    records: list[Record] = []
    evidence: list[Evidence] = []
    for row_index in range(ir.header_rows, ir.n_rows):
        if row_index in footnote_rows:
            continue
        row = rows.get(row_index, {})
        grade_text = clean_text(_text(row, grade_col))
        quality_text = (
            clean_text(_text(row, quality_col))
            if quality_col is not None
            else ""
        )
        grades = _combine_grades(grade_text, quality_text)
        if not grades:
            continue
        for measure in measures:
            cell = clean_text(_text(row, measure.column))
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
                    f"ev:{document.doc_id}:{ir.table_id}:"
                    f"r{row_index}:c{measure.column}{suffix}"
                )
                records.append(
                    Record(
                        record_id=(
                            f"rec-{ir.table_id}-r{row_index}-c{measure.column}{suffix}"
                        ),
                        source_table_id=ir.table_id,
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
                        page_no=ir.page_no,
                        table_id=ir.table_id,
                        row=row_index,
                        col=measure.column,
                        quote=cell,
                        artifact_uri="pages.json",
                    )
                )
    if not records:
        return None
    return ExtractionOutput(records=records, evidence=evidence)


def extract_property_matrix_ir(
    ir: TableIR, document: DocumentMeta
) -> ExtractionOutput | None:
    """Read a ``性能 × 温度`` matrix from the IR."""

    if ir.profile not in PROPERTY_MATRIX_PROFILES:
        return None
    headers, start = _matrix_headers_ir(ir)
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

    rows = _rows(ir)
    footnote_rows = {cell.row for cell in ir.cells if cell.raw_role == "footnote"}
    records: list[Record] = []
    evidence: list[Evidence] = []
    for row_index in range(start, ir.n_rows):
        if row_index in footnote_rows:
            continue
        row = rows.get(row_index, {})
        label = clean_text(row.get(label_col, ""))
        prop = canonical_property(label)
        if not prop:
            continue
        unit = _label_unit(label, prop)
        grade = clean_text(row.get(grade_col, "")) if grade_col is not None else ""
        for column, condition in condition_cols:
            cell = clean_text(row.get(column, ""))
            if cell in SKIP_VALUES:
                continue
            parsed = _parse_matrix_value(cell, prop, label)
            if parsed is None:
                continue
            evidence_id = (
                f"ev:{document.doc_id}:{ir.table_id}:r{row_index}:c{column}"
            )
            records.append(
                Record(
                    record_id=f"rec-{ir.table_id}-r{row_index}-c{column}",
                    source_table_id=ir.table_id,
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
                    page_no=ir.page_no,
                    table_id=ir.table_id,
                    row=row_index,
                    col=column,
                    quote=cell,
                    artifact_uri="pages.json",
                )
            )
    if not records:
        return None
    return ExtractionOutput(records=records, evidence=evidence)


def extract_hardness_minmax_ir(
    ir: TableIR, document: DocumentMeta
) -> ExtractionOutput | None:
    """Read minimum/maximum hardness columns from the IR."""

    return extract_hardness_rows(
        table_id=ir.table_id,
        page_no=ir.page_no,
        doc_id=document.doc_id,
        rows=_row_matrix(ir),
        header_paths=ir.header_paths,
        header_rows=ir.header_rows,
    )


def _matrix_headers_ir(ir: TableIR) -> tuple[list[str], int]:
    headers = [
        " ".join(clean_text(part) for part in path if clean_text(part))
        for path in ir.header_paths
    ]
    if headers and len(headers) >= 2 and not any(len(header) > 40 for header in headers):
        return headers, ir.header_rows
    first = _rows(ir).get(0, {})
    if first:
        return [clean_text(first.get(index, "")) for index in range(ir.n_cols)], 1
    return [], 0


def compare_extraction_outputs(
    legacy: ExtractionOutput | None, current: ExtractionOutput | None
) -> dict:
    """Diff the legacy and IR matrix outputs for one table."""

    if legacy is None and current is None:
        return {"status": "skipped", "legacy_records": 0, "ir_records": 0}
    if legacy is None or current is None:
        return {
            "status": "mismatch",
            "legacy_records": len(legacy.records) if legacy else 0,
            "ir_records": len(current.records) if current else 0,
            "records_equal": False,
            "evidence_equal": False,
            "detail": "one path produced no output",
        }
    records_equal = _dumps(legacy.records) == _dumps(current.records)
    evidence_equal = _dumps(legacy.evidence) == _dumps(current.evidence)
    payload = {
        "status": "identical" if records_equal and evidence_equal else "mismatch",
        "legacy_records": len(legacy.records),
        "ir_records": len(current.records),
        "records_equal": records_equal,
        "evidence_equal": evidence_equal,
    }
    if not records_equal:
        payload["detail"] = _record_detail(legacy.records, current.records)
    return payload


def _rows(ir: TableIR) -> dict[int, dict[int, str]]:
    rows: dict[int, dict[int, str]] = {}
    for cell in ir.cells:
        rows.setdefault(cell.row, {})[cell.col] = cell.text
    return rows


def _row_matrix(ir: TableIR) -> list[list[str]]:
    rows = _rows(ir)
    return [
        [rows.get(row_index, {}).get(column, "") for column in range(ir.n_cols)]
        for row_index in range(ir.n_rows)
    ]


def _text(row: dict[int, str], column: int | None) -> str:
    if column is None:
        return ""
    return row.get(column, "")


def _dumps(items: list) -> list[dict]:
    return [
        item.model_dump(mode="json")
        for item in sorted(items, key=lambda value: value.record_id if hasattr(value, "record_id") else value.evidence_id)
    ]


def _record_detail(legacy: list[Record], current: list[Record]) -> str:
    left = {record.record_id for record in legacy}
    right = {record.record_id for record in current}
    missing = sorted(left - right)
    extra = sorted(right - left)
    if missing or extra:
        return f"missing={missing[:5]} extra={extra[:5]}"
    changed = next(
        (
            left_record.record_id
            for left_record in legacy
            for right_record in current
            if left_record.record_id == right_record.record_id
            and left_record.model_dump(mode="json")
            != right_record.model_dump(mode="json")
        ),
        "",
    )
    return f"changed={changed}"
