from __future__ import annotations

import asyncio

from hanson_contracts import ReviewRequest

from services.review.config import Settings
from services.review.rules import run_document_rules
from services.review.service import ReviewService


def _record(
    record_id: str,
    grade: str,
    *,
    table_id: str = "T1",
    unit: str = "MPa",
    **props: float,
) -> dict:
    return {
        "record_id": record_id,
        "table_id": table_id,
        "grade": grade,
        "properties": {
            name: {"value": value, "unit": unit} for name, value in props.items()
        },
        "evidence_refs": [record_id],
    }


def _rule_ids(findings) -> set[str]:  # noqa: ANN001 - test helper
    return {item.rule_id for item in findings}


def test_no_records_is_error() -> None:
    findings = run_document_rules([], [{"table_id": "T1", "records": 0}])
    assert _rule_ids(findings) == {"DOC-NO-RECORDS"}
    assert findings[0].severity == "error"
    assert findings[0].target["level"] == "document"


def test_all_nonrecord_tables_are_unrouted_not_failed() -> None:
    tables = [{"table_id": "T1", "records": 0}, {"table_id": "T2", "records": 0}]
    diagnostics = [
        {"code": "NONRECORD_TABLE", "detail": {"table_id": "T1"}},
        {"code": "NONRECORD_TABLE", "detail": {"table_id": "T2"}},
    ]
    findings = run_document_rules([], tables, diagnostics)
    assert _rule_ids(findings) == {"DOC-NO-APPLICABLE-TABLES"}
    assert findings[0].severity == "info"


def test_unrouted_and_unbound_tables_are_not_failures() -> None:
    tables = [{"table_id": "T1"}, {"table_id": "T2"}, {"table_id": "T3"}]
    diagnostics = [
        {"code": "UNROUTED_TABLE", "message": "no recipe", "detail": {"table_id": "T1"}},
        {"code": "UNROUTED_TABLE", "message": "no recipe", "detail": {"table_id": "T2"}},
        {
            "code": "MEASURE_COLUMN_MISSING",
            "message": "missing",
            "detail": {
                "table_id": "T3",
                "measure": "HRC",
                "bound_measures": ["HB", "HRC"],
            },
        },
        {
            "code": "MEASURE_COLUMN_MISSING",
            "message": "missing",
            "detail": {
                "table_id": "T3",
                "measure": "HB",
                "bound_measures": ["HB", "HRC"],
            },
        },
    ]
    findings = run_document_rules([], tables, diagnostics)
    rule_ids = _rule_ids(findings)
    assert "DOC-NO-APPLICABLE-TABLES" in rule_ids
    assert "DOC-NO-RECORDS" not in rule_ids
    assert findings[0].severity == "info"


def test_partially_bound_table_still_fails() -> None:
    tables = [{"table_id": "T1"}]
    diagnostics = [
        {
            "code": "MEASURE_COLUMN_MISSING",
            "message": "missing",
            "detail": {
                "table_id": "T1",
                "measure": "HRC",
                "bound_measures": ["HB", "HRC"],
            },
        }
    ]
    findings = run_document_rules([], tables, diagnostics)
    rule_ids = _rule_ids(findings)
    assert "DOC-NO-RECORDS" in rule_ids
    assert "DOC-NO-APPLICABLE-TABLES" not in rule_ids
    assert findings[0].severity == "error"


def test_mixed_nonrecord_and_binding_failure_still_fails() -> None:
    tables = [{"table_id": "T1", "records": 0}, {"table_id": "T2", "records": 0}]
    diagnostics = [{"code": "NONRECORD_TABLE", "detail": {"table_id": "T1"}}]
    findings = run_document_rules([], tables, diagnostics)
    assert "DOC-NO-RECORDS" in _rule_ids(findings)


def test_no_tables_in_long_document() -> None:
    findings = run_document_rules([], [], [], pages=5)
    assert _rule_ids(findings) == {"DOC-NO-TABLES"}
    assert findings[0].severity == "error"


def test_no_tables_in_short_document_is_ignored() -> None:
    assert run_document_rules([], [], [], pages=2) == []


def test_unbound_columns_ratio() -> None:
    tables = [{"table_id": "T1"}, {"table_id": "T2"}]
    diagnostics = [
        {
            "code": "MEASURE_COLUMN_MISSING",
            "message": "unbound",
            "detail": {"table_id": "T1", "column": "Rm"},
        },
        {
            "code": "MEASURE_COLUMN_MISSING",
            "message": "unbound",
            "detail": {"table_id": "T2", "column": "A"},
        },
    ]
    findings = run_document_rules(
        [_record("R1", "Q355B", Rm=470)],
        tables,
        diagnostics,
    )
    assert "DOC-UNBOUND-COLUMNS" in _rule_ids(findings)
    # T1 已产出记录，缺失 measure 只是该标准未规定，不再误报。
    assert {item.target["table_id"] for item in findings} == {"T2"}
    assert all(item.target["level"] == "table" for item in findings)


def test_duplicate_keys_over_limit() -> None:
    records = [
        _record(f"R{index}", "Q355B", Rm=470) for index in range(1, 6)
    ]
    findings = run_document_rules(records, [{"table_id": "T1"}])
    dup = [item for item in findings if item.rule_id == "DOC-DUP-KEYS"]
    assert len(dup) == 1
    assert dup[0].target == {"level": "field", "grade": "Q355B", "property": "Rm"}


def test_duplicate_keys_within_limit() -> None:
    records = [_record(f"R{index}", "Q355B", Rm=470) for index in range(1, 4)]
    findings = run_document_rules(records, [{"table_id": "T1"}])
    assert "DOC-DUP-KEYS" not in _rule_ids(findings)


def test_duplicate_keys_ignore_distinct_conditions() -> None:
    records = []
    for index in range(1, 6):
        record = _record(f"R{index}", "Q355B", Rm=470)
        record["condition_key"] = f"Batch-A{index}"
        records.append(record)
    findings = run_document_rules(records, [{"table_id": "T1"}])
    assert "DOC-DUP-KEYS" not in _rule_ids(findings)


def test_unit_missing_ratio() -> None:
    records = [
        _record(f"R{index}", f"G{index}", Rm=470, unit="") for index in range(1, 6)
    ]
    findings = run_document_rules(records, [{"table_id": "T1"}])
    assert "DOC-UNIT-MISSING" in _rule_ids(findings)


def test_low_table_coverage() -> None:
    tables = [
        {"table_id": "T1", "records": 1},
        {"table_id": "T2", "records": 0},
        {"table_id": "T3", "records": 0},
    ]
    findings = run_document_rules(
        [_record("R1", "Q355B", Rm=470)], tables
    )
    coverage = [item for item in findings if item.rule_id == "DOC-LOW-COVERAGE"]
    assert len(coverage) == 1
    assert coverage[0].target["table_ids"] == ["T2", "T3"]


def test_low_coverage_ignores_non_record_tables() -> None:
    tables = [
        {"table_id": "T1", "records": 1},
        {"table_id": "T2", "records": 0},
        {"table_id": "T3", "records": 0},
    ]
    diagnostics = [
        {"code": "NONRECORD_TABLE", "detail": {"table_id": "T2"}},
        {"code": "UNROUTED_TABLE", "detail": {"table_id": "T3"}},
    ]
    findings = run_document_rules(
        [_record("R1", "Q355B", Rm=470)], tables, diagnostics
    )
    assert "DOC-LOW-COVERAGE" not in _rule_ids(findings)


def test_review_service_counts_document_findings() -> None:
    async def scenario() -> None:
        service = ReviewService(Settings(use_agent=False))
        report = await service.review(
            ReviewRequest(
                run_id="run-doc-empty",
                records=[],
                evidence=[],
                tables=[{"table_id": "T1", "records": 0}],
                pages=4,
            )
        )
        assert report.status == "fail"
        assert report.stats["document_findings"] == 1
        assert report.stats["deterministic_errors"] == 1
        assert report.findings[0].message

    asyncio.run(scenario())


def test_feedback_payloads_from_document_findings() -> None:
    from services.orchestration.feedback.service import feedback_from_findings

    findings = run_document_rules([], [{"table_id": "T1", "records": 0}])
    payloads = feedback_from_findings("run-1", "doc-1", findings)
    assert len(payloads) == 1
    payload = payloads[0]
    assert payload.target["level"] == "document"
    assert payload.target["rule_id"] == "DOC-NO-RECORDS"
    assert payload.target["document_id"] == "doc-1"
    assert payload.reporter == "review"
    assert payload.description


def test_document_target_fixed_rules() -> None:
    from services.orchestration.feedback.service import _document_target_fixed

    before = [_record(f"R{index}", "Q355B", Rm=470) for index in range(1, 5)]
    assert _document_target_fixed("DOC-NO-RECORDS", [], before, [], [])
    assert not _document_target_fixed("DOC-NO-RECORDS", before, before, [], [])
    assert _document_target_fixed(
        "DOC-UNBOUND-COLUMNS",
        before,
        before,
        [{"code": "MEASURE_COLUMN_MISSING", "severity": "warning"}],
        [],
    )
    duplicate = before + [_record("R5", "Q355B", Rm=470)]
    assert _document_target_fixed("DOC-DUP-KEYS", duplicate, before, [], [])
    conditioned = []
    for index in range(1, 6):
        record = _record(f"R{index}", "Q355B", Rm=470)
        record["condition_key"] = f"Batch-A{index}"
        conditioned.append(record)
    assert _document_target_fixed("DOC-DUP-KEYS", duplicate, conditioned, [], [])
    missing_unit = [_record(f"R{index}", f"G{index}", Rm=470, unit="") for index in range(1, 6)]
    assert _document_target_fixed("DOC-UNIT-MISSING", missing_unit, before, [], [])
