"""Validation layers L0-L3.5.

L4 (LLM judge) is intentionally omitted from the mock pipeline; it runs only on
suspicious fields once a model is available.
"""

from __future__ import annotations

from ..contracts import (
    AuditReport,
    CoveragePlan,
    DocumentMeta,
    Evidence,
    ExtractedValue,
    Record,
    TableGrid,
    ValidationIssue,
)
from ..coverage.plan import MECHANICAL_PROPS
from ..tablegrid.normalize import ELEMENTS, clean_text
from .facts import check_facts


EXPECTED_UNITS = {
    "Rm": "MPa",
    "Rp0.2": "MPa",
    "A": "%",
    "Z": "%",
    "KV2": "J",
    "E": "GPa",
}


def validate(
    document: DocumentMeta,
    records: list[Record],
    evidence: list[Evidence],
    coverage: CoveragePlan,
    tables: list[TableGrid] | None = None,
) -> AuditReport:
    issues: list[ValidationIssue] = []
    evidence_index = {item.evidence_id: item for item in evidence}
    table_index = {table.table_id: table for table in tables or []}

    # L0: schema-level sanity (Pydantic already enforced types).
    if not document.standard_no:
        issues.append(_issue("L0", "MISSING_STANDARD_NO", "standard_no was not parsed", severity="warn"))
    if not records:
        issues.append(
            _issue(
                "L0",
                "NO_RECORDS",
                "no records extracted; mock extractor may not cover this table profile",
                severity="warn",
            )
        )

    for record in records:
        if not record.record_id:
            issues.append(
                _issue("L0", "MISSING_RECORD_ID", "record has no record_id", severity="error")
            )
        if not record.grade and not record.grade_level:
            issues.append(
                _issue("L0", "MISSING_GRADE", "record has no grade or grade_level", record_id=record.record_id)
            )
        for field, value in record.properties.items():
            if not field:
                issues.append(
                    _issue("L0", "EMPTY_PROPERTY_KEY", "property key is empty", record_id=record.record_id, severity="error")
                )
            issues.extend(_check_structure(record, field, value))
            if not value.evidence_id:
                issues.append(
                    _issue(
                        "L0",
                        "MISSING_EVIDENCE_ID",
                        "value has no evidence_id",
                        record_id=record.record_id,
                        field=field,
                        severity="error",
                    )
                )
            # L1: evidence must resolve, locate a cell, and contain the quote.
            evidence_item = evidence_index.get(value.evidence_id)
            if not evidence_item:
                issues.append(
                    _issue(
                        "L1",
                        "EVIDENCE_NOT_FOUND",
                        "evidence_id does not resolve",
                        record_id=record.record_id,
                        field=field,
                        evidence_id=value.evidence_id,
                        severity="error",
                    )
                )
            else:
                issues.extend(
                    _check_evidence(
                        record, field, value, evidence_item, table_index
                    )
                )
            # L2: domain rules.
            issues.extend(_check_value(record, field, value))

    # L3.5: coverage.
    for item in coverage.items:
        if item.required and item.status == "missing":
            issues.append(
                _issue(
                    "L3.5",
                    "COVERAGE_MISSING",
                    f"required field not covered: {item.field}",
                    field=item.field,
                    severity="warn",
                )
            )
        elif item.required and item.status == "ambiguous":
            issues.append(
                _issue(
                    "L3.5",
                    "COVERAGE_AMBIGUOUS",
                    f"required field is ambiguous: {item.field}",
                    field=item.field,
                    severity="warn",
                )
            )

    # P6-D: fact-level checks over the extracted values themselves.
    issues.extend(check_facts(document, records, evidence, tables))

    errors = sum(1 for issue in issues if issue.severity == "error")
    warns = sum(1 for issue in issues if issue.severity == "warn")
    status = "fail" if errors else ("review" if warns else "pass")

    required = [item for item in coverage.items if item.required]
    found = [item for item in required if item.status == "found"]
    stats = {
        "record_count": len(records),
        "value_count": sum(len(record.properties) for record in records),
        "evidence_count": len(evidence),
        "coverage_required": len(required),
        "coverage_found": len(found),
        "coverage_ambiguous": sum(1 for item in required if item.status == "ambiguous"),
        "coverage_missing": sum(1 for item in required if item.status == "missing"),
        "issue_errors": errors,
        "issue_warnings": warns,
    }

    return AuditReport(
        doc_id=document.doc_id,
        status=status,
        issues=issues,
        coverage=coverage,
        stats=stats,
    )


def _check_structure(
    record: Record, field: str, value: ExtractedValue
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if not value.raw and value.comparator != "na":
        issues.append(
            _issue(
                "L0",
                "MISSING_RAW",
                "value has no raw text",
                record_id=record.record_id,
                field=field,
                severity="error",
            )
        )
    if value.comparator in {"eq", "min", "max"} and value.value is None:
        issues.append(
            _issue(
                "L0",
                "COMPARATOR_VALUE_MISSING",
                f"comparator {value.comparator} requires a numeric value",
                record_id=record.record_id,
                field=field,
                severity="error",
            )
        )
    if value.comparator == "range" and (value.lower is None or value.upper is None):
        issues.append(
            _issue(
                "L0",
                "RANGE_MISSING_BOUND",
                "range value is missing lower or upper bound",
                record_id=record.record_id,
                field=field,
                severity="error",
            )
        )
    if value.comparator == "text" and not (value.text or value.raw):
        issues.append(
            _issue(
                "L0",
                "TEXT_VALUE_MISSING",
                "text comparator requires text",
                record_id=record.record_id,
                field=field,
                severity="error",
            )
        )
    if value.comparator == "na" and (value.value is not None or value.text):
        issues.append(
            _issue(
                "L0",
                "NA_HAS_VALUE",
                "na value must not carry value or text",
                record_id=record.record_id,
                field=field,
                severity="error",
            )
        )
    return issues


def _check_evidence(
    record: Record,
    field: str,
    value: ExtractedValue,
    evidence_item: Evidence,
    table_index: dict[str, TableGrid],
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if not evidence_item.quote:
        issues.append(
            _issue(
                "L1",
                "EMPTY_EVIDENCE_QUOTE",
                "evidence quote is empty",
                record_id=record.record_id,
                field=field,
                evidence_id=value.evidence_id,
                severity="error",
            )
        )
        return issues

    if not table_index or not evidence_item.table_id:
        return issues
    table = table_index.get(evidence_item.table_id)
    if table is None:
        issues.append(
            _issue(
                "L1",
                "EVIDENCE_TABLE_NOT_FOUND",
                f"evidence table {evidence_item.table_id} does not exist",
                record_id=record.record_id,
                field=field,
                evidence_id=value.evidence_id,
                severity="error",
            )
        )
        return issues
    if evidence_item.page_no != table.page_no:
        issues.append(
            _issue(
                "L1",
                "EVIDENCE_PAGE_MISMATCH",
                f"evidence page {evidence_item.page_no} != table page {table.page_no}",
                record_id=record.record_id,
                field=field,
                evidence_id=value.evidence_id,
                severity="error",
            )
        )
    if evidence_item.row is None or evidence_item.col is None:
        issues.append(
            _issue(
                "L1",
                "EVIDENCE_LOCATOR_MISSING",
                "table evidence needs row and col",
                record_id=record.record_id,
                field=field,
                evidence_id=value.evidence_id,
                severity="error",
            )
        )
        return issues
    row, col = evidence_item.row, evidence_item.col
    if row < 0 or row >= len(table.rows) or col < 0 or col >= len(table.rows[row]):
        issues.append(
            _issue(
                "L1",
                "EVIDENCE_CELL_OUT_OF_RANGE",
                f"evidence cell ({row},{col}) outside table {table.n_rows}x{table.n_cols}",
                record_id=record.record_id,
                field=field,
                evidence_id=value.evidence_id,
                severity="error",
            )
        )
        return issues
    cell = clean_text(table.rows[row][col])
    quote = clean_text(evidence_item.quote)
    if cell and quote and quote not in cell and cell not in quote:
        issues.append(
            _issue(
                "L1",
                "EVIDENCE_QUOTE_MISMATCH",
                f"quote {quote!r} does not match cell {cell!r}",
                record_id=record.record_id,
                field=field,
                evidence_id=value.evidence_id,
                severity="error",
            )
        )
    expected_suffix = f":{table.table_id}:r{row}:c{col}"
    if expected_suffix not in value.evidence_id:
        issues.append(
            _issue(
                "L1",
                "EVIDENCE_ID_MISMATCH",
                f"evidence id does not match locator {expected_suffix}",
                record_id=record.record_id,
                field=field,
                evidence_id=value.evidence_id,
            )
        )
    return issues


def _check_value(record: Record, field: str, value: ExtractedValue) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if value.comparator == "range":
        if value.lower is None or value.upper is None:
            return issues
        if value.lower > value.upper:
            issues.append(
                _issue(
                    "L2",
                    "RANGE_INVERTED",
                    f"lower bound {value.lower} > upper bound {value.upper}",
                    record_id=record.record_id,
                    field=field,
                    severity="error",
                )
            )
        if value.lower < 0:
            issues.append(
                _issue(
                    "L2",
                    "RANGE_NEGATIVE",
                    f"range lower bound {value.lower} is negative",
                    record_id=record.record_id,
                    field=field,
                    severity="error",
                )
            )
        if field in ELEMENTS and value.upper > 100:
            issues.append(
                _issue(
                    "L2",
                    "CHEMICAL_RANGE_OUT_OF_RANGE",
                    f"chemical range upper bound {value.upper} > 100",
                    record_id=record.record_id,
                    field=field,
                    severity="error",
                )
            )
        if field in {"A", "Z"} and value.upper > 100:
            issues.append(
                _issue(
                    "L2",
                    "PERCENT_OUT_OF_RANGE",
                    f"{field} range upper bound {value.upper} > 100",
                    record_id=record.record_id,
                    field=field,
                    severity="error",
                )
            )
        return issues

    if value.value is None:
        return issues

    if field in ELEMENTS:
        if value.value < 0 or value.value > 100:
            issues.append(
                _issue(
                    "L2",
                    "CHEMICAL_OUT_OF_RANGE",
                    f"chemical value {value.value} outside 0-100",
                    record_id=record.record_id,
                    field=field,
                    severity="error",
                )
            )
        if value.unit not in (None, "%"):
            issues.append(
                _issue(
                    "L2",
                    "CHEMICAL_UNIT_SUSPECT",
                    f"unexpected chemical unit: {value.unit}",
                    record_id=record.record_id,
                    field=field,
                )
            )

    expected_unit = EXPECTED_UNITS.get(field)
    unit = clean_text(value.unit)
    unit_matches = unit == expected_unit
    if field == "KV2" and unit in {"J/cm²", "J/cm2"}:
        unit_matches = True
    if expected_unit and value.unit and not unit_matches:
        issues.append(
            _issue(
                "L2",
                "UNIT_MISMATCH",
                f"{field} expects unit {expected_unit}, got {value.unit}",
                record_id=record.record_id,
                field=field,
            )
        )

    if field in {"Rm", "Rp0.2", "E"} and value.value <= 0:
        issues.append(
            _issue(
                "L2",
                "MECHANICAL_NON_POSITIVE",
                f"{field} must be positive",
                record_id=record.record_id,
                field=field,
                severity="error",
            )
        )
    if field in {"HB", "HRC", "HV"} and value.value <= 0:
        issues.append(
            _issue(
                "L2",
                "HARDNESS_NON_POSITIVE",
                f"{field} must be positive",
                record_id=record.record_id,
                field=field,
                severity="error",
            )
        )
    if field in {"A", "Z"} and (value.value < 0 or value.value > 100):
        issues.append(
            _issue(
                "L2",
                "PERCENT_OUT_OF_RANGE",
                f"{field} must be between 0 and 100",
                record_id=record.record_id,
                field=field,
                severity="error",
            )
        )
    if field in MECHANICAL_PROPS and value.value < 0:
        issues.append(
            _issue(
                "L2",
                "MECHANICAL_NEGATIVE",
                f"{field} must not be negative",
                record_id=record.record_id,
                field=field,
                severity="error",
            )
        )

    return issues


def _issue(
    level: str,
    code: str,
    message: str,
    record_id: str | None = None,
    field: str | None = None,
    evidence_id: str | None = None,
    severity: str = "warn",
) -> ValidationIssue:
    return ValidationIssue(
        level=level,
        code=code,
        message=message,
        record_id=record_id,
        field=field,
        evidence_id=evidence_id,
        severity=severity,
    )
