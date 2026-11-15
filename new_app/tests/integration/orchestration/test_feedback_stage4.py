from __future__ import annotations

from services.orchestration.feedback.gates import evaluate_gates
from services.orchestration.feedback.table_repair import (
    apply_table_repair,
    apply_table_repair_to_ocr,
    extract_table_repair,
    validate_table_repair_spec,
)


def _table() -> dict:
    return {
        "table_id": "T1",
        "page_no": 3,
        "caption": "表1 力学性能",
        "header_paths": [["牌号", "Rm"]],
        "rows": [["牌号", "Rm"], ["Q355B", "590"], ["Q355C", "600"]],
    }


def test_valid_table_repair_spec_is_accepted() -> None:
    spec, problems = validate_table_repair_spec(
        {"header_rows": 1, "patch_cells": {"1": {"1": "≥590"}}}, _table()
    )
    assert problems == []
    assert spec == {"header_rows": 1, "patch_cells": {"1": {"1": "≥590"}}}


def test_fabricated_number_is_rejected() -> None:
    spec, problems = validate_table_repair_spec(
        {"patch_cells": {"1": {"1": "999"}}}, _table()
    )
    assert spec is None
    assert any("编造" in problem for problem in problems)


def test_out_of_range_row_is_rejected() -> None:
    spec, problems = validate_table_repair_spec(
        {"replace_rows": {"9": ["X", "Y"]}}, _table()
    )
    assert spec is None
    assert any("越界" in problem for problem in problems)


def test_replace_rows_accepts_indexed_list() -> None:
    spec, problems = validate_table_repair_spec(
        {"replace_rows": [{"row_index": 1, "cells": ["Q355B", "≥590"]}]}, _table()
    )
    assert problems == []
    assert spec == {"replace_rows": {"1": ["Q355B", "≥590"]}}


def test_delete_all_rows_is_rejected() -> None:
    spec, problems = validate_table_repair_spec({"delete_rows": [0, 1, 2]}, _table())
    assert spec is None
    assert any("全部" in problem for problem in problems)


def test_apply_replaces_cells_and_keeps_original() -> None:
    original = _table()
    repaired = apply_table_repair(
        original, {"patch_cells": {"1": {"1": "≥590"}}, "delete_rows": [2]}
    )
    assert repaired["rows"][1][1] == "≥590"
    assert len(repaired["rows"]) == 2
    assert original["rows"][1][1] == "590"
    assert original["rows"][2][0] == "Q355C"


def test_apply_to_ocr_only_touches_target_table() -> None:
    ocr = {"tables": [_table(), {**_table(), "table_id": "T2"}]}
    repaired = apply_table_repair_to_ocr(
        ocr, "T1", {"patch_cells": {"1": {"1": "≥590"}}}
    )
    assert repaired["tables"][0]["rows"][1][1] == "≥590"
    assert repaired["tables"][1]["rows"][1][1] == "590"
    assert repaired["_table_repair"]["table_id"] == "T1"


def test_extract_table_repair_shapes() -> None:
    table_id, spec = extract_table_repair(
        {"table_repair": {"table_id": "T8", "spec": {"header_rows": 1}}}, "T1"
    )
    assert table_id == "T8"
    assert spec == {"header_rows": 1}

    table_id, spec = extract_table_repair(
        {
            "operator": "table_repair.add",
            "params": {"table_id": "T9", "spec": {"delete_rows": [2]}},
        },
        "T1",
    )
    assert table_id == "T9"
    assert spec == {"delete_rows": [2]}

    table_id, spec = extract_table_repair({"spec": {"header_rows": 2}}, "T1")
    assert table_id == "T1"
    assert spec == {"header_rows": 2}

    assert extract_table_repair({}, "T1") == ("T1", None)


def test_gates_accept_when_all_checks_pass() -> None:
    gate = evaluate_gates(
        target_fixed=True,
        new_errors=0,
        removed=False,
        evidence_grounded=True,
        reproduced=True,
        acceptance={"metric": "records", "current": 0, "target": 1},
    )
    assert gate["decision"] == "accept"
    assert gate["passed"] is True
    names = [check["name"] for check in gate["checks"]]
    assert names == [
        "evidence_grounded",
        "reproduction",
        "target_metric",
        "no_new_errors",
        "required_no_loss",
        "no_removed_records",
        "iteration_limit",
        "regression",
    ]


def test_gates_rollback_when_target_not_fixed() -> None:
    gate = evaluate_gates(
        target_fixed=False,
        new_errors=0,
        removed=False,
        evidence_grounded=True,
        reproduced=True,
    )
    assert gate["decision"] == "rollback"


def test_gates_rollback_on_new_errors_or_removed_records() -> None:
    errors = evaluate_gates(
        target_fixed=True,
        new_errors=2,
        removed=False,
        evidence_grounded=True,
        reproduced=True,
    )
    removed = evaluate_gates(
        target_fixed=True,
        new_errors=0,
        removed=True,
        evidence_grounded=True,
        reproduced=True,
    )
    assert errors["decision"] == "rollback"
    assert removed["decision"] == "rollback"


def test_gates_rollback_when_iteration_limit_exceeded() -> None:
    gate = evaluate_gates(
        target_fixed=True,
        new_errors=0,
        removed=False,
        evidence_grounded=True,
        reproduced=True,
        iterations=4,
    )
    assert gate["decision"] == "rollback"


def test_gates_l3_requires_policy_before_accept() -> None:
    blocked = evaluate_gates(
        target_fixed=True,
        new_errors=0,
        removed=False,
        evidence_grounded=True,
        reproduced=True,
        level="L3",
    )
    allowed = evaluate_gates(
        target_fixed=True,
        new_errors=0,
        removed=False,
        evidence_grounded=True,
        reproduced=True,
        level="L3",
        l3_policy_passed=True,
    )
    assert blocked["decision"] == "propose_only"
    assert allowed["decision"] == "accept"


def test_gates_rollback_when_regression_fails() -> None:
    gate = evaluate_gates(
        target_fixed=True,
        new_errors=0,
        removed=False,
        evidence_grounded=True,
        reproduced=True,
        regression=(False, "regression set dropped"),
    )
    assert gate["decision"] == "rollback"
