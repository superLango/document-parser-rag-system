from __future__ import annotations

from services.orchestration.feedback.patching import sanitize_patch, validate_operator
from services.orchestration.feedback.repairability import evaluate_repairability


def _context(
    root_cause: str,
    *,
    action: str = "rule_fix",
    expected: str | None = None,
    admissible: list[str] | None = None,
    allowed_operators: list[str] | None = None,
    allowed_levels: list[str] | None = None,
    field: str = "",
) -> dict:
    return {
        "intent": {"field": field},
        "diagnosis": {
            "root_cause": root_cause,
            "action": action,
            "expected": expected,
        },
        "repair_context": {
            "constraints": {
                "admissible": {"columns": admissible or [], "measures": admissible or []},
                "allowed_operators": allowed_operators or [],
                "allowed_levels": allowed_levels or ["L1", "L2"],
            }
        },
    }


def test_engine_scope_is_not_repairable() -> None:
    result = evaluate_repairability(_context("ocr_error", action="report_only"))
    assert result["decision"] == "engine"
    assert result["allowed_operators"] == []


def test_table_structure_routes_to_l1() -> None:
    result = evaluate_repairability(_context("table_structure", action="table_repair"))
    assert result["decision"] == "data"
    assert result["allowed_levels"] == ["L1"]


def test_recipe_binding_with_admissible_columns() -> None:
    result = evaluate_repairability(
        _context(
            "recipe_binding",
            admissible=["C", "Si"],
            allowed_operators=["recipe.binding_override"],
        )
    )
    assert result["decision"] == "recipe_binding"
    assert result["allowed_operators"] == ["recipe.binding_override"]


def test_recipe_binding_without_evidence_needs_human() -> None:
    result = evaluate_repairability(_context("recipe_binding"))
    assert result["decision"] == "needs_more_info"


def test_value_parsing_without_expected_needs_human() -> None:
    result = evaluate_repairability(_context("value_parsing", action="rule_fix"))
    assert result["decision"] == "needs_more_info"


def test_unknown_root_cause_needs_human() -> None:
    result = evaluate_repairability(_context("unknown", action="report_only"))
    assert result["decision"] == "needs_more_info"


def test_method_field_routes_to_document_rule() -> None:
    result = evaluate_repairability(_context("extraction_rule", field="试验方法"))
    assert result["decision"] == "document_rule"
    assert result["allowed_levels"] == ["engine"]
    assert result["allowed_operators"] == []


def test_binding_and_rule_ops_are_effective() -> None:
    result = sanitize_patch(
        {
            "ops": [
                {"op": "add", "path": "/bindings/measures/C", "value": {"unit": "%"}},
                {"op": "replace", "path": "/rules/transposed", "value": True},
                {"op": "add", "path": "/bindings/conditions", "value": "状态"},
            ]
        }
    )
    assert result["effective"] is True
    assert len(result["effective_ops"]) == 3
    assert result["advisory_ops"] == []
    assert result["rejected_ops"] == []


def test_add_to_conditions_appends() -> None:
    result = sanitize_patch(
        {"ops": [{"op": "add", "path": "/bindings/conditions", "value": "Batch"}]}
    )
    assert result["effective"] is True
    assert result["effective_ops"][0]["path"] == "/bindings/conditions/-"


def test_signature_and_template_ops_are_advisory_only() -> None:
    result = sanitize_patch(
        {
            "ops": [
                {"op": "add", "path": "/signature/tokens/-", "value": "抗拉强度"},
                {"op": "replace", "path": "/templates/template_id", "value": "product_full"},
                {"op": "add", "path": "/compatibility/coverage_template", "value": "x"},
            ]
        }
    )
    assert result["effective"] is False
    assert len(result["advisory_ops"]) == 3
    assert result["rejected_ops"] == []


def test_unknown_root_is_rejected() -> None:
    result = sanitize_patch(
        {"ops": [{"op": "add", "path": "/engine/dockerfile", "value": "x"}]}
    )
    assert result["effective"] is False
    assert len(result["rejected_ops"]) == 1
    assert "不允许的路径根" in result["rejected_ops"][0]["reason"]


def test_unsupported_op_and_missing_value_are_rejected() -> None:
    result = sanitize_patch(
        {
            "ops": [
                {"op": "move", "path": "/bindings/measures/C"},
                {"op": "add", "path": "/bindings/measures/Si"},
            ]
        }
    )
    assert result["effective"] is False
    assert len(result["rejected_ops"]) == 2


def test_operator_patch_is_not_effective_without_conversion() -> None:
    result = sanitize_patch(
        {
            "operator": "recipe.binding_override",
            "params": {"recipe_id": "r", "bindings": {"Rm": {"unit": "MPa"}}},
        }
    )
    assert result["effective"] is False
    assert "尚未实现" in result["problems"][0]


def test_operator_missing_params_is_reported() -> None:
    problems = validate_operator("column_alias.add", {"alias": "Rm"})
    assert problems == ["缺少参数 property"]


def test_advisory_operator_does_not_become_effective() -> None:
    result = sanitize_patch(
        {"operator": "unit_normalize.add", "params": {"pattern": "ksi", "unit": "MPa"}}
    )
    assert result["effective"] is False
    assert len(result["advisory_ops"]) == 1


def test_empty_patch_reports_problem() -> None:
    result = sanitize_patch({})
    assert result["effective"] is False
    assert result["problems"] == ["patch.ops 缺失或不是数组"]


def test_measure_add_outside_admissible_is_rejected() -> None:
    result = sanitize_patch(
        {
            "ops": [
                {
                    "op": "add",
                    "path": "/bindings/measures/Ag",
                    "value": {"unit": "%"},
                }
            ]
        },
        admissible={"columns": ["C"], "measures": ["C"]},
    )
    assert result["effective"] is False
    assert "不在可采纳集合内" in result["rejected_ops"][0]["reason"]


def test_measure_add_inside_admissible_is_effective() -> None:
    result = sanitize_patch(
        {
            "ops": [
                {
                    "op": "add",
                    "path": "/bindings/measures/Ag",
                    "value": {"unit": "%"},
                }
            ]
        },
        admissible={"columns": ["Ag"], "measures": ["Ag"]},
    )
    assert result["effective"] is True
    assert len(result["effective_ops"]) == 1


def test_measure_remove_is_rejected_by_default() -> None:
    result = sanitize_patch(
        {"ops": [{"op": "remove", "path": "/bindings/measures/Ag"}]},
        admissible={"columns": [], "measures": []},
    )
    assert result["effective"] is False
    assert "默认禁止删除或替换 measure 绑定" in result["rejected_ops"][0]["reason"]


def test_measure_remove_is_allowed_with_explicit_approval() -> None:
    result = sanitize_patch(
        {"ops": [{"op": "remove", "path": "/bindings/measures/Ag"}]},
        admissible={"columns": [], "measures": []},
        allow_measure_removal=True,
    )
    assert result["effective"] is True


def test_measure_root_replace_is_rejected_by_default() -> None:
    result = sanitize_patch(
        {"ops": [{"op": "replace", "path": "/bindings/measures", "value": {}}]}
    )
    assert result["effective"] is False
    assert "默认禁止删除或替换 measure 绑定" in result["rejected_ops"][0]["reason"]


def test_max_ops_truncates_extra_ops() -> None:
    ops = [
        {
            "op": "add",
            "path": f"/bindings/measures/M{index}",
            "value": {"unit": "%"},
        }
        for index in range(7)
    ]
    result = sanitize_patch(
        {"ops": ops},
        admissible={
            "columns": [f"M{index}" for index in range(7)],
            "measures": [],
        },
        max_ops=5,
    )
    assert len(result["effective_ops"]) == 5
    assert len(result["rejected_ops"]) == 2
    assert all("max_ops" in item["reason"] for item in result["rejected_ops"])
