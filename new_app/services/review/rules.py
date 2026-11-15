"""Deterministic review rules (run before the optional ReviewAgent)."""

from __future__ import annotations

import json
import re
from typing import Any

from hanson_contracts import ReviewFinding

RULESET_VERSION = "m5"

DOC_RULE_IDS = (
    "DOC-NO-RECORDS",
    "DOC-NO-APPLICABLE-TABLES",
    "DOC-NO-TABLES",
    "DOC-UNBOUND-COLUMNS",
    "DOC-DUP-KEYS",
    "DOC-UNIT-MISSING",
    "DOC-LOW-COVERAGE",
    "DOC-CLAUSE-UNMAPPED",
    "DOC-QUALITATIVE-MISSING",
    "DOC-REFERENCE-UNRESOLVED",
    "DOC-INVENTORY-CONFLICT",
)


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
        message=message,
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
    duplicate_keys: set[str] = set()
    table_counts: dict[str, int] = {}

    for record in records:
        if not isinstance(record, dict):
            continue
        record_id = str(record.get("record_id") or "")
        table_id = str(record.get("table_id") or "")
        # Prose/qualitative rows carry requirement text, not a material grade
        # or a numeric measurement; the numeric schema rules do not apply.
        qualitative = str(record.get("profile") or "") == "qualitative"
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
        if not grade and not qualitative:
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
            if (
                isinstance(numeric, (int, float))
                and not value.get("unit")
                # "1.5T" / "10×tb" 把单位写进了原始值，不是缺单位。
                and not re.search(r"[A-Za-z×√]", raw)
            ):
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
            if (
                numeric is None
                and raw
                and not qualitative
                and not (
                    str(record.get("profile") or "") == "chemical_composition"
                    and re.fullmatch(r"(?:余量|平衡|balance|bal\.?|remainder)", raw, re.I)
                )
            ):
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
        if (
            grade_key in seen_grades
            and grade
            and not qualitative
            and grade_key not in duplicate_keys
        ):
            previous = seen_grades[grade_key]
            if previous != record_id:
                duplicate_keys.add(grade_key)
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


def run_document_rules(
    records: list[dict[str, Any]],
    tables: list[dict[str, Any]] | None = None,
    diagnostics: list[dict[str, Any]] | None = None,
    pages: int = 0,
    *,
    min_pages: int = 3,
    unbound_ratio: float = 0.3,
    dup_key_limit: int = 3,
    unit_missing_ratio: float = 0.5,
    unit_min_samples: int = 5,
    low_coverage_ratio: float = 0.5,
    min_tables: int = 2,
) -> list[ReviewFinding]:
    """文档级门禁：0 记录、0 表格、未绑定列、重复键、缺单位、低覆盖。

    这些规则只看整篇文档的统计特征，命中后由 orchestration 转成 feedback。
    """
    table_list = [item for item in (tables or []) if isinstance(item, dict)]
    findings: list[ReviewFinding] = []
    record_counts: dict[str, int] = {}
    for record in records:
        table_id = str(record.get("table_id") or "")
        if table_id:
            record_counts[table_id] = record_counts.get(table_id, 0) + 1

    nonrecord_tables: set[str] = set()
    unrouted_tables: set[str] = set()
    missing_measures: dict[str, set[str]] = {}
    bound_measures: dict[str, set[str]] = {}
    for item in diagnostics or []:
        if not isinstance(item, dict):
            continue
        detail = item.get("detail") or {}
        table_id = str(detail.get("table_id") or "")
        if not table_id:
            continue
        if item.get("code") == "NONRECORD_TABLE":
            nonrecord_tables.add(table_id)
        elif item.get("code") == "UNROUTED_TABLE":
            unrouted_tables.add(table_id)
        elif item.get("code") == "MEASURE_COLUMN_MISSING":
            measure = str(detail.get("measure") or detail.get("column") or "")
            if measure:
                missing_measures.setdefault(table_id, set()).add(measure)
            bound = {str(name) for name in detail.get("bound_measures") or [] if name}
            if bound:
                bound_measures.setdefault(table_id, set()).update(bound)
    # 配方绑定的 measure 在该表中全部缺失：这张表不可能产出任何记录，
    # 即使路由给了它一个配方，也属于“不适用”而不是“抽取失败”。
    unbound_tables = {
        table_id
        for table_id, missing in missing_measures.items()
        if bound_measures.get(table_id)
        and missing >= bound_measures[table_id]
    }
    non_applicable = nonrecord_tables | unrouted_tables | unbound_tables

    if not records and table_list:
        table_ids = {
            str(item.get("table_id") or "") for item in table_list
        } - {""}
        applicable = table_ids - non_applicable
        if table_ids and not applicable:
            # 整篇只有说明/目录/参数表，没有可产出记录的表：这是 UNROUTED，
            # 不是抽取失败，避免把“标准本身无性能表”误判为解析错误。
            findings.append(
                _finding(
                    "DOC-NO-APPLICABLE-TABLES",
                    "coverage",
                    "info",
                    {"level": "document"},
                    "tables were detected but none can produce records",
                    observed=(
                        f"0 records / {len(table_ids)} table(s); "
                        f"{len(unrouted_tables)} unrouted, "
                        f"{len(unbound_tables)} without any bound measure"
                    ),
                    expected=">=1 record table",
                )
            )
        else:
            findings.append(
                _finding(
                    "DOC-NO-RECORDS",
                    "coverage",
                    "error",
                    {"level": "document"},
                    "document contains tables but no records were extracted",
                    observed=f"0 records / {len(table_list)} table(s)",
                    expected=">=1 record",
                )
            )
    if not table_list and pages >= min_pages:
        findings.append(
            _finding(
                "DOC-NO-TABLES",
                "coverage",
                "error",
                {"level": "document"},
                "no tables were detected in a multi-page document",
                observed=f"0 tables / {pages} pages",
                expected=">=1 table",
            )
        )

    unbound: dict[str, dict[str, Any]] = {}
    for item in diagnostics or []:
        if not isinstance(item, dict) or item.get("code") != "MEASURE_COLUMN_MISSING":
            continue
        detail = item.get("detail") or {}
        table_id = str(detail.get("table_id") or "")
        entry = unbound.setdefault(table_id, {"count": 0, "columns": []})
        entry["count"] += 1
        column = str(detail.get("column") or detail.get("measure") or "")
        if column and column not in entry["columns"]:
            entry["columns"].append(column)
    if table_list and unbound and len(unbound) / len(table_list) >= unbound_ratio:
        for table_id in sorted(unbound):
            # 已产出记录的表：缺失的 measure 只是该标准未规定，不是抽取缺陷。
            if record_counts.get(table_id, 0) > 0:
                continue
            # 非记录表 / 完全未匹配配方的表已经在其它规则中处理。
            if table_id in non_applicable:
                continue
            info = unbound[table_id]
            target: dict[str, Any] = {"level": "table" if table_id else "document"}
            if table_id:
                target["table_id"] = table_id
            findings.append(
                _finding(
                    "DOC-UNBOUND-COLUMNS",
                    "structure",
                    "warning",
                    target,
                    "measure columns could not be bound to recipe bindings",
                    observed=(
                        f"{info['count']} unbound column(s): "
                        f"{', '.join(info['columns'][:6])}"
                    ),
                    expected="all measure columns bound",
                )
            )

    duplicates: dict[tuple[str, str, str], int] = {}
    for record in records:
        if str(record.get("profile") or "") == "qualitative":
            # 正文条款按 clause 拆分，同一牌号下多个条款不是重复行。
            continue
        grade = str(record.get("grade") or "").strip()
        if not grade or grade == "~":
            continue
        condition = str(record.get("condition_key") or "")
        if not condition and record.get("conditions"):
            condition = json.dumps(
                record["conditions"], ensure_ascii=False, sort_keys=True
            )
        for name, value in (record.get("properties") or {}).items():
            if not isinstance(value, dict):
                continue
            if value.get("value") is None and not str(value.get("raw") or "").strip():
                continue
            duplicates[(grade, name, condition)] = (
                duplicates.get((grade, name, condition), 0) + 1
            )
    hits = sorted(
        ((key, count) for key, count in duplicates.items() if count > dup_key_limit),
        key=lambda item: (-item[1], item[0]),
    )
    for (grade, name, condition), count in hits[:5]:
        target: dict[str, Any] = {
            "level": "field",
            "grade": grade,
            "property": name,
        }
        if condition:
            target["condition_key"] = condition
        findings.append(
            _finding(
                "DOC-DUP-KEYS",
                "consistency",
                "warning",
                target,
                "same grade and measure repeat across too many records",
                observed=f"{grade}.{name} x{count}",
                expected=f"<= {dup_key_limit}",
            )
        )

    numeric = 0
    missing_unit = 0
    for record in records:
        for value in (record.get("properties") or {}).values():
            if not isinstance(value, dict):
                continue
            number = value.get("value")
            if isinstance(number, bool) or not isinstance(number, (int, float)):
                continue
            numeric += 1
            if not value.get("unit"):
                missing_unit += 1
    if numeric >= unit_min_samples and missing_unit / numeric >= unit_missing_ratio:
        findings.append(
            _finding(
                "DOC-UNIT-MISSING",
                "unit",
                "warning",
                {"level": "document"},
                "most numeric values have no unit binding",
                observed=f"{missing_unit}/{numeric} values without unit",
                expected=f"<= {int(unit_missing_ratio * 100)}%",
            )
        )

    if records and len(table_list) >= min_tables:
        uncovered: list[str] = []
        covered = 0
        for table in table_list:
            table_id = str(table.get("table_id") or "")
            # 说明/目录/尺寸等非记录表本来就不应产出记录，不能算作覆盖失败。
            if table_id in non_applicable:
                continue
            count = table.get("records")
            if not isinstance(count, int):
                count = record_counts.get(table_id, 0)
            if count <= 0:
                uncovered.append(table_id)
            else:
                covered += 1
        eligible = covered + len(uncovered)
        if uncovered and eligible and covered / eligible < low_coverage_ratio:
            findings.append(
                _finding(
                    "DOC-LOW-COVERAGE",
                    "coverage",
                    "warning",
                    {"level": "document", "table_ids": uncovered[:10]},
                    "most detected tables produced no records",
                    observed=f"{covered}/{eligible} tables covered",
                    expected=f">= {int(low_coverage_ratio * 100)}%",
                )
            )

    return findings


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


def run_intelligence_rules(
    intelligence: dict[str, Any] | None,
    inventory: dict[str, Any] | None,
    references: dict[str, Any] | None,
) -> list[ReviewFinding]:
    """Review the document-understanding artifacts (clauses/inventory/refs)."""
    findings: list[ReviewFinding] = []
    items = [
        item
        for item in (inventory or {}).get("items") or []
        if isinstance(item, dict)
    ]
    conflicts = [item for item in items if item.get("conflicts")]
    if conflicts:
        first = conflicts[0]
        findings.append(
            _finding(
                "DOC-INVENTORY-CONFLICT",
                "consistency",
                "warning",
                {
                    "level": "document",
                    "feature": first.get("feature") or first.get("item"),
                },
                f"{len(conflicts)} inventory item(s) have conflicting sources",
                observed="；".join(str(value) for value in (first.get("conflicts") or [])[:3]),
                expected="one method per item",
            )
        )
    stats = (intelligence or {}).get("stats") or {}
    qualitative_items = int(stats.get("qualitative_items") or 0)
    qualitative_records = int(stats.get("qualitative_records") or 0)
    if qualitative_items > qualitative_records:
        findings.append(
            _finding(
                "DOC-QUALITATIVE-MISSING",
                "completeness",
                "warning",
                {"level": "document"},
                f"{qualitative_items - qualitative_records} qualitative item(s) were not projected",
                observed=f"{qualitative_records}/{qualitative_items}",
                expected="all qualitative items projected",
            )
        )
    reference_stats = (references or {}).get("stats") or stats.get("references") or {}
    unresolved = int(reference_stats.get("unresolved") or 0)
    if unresolved:
        findings.append(
            _finding(
                "DOC-REFERENCE-UNRESOLVED",
                "reference",
                "info",
                {"level": "document"},
                f"{unresolved} cited standard(s) are not in the normative-reference list",
                observed=str(unresolved),
                expected="resolved against the normative list",
            )
        )
    projected = {
        str(item.get("feature") or "")
        for item in (intelligence or {}).get("qualitative_items") or []
        if isinstance(item, dict)
    }
    unmapped = [
        item
        for item in items
        if item.get("status") == "probable"
        and "clause" in (item.get("sources") or [])
        and str(item.get("feature") or "") not in projected
    ]
    if unmapped:
        findings.append(
            _finding(
                "DOC-CLAUSE-UNMAPPED",
                "coverage",
                "info",
                {"level": "document"},
                f"{len(unmapped)} clause-only item(s) have no projected row",
                observed="；".join(
                    str(item.get("feature") or item.get("item"))
                    for item in unmapped[:5]
                ),
                expected="mapped to a numeric or qualitative row",
            )
        )
    return findings


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
