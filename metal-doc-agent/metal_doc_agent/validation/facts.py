"""P6-D fact-level checks.

Structural validation (``checks.py``) proves that a value has an evidence cell.
These checks prove that the *value itself* is faithful to the document:

* the record grade really occurs in its source table;
* an element key is a real element symbol (``Hg`` must not become ``H``);
* a text requirement is copied from the cell, not invented;
* a number exists in the raw text, and hardness values use their own scale.
"""

from __future__ import annotations

import re

from ..contracts import (
    DocumentMeta,
    Evidence,
    ExtractedValue,
    Record,
    TableGrid,
    ValidationIssue,
)
from ..tablegrid.normalize import (
    ELEMENTS,
    NUMBER_RE,
    canonical_property,
    clean_text,
)

HARDNESS_SCALES = {"HB", "HRB", "HRC", "HV"}
HARDNESS_RANGES = {
    "HB": (50.0, 650.0),
    "HRB": (20.0, 120.0),
    "HRC": (20.0, 70.0),
    "HV": (50.0, 1200.0),
}
UNIT_SCALE = {
    "HB": "HB",
    "HBW": "HB",
    "HBS": "HB",
    "HRB": "HRB",
    "HRC": "HRC",
    "HV": "HV",
}


def check_facts(
    document: DocumentMeta,
    records: list[Record],
    evidence: list[Evidence],
    tables: list[TableGrid] | None = None,
) -> list[ValidationIssue]:
    table_index = {table.table_id: table for table in tables or []}
    evidence_index = {item.evidence_id: clean_text(item.quote) for item in evidence}
    table_text: dict[str, str] = {}
    for table in tables or []:
        table_text[table.table_id] = _squash(
            " ".join(cell for row in table.rows for cell in row)
        )

    issues: list[ValidationIssue] = []
    for record in records:
        issues.extend(_check_grade(record, table_index, table_text))
        for field, value in (record.properties or {}).items():
            issues.extend(_check_field(record, field, value))
            quote = evidence_index.get(value.evidence_id, "")
            issues.extend(_check_text(record, field, value, quote))
            issues.extend(_check_number(record, field, value, quote))
            issues.extend(_check_unit(record, field, value))
    return issues


def _check_grade(
    record: Record,
    table_index: dict[str, TableGrid],
    table_text: dict[str, str],
) -> list[ValidationIssue]:
    grade = clean_text(record.grade)
    table_id = record.source_table_id
    if not grade or not table_id or table_id not in table_index:
        return []
    text = table_text.get(table_id, "")
    if not text:
        return []
    if _grade_grounded(grade, text):
        return []
    return [
        _issue(
            "GRADE_UNGROUNDED",
            f"grade {grade!r} does not occur in source table {table_id}",
            record_id=record.record_id,
            field="grade",
        )
    ]


def _grade_grounded(grade: str, text: str) -> bool:
    value = _squash(grade)
    if value in text:
        return True
    # 合并单元格里的多牌号组（"Q355B、Q355C"）在源表里是分开的单元格。
    parts = [
        part for part in re.split(r"[、,，;；/]+", grade) if len(clean_text(part)) >= 3
    ]
    if len(parts) > 1 and all(_grade_grounded(part, text) for part in parts):
        return True
    # grade + quality letter ("Q355" + "B") or an OCR footnote letter.
    core = re.sub(r"(?<=[0-9A-Z])[A-Za-z]$", "", value)
    if core != value and core and core in text:
        return True
    # Any cell fully contained in the grade (e.g. cell "Q355" for "Q355B").
    return any(
        len(cell) >= 3 and cell in value for cell in re.split(r"[\s,，、;；]+", text)
    )


def _check_field(
    record: Record, field: str, value: ExtractedValue
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    key = clean_text(field)
    if (
        re.fullmatch(r"[A-Z][a-z]?", key)
        and key not in ELEMENTS
        and canonical_property(key) is None
    ):
        issues.append(
            _issue(
                "ELEMENT_NOT_WHITELISTED",
                f"property key {key!r} looks like an element but is not in the "
                "element whitelist",
                record_id=record.record_id,
                field=field,
            )
        )
    return issues


def _check_text(
    record: Record, field: str, value: ExtractedValue, quote: str
) -> list[ValidationIssue]:
    if value.comparator != "text":
        return []
    text = clean_text(value.text) or clean_text(value.raw)
    raw = clean_text(value.raw)
    if not text:
        return []
    if not quote:
        return []
    if text in quote or quote in text or (raw and raw in quote):
        return []
    return [
        _issue(
            "TEXT_VALUE_NOT_IN_SOURCE",
            f"text requirement {text!r} is not present in the source cell "
            f"{quote!r}",
            record_id=record.record_id,
            field=field,
        )
    ]


def _check_number(
    record: Record, field: str, value: ExtractedValue, quote: str
) -> list[ValidationIssue]:
    if value.comparator in {"text", "na"}:
        return []
    source = clean_text(value.raw) or quote
    if not source:
        return []
    numbers = [float(match) for match in NUMBER_RE.findall(source.replace(",", ""))]
    if not numbers:
        return []
    expected: list[float] = []
    if value.comparator == "range":
        expected = [
            number
            for number in (value.lower, value.upper)
            if number is not None
        ]
    elif value.value is not None:
        expected = [float(value.value)]
    missing = [
        number
        for number in expected
        if not any(abs(number - found) <= 1e-9 for found in numbers)
    ]
    if not missing:
        return []
    return [
        _issue(
            "VALUE_NOT_IN_SOURCE",
            f"value {missing[0]:g} is not present in raw text {source!r}",
            record_id=record.record_id,
            field=field,
        )
    ]


def _check_unit(
    record: Record, field: str, value: ExtractedValue
) -> list[ValidationIssue]:
    prop = canonical_property(field)
    if prop not in HARDNESS_SCALES or value.value is None:
        return []
    unit = UNIT_SCALE.get(clean_text(value.unit).upper())
    issues: list[ValidationIssue] = []
    if unit and unit != prop:
        issues.append(
            _issue(
                "HARDNESS_SCALE_MISMATCH",
                f"{prop} value carries {unit} unit",
                record_id=record.record_id,
                field=field,
            )
        )
    low, high = HARDNESS_RANGES[prop]
    if not low <= float(value.value) <= high:
        issues.append(
            _issue(
                "HARDNESS_VALUE_OUT_OF_SCALE",
                f"{prop} value {value.value:g} is outside [{low:g}, {high:g}]",
                record_id=record.record_id,
                field=field,
            )
        )
    return issues


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", clean_text(text))


def _issue(
    code: str,
    message: str,
    *,
    record_id: str | None = None,
    field: str | None = None,
) -> ValidationIssue:
    return ValidationIssue(
        level="L2",
        code=code,
        message=message,
        record_id=record_id,
        field=field,
        severity="warn",
    )
