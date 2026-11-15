from __future__ import annotations

import json

from services.orchestration.feedback.actions import (
    TIER_AUTO,
    TIER_HUMAN,
    TIER_REVIEW,
    classify_action,
)
from services.orchestration.feedback.memory import (
    CaseStore,
    header_fingerprint,
    summarize_cases,
)
from services.orchestration.feedback.regression import (
    compare_snapshots,
    metrics_from_records,
    snapshot_from_documents,
)
from services.orchestration.feedback.regression import (
    gate as regression_gate,
)


def _table(headers: list[str], section: str = "mechanical") -> dict:
    return {
        "table_id": "T1",
        "header_paths": [headers],
        "section_kind": section,
    }


def test_action_tiers() -> None:
    assert classify_action(level="L1", operator="table_repair.add")["tier"] == TIER_AUTO
    assert classify_action(level="L2", ops=[])["tier"] == TIER_REVIEW
    assert classify_action(level="L3")["tier"] == TIER_HUMAN
    assert classify_action(level="L3")["requires_confirmation"] is True


def test_risky_ops_force_review() -> None:
    removed = classify_action(
        level="L1",
        ops=[{"op": "remove", "path": "/bindings/measures/Old"}],
    )
    strategy = classify_action(
        level="L1",
        ops=[{"op": "replace", "path": "/rules/strategy_chain", "value": []}],
    )
    advisory = classify_action(level="L1", advisory_count=1)
    assert removed["tier"] == TIER_REVIEW
    assert strategy["tier"] == TIER_REVIEW
    assert advisory["tier"] == TIER_REVIEW


def test_header_fingerprint_ignores_numbers_and_units() -> None:
    left = header_fingerprint(_table(["牌号", "Rm MPa", "Rp0.2 MPa"]))
    right = header_fingerprint(_table(["牌号", "Rm(MPa)", "Rp0.2/MPa"]))
    assert left == right
    other = header_fingerprint(_table(["牌号", "KV2 J", "KU2 J"]))
    assert left != other


def test_case_store_remembers_and_finds(tmp_path) -> None:
    store = CaseStore(tmp_path / "cases.json")
    case = {
        "fingerprint": "abc123",
        "concept_id": "mechanical.room_tensile",
        "rule_id": "DOC-UNBOUND-COLUMNS",
        "level": "L2",
        "operator": "recipe.binding_override",
        "patch": {"ops": [{"op": "add", "path": "/bindings/measures/C", "value": {}}]},
        "action_tier": "review",
        "feedback_id": "fb-1",
    }
    store.remember(case)
    store.remember(case)
    assert len(store.load()) == 1
    found = store.find("abc123", "mechanical.room_tensile")
    assert len(found) == 1
    assert found[0]["feedback_id"] == "fb-1"
    assert store.find("abc123", "chemical.composition") == []


def test_case_summary_counts_tiers_and_concepts(tmp_path) -> None:
    store = CaseStore(tmp_path / "cases.json")
    for index, tier in enumerate(["auto", "review", "review"]):
        store.remember(
            {
                "fingerprint": f"fp{index}",
                "concept_id": "mechanical.impact",
                "patch": {"ops": []},
                "action_tier": tier,
            }
        )
    summary = summarize_cases(store.load())
    assert summary["total"] == 3
    assert summary["by_tier"] == {"auto": 1, "review": 2}
    assert summary["concepts"] == {"mechanical.impact": 3}
    assert summary["fingerprints"] == 3


def test_regression_passes_on_unchanged_snapshot() -> None:
    baseline = snapshot_from_documents(
        [
            {"name": "A.pdf", "status": "STRUCTURED_READY", "records": 10, "fields": 40},
            {"name": "B.pdf", "status": "STRUCTURED_READY", "records": 5, "fields": 20},
        ]
    )
    result = compare_snapshots(baseline, baseline)
    assert result["passed"] is True
    assert result["regressions"] == []


def test_regression_fails_on_status_or_record_drop() -> None:
    baseline = snapshot_from_documents(
        [
            {"name": "A.pdf", "status": "STRUCTURED_READY", "records": 10, "fields": 40},
            {"name": "B.pdf", "status": "STRUCTURED_READY", "records": 10, "fields": 40},
        ]
    )
    current = snapshot_from_documents(
        [
            {"name": "A.pdf", "status": "REVIEW_FAILED", "records": 0, "fields": 0},
            {"name": "B.pdf", "status": "STRUCTURED_READY", "records": 5, "fields": 20},
        ]
    )
    result = compare_snapshots(baseline, current)
    assert result["passed"] is False
    reasons = {item["name"]: item["reason"] for item in result["regressions"]}
    assert reasons == {"A.pdf": "status_regressed", "B.pdf": "records_dropped"}


def test_regression_gate_skips_when_unconfigured(tmp_path) -> None:
    result = regression_gate(tmp_path / "missing.json", tmp_path / "also-missing.json")
    assert result["passed"] is True
    assert result["skipped"] is True


def test_metrics_from_records_counts_placeholders_and_duplicates() -> None:
    records = [
        {"record_id": "R1", "grade": "~", "properties": {"Rm": {"raw": "470"}}},
        {"record_id": "R2", "grade": "Q355B", "properties": {"Rm": {"raw": "470"}}},
        {"record_id": "R3", "grade": "Q355B", "properties": {"Rm": {"raw": "470"}}},
        {"record_id": "R4", "grade": "Q355B", "properties": {"Rm": {"raw": "470"}}},
        {"record_id": "R5", "grade": "Q355B", "properties": {"Rm": {"raw": "470"}}},
    ]
    metrics = metrics_from_records(records)
    assert metrics["records"] == 5
    assert metrics["fields"] == 5
    assert metrics["placeholders"] == 1
    assert metrics["duplicates"] == 1


def test_regression_fails_when_placeholders_or_duplicates_increase() -> None:
    baseline = snapshot_from_documents(
        [
            {
                "name": "A.pdf",
                "status": "STRUCTURED_READY",
                "records": 10,
                "fields": 40,
                "placeholders": 1,
                "duplicates": 0,
            }
        ]
    )
    current = snapshot_from_documents(
        [
            {
                "name": "A.pdf",
                "status": "STRUCTURED_READY",
                "records": 10,
                "fields": 40,
                "placeholders": 3,
                "duplicates": 2,
            }
        ]
    )
    result = compare_snapshots(baseline, current)
    assert result["passed"] is False
    assert {item["reason"] for item in result["regressions"]} == {
        "placeholders_increased",
        "duplicates_increased",
    }


def test_regression_fails_when_complete_rows_drop() -> None:
    baseline = snapshot_from_documents(
        [
            {
                "name": "A.pdf",
                "status": "STRUCTURED_READY",
                "records": 10,
                "fields": 40,
                "complete_rows": 20,
            }
        ]
    )
    current = snapshot_from_documents(
        [
            {
                "name": "A.pdf",
                "status": "STRUCTURED_READY",
                "records": 10,
                "fields": 40,
                "complete_rows": 10,
            }
        ]
    )
    result = compare_snapshots(baseline, current)
    assert result["passed"] is False
    assert result["regressions"][0]["reason"] == "complete_rows_dropped"


def test_regression_gate_blocks_promotion_on_regression(tmp_path) -> None:
    baseline = tmp_path / "baseline.json"
    current = tmp_path / "current.json"
    baseline.write_text(
        json.dumps(
            {
                "documents": [
                    {"name": "A.pdf", "status": "STRUCTURED_READY", "records": 10, "fields": 40}
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    current.write_text(
        json.dumps(
            {
                "documents": [
                    {"name": "A.pdf", "status": "REVIEW_FAILED", "records": 0, "fields": 0}
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    result = regression_gate(baseline, current)
    assert result["passed"] is False
    assert result["skipped"] is False
    assert result["regressions"][0]["reason"] == "status_regressed"


def test_regression_tolerates_small_record_drop_and_missing() -> None:
    baseline = snapshot_from_documents(
        [{"name": "A.pdf", "status": "STRUCTURED_READY", "records": 10, "fields": 40}]
    )
    tolerated = snapshot_from_documents(
        [{"name": "A.pdf", "status": "STRUCTURED_READY", "records": 9, "fields": 36}]
    )
    assert compare_snapshots(baseline, tolerated)["passed"] is True
    missing = compare_snapshots(baseline, {})
    assert missing["passed"] is False
    assert missing["regressions"][0]["reason"] == "missing"
