from __future__ import annotations

from hanson_contracts import AcceptedSnapshot

from services.orchestration.shadow import compare_shadow
from services.orchestration.snapshots import build_snapshot


def _record(
    record_id: str,
    grade: str,
    *,
    table_id: str = "T1",
    **props: float,
) -> dict:
    return {
        "record_id": record_id,
        "table_id": table_id,
        "grade": grade,
        "properties": {
            name: {"value": value, "unit": "MPa"} for name, value in props.items()
        },
    }


def test_shadow_passes_when_records_and_fields_are_stable() -> None:
    records = [_record("R1", "Q355B", Rm=470)]
    snapshot = build_snapshot(
        records, document_id="doc-1", document_version=1, run_id="run-1"
    )
    metrics = compare_shadow(records, records, snapshot)
    assert metrics["passed"] is True
    assert metrics["records_ok"] and metrics["accepted_ok"] and metrics["errors_ok"]


def test_shadow_detects_record_regression() -> None:
    baseline = [_record("R1", "Q355B", Rm=470), _record("R2", "Q235B", Rm=400)]
    candidate = [_record("R1", "Q355B", Rm=470)]
    metrics = compare_shadow(baseline, candidate, None)
    assert metrics["records_ok"] is False
    assert metrics["passed"] is False


def test_shadow_detects_accepted_region_change() -> None:
    baseline = [_record("R1", "Q355B", Rm=470)]
    snapshot = build_snapshot(
        baseline, document_id="doc-1", document_version=1, run_id="run-1"
    )
    candidate = [_record("R1", "Q355B", Rm=480)]
    metrics = compare_shadow(baseline, candidate, snapshot)
    assert metrics["candidate_accepted_changes"] == 1
    assert metrics["accepted_ok"] is False
    assert metrics["passed"] is False


def test_shadow_detects_new_errors() -> None:
    records = [_record("R1", "Q355B", Rm=470)]
    metrics = compare_shadow(
        records,
        records,
        None,
        baseline_diagnostics=[{"code": "X", "severity": "warning"}],
        candidate_diagnostics=[
            {"code": "X", "severity": "warning"},
            {"code": "Y", "severity": "error"},
        ],
    )
    assert metrics["candidate_errors"] == 1
    assert metrics["errors_ok"] is False
    assert metrics["passed"] is False


def test_shadow_without_snapshot_ignores_accepted_check() -> None:
    records = [_record("R1", "Q355B", Rm=470)]
    metrics = compare_shadow(records, [_record("R1", "Q355B", Rm=480)], None)
    assert metrics["accepted_ok"] is True
    assert metrics["passed"] is True


def test_shadow_with_empty_snapshot_treats_all_as_new() -> None:
    records = [_record("R1", "Q355B", Rm=470)]
    metrics = compare_shadow(
        records, records, AcceptedSnapshot(document_id="doc-1", run_id="run-1")
    )
    assert metrics["passed"] is True
