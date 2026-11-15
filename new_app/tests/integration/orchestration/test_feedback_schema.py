from __future__ import annotations

from hanson_contracts import RepairProposal, VerificationPackage

from services.orchestration.feedback.context import build_repair_context
from services.orchestration.feedback.coverage import compute_coverage, summarize_coverage
from services.orchestration.feedback.diagnosis import diagnose
from services.orchestration.feedback.gates import evaluate_gates
from services.orchestration.feedback.intent import resolve_intent
from services.orchestration.feedback.repairability import evaluate_repairability
from services.orchestration.feedback.schema_contract import REQUIRED_FIELDS
from services.orchestration.feedback.service import (
    FeedbackService,
    _coverage_delta,
    _diagnostic_summary,
    _tool_tables,
)


def _record(grade: str, properties: dict, **extra) -> dict:
    return {
        "record_id": f"R-{grade}-{len(properties)}",
        "table_id": "T1",
        "grade": grade,
        "condition_key": "",
        "properties": properties,
        **extra,
    }


def test_required_fields_follow_fixed_schema() -> None:
    assert REQUIRED_FIELDS["items"] == ("项目名称", "材料牌号", "标准要求")
    heat = REQUIRED_FIELDS["heat_treatment"]
    assert "项目大类" in heat
    assert "材料牌号" in heat and "工序名称" in heat
    assert "保温温度" not in heat and "保温时间" not in heat


def test_coverage_counts_complete_items() -> None:
    coverage = compute_coverage(
        [
            _record(
                "Q355B",
                {
                    "Rm": {"raw": "470", "value": 470.0, "unit": "MPa"},
                    "Rp0.2": {"raw": "355", "value": 355.0, "unit": "MPa"},
                },
            )
        ]
    )
    assert coverage["items_total"] == 2
    assert coverage["complete_rows"] == 2
    assert coverage["required_total"] == 6
    assert coverage["required_present"] == 6
    assert coverage["required_rate"] == 1.0
    assert coverage["missing"] == []


def test_placeholder_grade_is_row_skipped() -> None:
    coverage = compute_coverage([_record("~", {"Rm": {"raw": "470", "value": 470.0}})])
    assert coverage["complete_rows"] == 0
    assert coverage["required_present"] == 2
    assert coverage["missing"][0]["field"] == "材料牌号"
    assert coverage["missing"][0]["cause"] == "row_skipped"


def test_unparsed_requirement_is_reported() -> None:
    coverage = compute_coverage(
        [_record("Q355B", {"Rm": {"raw": "", "value": None, "unit": "MPa"}})]
    )
    assert coverage["complete_rows"] == 0
    assert any(
        item["field"] == "标准要求" and item["cause"] == "value_unparsed"
        for item in coverage["missing"]
    )


def test_conditional_fields_only_expected_when_source_has_them() -> None:
    record = _record("Q355B", {"Rm": {"raw": "470", "value": 470.0, "unit": "MPa"}})
    with_source = compute_coverage([record], text="表1 力学性能 试验方法")
    assert with_source["conditional_expected"] >= 1
    assert any(
        item["field"] == "试验方法" for item in with_source["conditional_missing"]
    )

    without_source = compute_coverage([record], text="表1 力学性能")
    # 数值型会给"单位"增加一条条件期望；源文没有试验方法时不得报缺。
    assert without_source["conditional_missing"] == []


def test_heat_treatment_requires_project_category() -> None:
    coverage = compute_coverage(
        [],
        heat_treatments=[
            {"材料牌号": "GH4169", "工序名称": "时效", "保温温度": "720"}
        ],
    )
    assert coverage["heat_treatment_total"] == 3
    assert coverage["heat_treatment_present"] == 2
    assert coverage["missing"][0]["field"] == "项目大类"


def test_acceptance_uses_complete_items_metric() -> None:
    tables = [
        {
            "table_id": "T1",
            "page_no": 3,
            "caption": "表1 力学性能",
            "profile": "mechanical_properties",
            "header_paths": [["牌号", "Rm"]],
            "rows": [["牌号", "Rm"], ["Q355B", "470"]],
        }
    ]
    feedback = {
        "description": "室温拉伸抽取效果不好",
        "target": {"rule_id": "DOC-NO-RECORDS", "table_id": "T1"},
    }
    intent = resolve_intent(feedback["description"], tables)
    context = build_repair_context(
        feedback=feedback,
        tables=tables,
        records=[
            _record("Q355B", {"Rm": {"raw": "470", "value": 470.0, "unit": "MPa"}})
        ],
        diagnostics=[],
        recipe={"recipe_id": "mechanical_properties_v1", "version": "1.6.1"},
        intent=intent,
    )
    acceptance = context["task"]["acceptance"]
    assert acceptance["metric"] == "complete_items"
    assert acceptance["current"] == 1
    assert acceptance["target"] == 2
    assert context["coverage"]["required_rate"] == 1.0
    assert context["schema"]["required"]["items"] == ["项目名称", "材料牌号", "标准要求"]


def test_required_no_loss_gate_blocks_regression() -> None:
    gate = evaluate_gates(
        target_fixed=True,
        new_errors=0,
        removed=False,
        evidence_grounded=True,
        reproduced=True,
        required_no_loss=False,
    )
    assert gate["decision"] == "rollback"
    failed = [check["name"] for check in gate["checks"] if not check["passed"]]
    assert failed == ["required_no_loss"]


def test_summarize_coverage_is_bounded() -> None:
    coverage = compute_coverage(
        [
            _record("~", {"Rm": {"raw": "", "value": None}}),
            _record("", {"Rp0.2": {"raw": "", "value": None}}),
        ]
    )
    summary = summarize_coverage(coverage)
    assert summary["complete_rows"] == 0
    assert len(summary["missing"]) <= 10
    assert {"complete_rows", "required_present", "required_rate"} <= set(summary)


def test_diagnostic_summary_collects_row_indexes() -> None:
    diagnostics = [
        {"code": "ROW_SKIPPED", "detail": {"row_index": 3}},
        {"code": "ROW_SKIPPED", "detail": {"row_index": 4}},
        {"code": "EMPTY_RECORD_SKIPPED", "detail": {"row_index": 7}},
        {"code": "ROW_KEY_NOT_FOUND", "detail": {"row_index": True}},
        {"code": "MEASURE_COLUMN_MISSING", "detail": {"headers": ["Rm"]}},
        "not-a-dict",
    ]
    summary = _diagnostic_summary(diagnostics)
    assert summary["counts"] == {
        "ROW_SKIPPED": 2,
        "EMPTY_RECORD_SKIPPED": 1,
        "ROW_KEY_NOT_FOUND": 1,
        "MEASURE_COLUMN_MISSING": 1,
    }
    assert summary["rows"]["ROW_SKIPPED"] == [3, 4]
    assert summary["rows"]["EMPTY_RECORD_SKIPPED"] == [7]
    assert "ROW_KEY_NOT_FOUND" not in summary["rows"]


def test_diagnostic_summary_caps_row_samples() -> None:
    diagnostics = [
        {"code": "ROW_SKIPPED", "detail": {"row_index": index}}
        for index in range(60)
    ]
    summary = _diagnostic_summary(diagnostics)
    assert summary["counts"]["ROW_SKIPPED"] == 60
    assert len(summary["rows"]["ROW_SKIPPED"]) == 30


def test_coverage_delta_reports_resolved_and_missing() -> None:
    before = summarize_coverage(
        compute_coverage([_record("~", {"Rm": {"raw": "470", "value": 470.0}})])
    )
    after = summarize_coverage(
        compute_coverage([_record("Q355B", {"Rm": {"raw": "470", "value": 470.0}})])
    )
    delta = _coverage_delta(before, after)
    assert delta["complete_rows"] == 1
    assert delta["required_present"] == 1
    assert delta["resolved"] == ["材料牌号"]
    assert delta["still_missing"] == []


def test_remember_attempt_carries_coverage_and_diagnostics() -> None:
    context = {
        "repair_context": {
            "task": {"rule_id": "DOC-NO-RECORDS"},
            "history": {},
        }
    }
    proposal = RepairProposal(
        summary="repair header",
        patch={"table_repair": {"table_id": "T1", "spec": {"header_rows": 1}}},
    )
    verification = VerificationPackage(
        proposal_id="F1",
        before_run="run-1",
        coverage_before={
            "complete_rows": 0,
            "required_present": 2,
            "required_total": 3,
            "required_rate": 0.6667,
            "missing": [{"field": "材料牌号", "cause": "row_skipped"}],
        },
        coverage_after={
            "complete_rows": 1,
            "required_present": 3,
            "required_total": 3,
            "required_rate": 1.0,
            "missing": [],
        },
        after_diagnostics={"counts": {"ROW_SKIPPED": 1}, "rows": {"ROW_SKIPPED": [2]}},
        checks=[{"name": "target_metric", "passed": True}],
        decision="accept",
    )
    FeedbackService()._remember_attempt(
        context,
        1,
        proposal,
        verification.checks,
        "L1 table T1: fixed",
        verification=verification,
    )
    attempts = context["repair_context"]["history"]["previous_attempts"]
    assert len(attempts) == 1
    entry = attempts[0]
    assert entry["decision"] == "accept"
    assert entry["coverage"]["delta"]["complete_rows"] == 1
    assert "材料牌号" in entry["coverage"]["delta"]["resolved"]
    assert entry["after_diagnostics"]["rows"]["ROW_SKIPPED"] == [2]
    assert entry["patch"] == proposal.patch


def test_tool_tables_only_ship_target_rows() -> None:
    tables = [
        {"table_id": "T1", "caption": "目标表", "rows": [["a"], ["b"]]},
        {"table_id": "T2", "caption": "其它表", "rows": [["c"], ["d"], ["e"]]},
    ]
    payload = _tool_tables(tables, "T1")
    assert payload[0]["rows"] == [["a"], ["b"]]
    assert payload[0]["truncated"] is False
    assert "rows" not in payload[1]
    assert payload[1]["n_rows"] == 3


def test_repair_context_keeps_only_header_merges() -> None:
    merges = [{"row": 0, "col": index, "text": f"h{index}"} for index in range(60)]
    merges.append({"row": 5, "col": 0, "text": "body"})
    tables = [{"table_id": "T1", "caption": "表1", "rows": [], "merges": merges}]
    context = build_repair_context(
        feedback={"target": {"table_id": "T1", "rule_id": "DOC-NO-RECORDS"}},
        tables=tables,
        records=[],
        diagnostics=[],
        recipe={},
    )
    evidence = context["evidence"]["table"]
    assert evidence["merge_count"] == 61
    assert len(evidence["merges"]) == 40
    assert all(item["row"] == 0 for item in evidence["merges"])


def test_missing_measure_diagnostics_route_to_recipe_binding() -> None:
    tables = [
        {
            "table_id": "T5",
            "caption": "表5 化学成分",
            "profile": "chemical_composition",
            "headers": [],
            "rows": [["Q355B", "0.12"]],
        }
    ]
    diagnostics = [
        {
            "code": "MEASURE_COLUMN_MISSING",
            "severity": "warning",
            "detail": {"table_id": "T5", "measure": "Ag"},
            "message": "measure Ag not found in table T5",
        },
        {
            "code": "MEASURE_COLUMN_MISSING",
            "severity": "warning",
            "detail": {"table_id": "T5", "measure": "As"},
            "message": "measure As not found in table T5",
        },
    ]
    feedback = {"target": {"rule_id": "DOC-UNBOUND-COLUMNS", "table_id": "T5"}}
    intent = resolve_intent("化学成分试验方法没有正确抽取", tables)
    context = build_repair_context(
        feedback=feedback,
        tables=tables,
        records=[],
        diagnostics=diagnostics,
        recipe={
            "recipe_id": "chemical_composition_v1",
            "version": "1.1.12",
            "bindings": {"measures": {"C": {"unit": "%"}}},
        },
        intent=intent,
    )
    assert context["recipe"]["unbound_columns"] == ["Ag", "As"]
    assert context["task"]["acceptance"]["metric"] == "required_items"
    diagnosis = diagnose(
        intent=intent,
        repair_context=context,
        tables=tables,
        records=[],
        diagnostics=diagnostics,
    )
    assert diagnosis["root_cause"] == "recipe_binding"
    decision = evaluate_repairability(
        {"diagnosis": diagnosis, "repair_context": context}
    )
    assert decision["decision"] == "recipe_binding"


def test_max_ops_is_rule_specific() -> None:
    def context_for(rule_id: str) -> dict:
        return build_repair_context(
            feedback={"target": {"rule_id": rule_id, "table_id": "T1"}},
            tables=[{"table_id": "T1", "caption": "表1", "rows": [["Q355B"]]}],
            records=[],
            diagnostics=[],
            recipe={"recipe_id": "r", "version": "1.0"},
        )

    assert context_for("DOC-DUP-KEYS")["constraints"]["max_ops"] == 20
    assert context_for("DOC-NO-RECORDS")["constraints"]["max_ops"] == 5
