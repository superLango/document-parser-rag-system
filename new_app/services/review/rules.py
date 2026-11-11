"""Deterministic review rules (run before the optional ReviewAgent)."""

from __future__ import annotations

import json
from typing import Any

from hanson_contracts import ReviewFinding

RULESET_VERSION = "m5"


def _finding(
    rule_id: str,
    category: str,
    severity: str,
    target: dict[str, Any],
    message: str,
    *,
    observed: str | None = None,
    expected: str | None = None,
    evidence_refs: list[str] | None = None,
) -> ReviewFinding:
    return ReviewFinding(
        category=category,
        severity=severity,  # type: ignore[arg-type]
        target=target,
        observed=observed,
        expected=expected,
        evidence_refs=evidence_refs or [],
        confidence=0.99,
        source="deterministic",
        rule_id=rule_id,
    )


def _record_target(record: dict[str, Any], property_name: str | None = None) -> dict[str, Any]:
    target = {
        "record_id": record.get("record_id"),
        "table_id": record.get("table_id"),
        "page_no": record.get("page_no"),
    }
    if property_name:
        target["property"] = property_name
    return target


def run_rules(
    records: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    tables: list[dict[str, Any]] | None = None,
) -> list[ReviewFinding]:
    findings: list[ReviewFinding] = []
    evidence_ids = {str(item.get("evidence_id")) for item in evidence}
    seen_ids: set[str] = set()
    seen_grades: dict[str, str] = {}
    table_counts: dict[str, int] = {}

    for record in records:
        if not isinstance(record, dict):
            continue
        record_id = str(record.get("record_id") or "")
        table_id = str(record.get("table_id") or "")
        table_counts[table_id] = table_counts.get(table_id, 0) + 1
        target = _record_target(record)
        if not record_id:
            findings.append(
                _finding(
                    "M5-ID-001",
                    "completeness",
                    "error",
                    target,
                    "record_id is missing",
                )
            )
        elif record_id in seen_ids:
            findings.append(
                _finding(
                    "M5-ID-002",
                    "consistency",
                    "error",
                    target,
                    f"duplicate record_id {record_id}",
                    observed=record_id,
                    expected="unique record_id",
                )
            )
        else:
            seen_ids.add(record_id)

        grade = str(record.get("grade") or "").strip()
        if not grade:
            findings.append(
                _finding(
                    "M5-GRADE-001",
                    "completeness",
                    "error",
                    target,
                    "grade is missing",
                    expected="non-empty grade",
                )
            )
        else:
            seen_grades[grade] = record_id

        properties = record.get("properties") or {}
        if not properties:
            findings.append(
                _finding(
                    "M5-PROP-001",
                    "completeness",
                    "warning",
                    target,
                    "no properties extracted",
                )
            )
        refs = [str(item) for item in record.get("evidence_refs") or []]
        if not refs:
            findings.append(
                _finding(
                    "M5-EVID-001",
                    "evidence",
                    "error",
                    target,
                    "record has no evidence reference",
                )
            )
        else:
            unknown = [ref for ref in refs if ref not in evidence_ids]
            if unknown:
                findings.append(
                    _finding(
                        "M5-EVID-002",
                        "evidence",
                        "error",
                        target,
                        "evidence reference not found",
                        observed=", ".join(unknown),
                        expected="existing evidence_id",
                        evidence_refs=refs,
                    )
                )
        for name, value in properties.items():
            if not isinstance(value, dict):
                continue
            raw = str(value.get("raw") or "").strip()
            numeric = value.get("value")
            if numeric is None and not raw:
                findings.append(
                    _finding(
                        "M5-PROP-002",
                        "completeness",
                        "warning",
                        _record_target(record, name),
                        "property value is empty",
                    )
                )
                continue
            if isinstance(numeric, (int, float)) and numeric < 0:
                findings.append(
                    _finding(
                        "M5-VALUE-001",
                        "semantic",
                        "error",
                        _record_target(record, name),
                        "negative value",
                        observed=str(numeric),
                        expected=">= 0",
                        evidence_refs=refs,
                    )
                )
            if isinstance(numeric, (int, float)) and not value.get("unit"):
                findings.append(
                    _finding(
                        "M5-UNIT-001",
                        "unit",
                        "warning",
                        _record_target(record, name),
                        "numeric value has no unit",
                        observed=str(numeric),
                        expected="unit",
                        evidence_refs=refs,
                    )
                )
            if numeric is None and raw:
                findings.append(
                    _finding(
                        "M5-VALUE-002",
                        "semantic",
                        "warning",
                        _record_target(record, name),
                        "value is not numeric",
                        observed=raw,
                        evidence_refs=refs,
                    )
                )

        conditions = json.dumps(
            record.get("conditions") or {}, ensure_ascii=False, sort_keys=True
        )
        grade_key = f"{grade}|{conditions}"
        if grade_key in seen_grades and grade:
            previous = seen_grades[grade_key]
            if previous != record_id:
                findings.append(
                    _finding(
                        "M5-DUP-001",
                        "consistency",
                        "warning",
                        target,
                        "same grade and conditions appear in multiple records",
                        observed=record_id,
                        expected=previous,
                    )
                )
        if grade:
            seen_grades[grade_key] = record_id

    for table in tables or []:
        table_id = str(table.get("table_id") or "")
        expected = table.get("records")
        if isinstance(expected, int) and table_id in table_counts:
            actual = table_counts[table_id]
            if actual != expected:
                findings.append(
                    _finding(
                        "M5-TABLE-001",
                        "consistency",
                        "warning",
                        {"table_id": table_id},
                        "record count does not match the table summary",
                        observed=str(actual),
                        expected=str(expected),
                    )
                )
    return _dedupe(findings)


def _dedupe(findings: list[ReviewFinding]) -> list[ReviewFinding]:
    seen: set[str] = set()
    unique: list[ReviewFinding] = []
    for finding in findings:
        key = json.dumps(
            {
                "rule": finding.rule_id,
                "target": finding.target,
                "observed": finding.observed,
                "expected": finding.expected,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(finding)
    return unique


def merge_findings(
    deterministic: list[ReviewFinding],
    model: list[ReviewFinding],
) -> list[ReviewFinding]:
    merged = list(deterministic)
    seen = {
        json.dumps(
            {
                "category": item.category,
                "target": item.target,
                "observed": item.observed,
                "expected": item.expected,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        for item in deterministic
    }
    for item in model:
        key = json.dumps(
            {
                "category": item.category,
                "target": item.target,
                "observed": item.observed,
                "expected": item.expected,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return merged
