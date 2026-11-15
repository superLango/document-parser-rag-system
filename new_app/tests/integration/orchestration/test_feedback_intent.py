from __future__ import annotations

from services.orchestration.feedback.concepts import load_dictionary
from services.orchestration.feedback.context import build_repair_context, merge_tables
from services.orchestration.feedback.intent import resolve_intent
from services.orchestration.feedback.outline import build_outline


def test_merge_tables_keeps_ocr_row_arrays() -> None:
    ocr = [
        {
            "table_id": "T1",
            "page_no": 3,
            "rows": [["牌号", "Rm"], ["Q355B", "470"]],
            "header_paths": [["牌号", "Rm"]],
        }
    ]
    summaries = [
        {"table_id": "T1", "rows": 2, "records": 1, "profile": "mechanical_properties"}
    ]
    merged = merge_tables(summaries, ocr)
    assert isinstance(merged[0]["rows"], list)
    assert merged[0]["rows"][1][1] == "470"
    assert merged[0]["records"] == 1
    assert merged[0]["header_paths"] == [["牌号", "Rm"]]


def _table(
    table_id: str,
    caption: str | None,
    headers: list[str],
    *,
    page_no: int = 1,
    profile: str = "mechanical_properties",
    records: int = 0,
    header_paths: list[list[str]] | None = None,
) -> dict:
    return {
        "table_id": table_id,
        "page_no": page_no,
        "caption": caption,
        "profile": profile,
        "orientation": "grade_rows",
        "header_paths": header_paths if header_paths is not None else [headers],
        "records": records,
    }


def test_dictionary_is_versioned_and_covers_core_concepts() -> None:
    dictionary = load_dictionary()
    assert dictionary.version == "1.0.1"
    for concept_id in (
        "mechanical.room_tensile",
        "mechanical.impact",
        "mechanical.hardness",
        "mechanical.bend",
        "chemical.composition",
        "dimension.size",
        "clause.test_method",
    ):
        assert dictionary.by_id(concept_id) is not None


def test_outline_falls_back_to_diagnostic_headers() -> None:
    table = {
        "table_id": "T5",
        "page_no": 8,
        "caption": None,
        "profile": "chemical_composition",
    }
    diagnostics = [
        {
            "code": "MEASURE_COLUMN_MISSING",
            "severity": "warning",
            "detail": {"table_id": "T5", "headers": ["牌号", "C", "Si", "Mn"]},
        }
    ]
    outline = build_outline([table], [], diagnostics)
    assert outline[0]["headers"] == ["牌号", "C", "Si", "Mn"]
    assert outline[0]["measures"] == ["C", "Mn", "Si"]
    assert outline[0]["section_kind"] == "chemical"
    assert outline[0]["diagnostics"] == ["MEASURE_COLUMN_MISSING"]


def test_room_temperature_tensile_matches_mechanical_properties_table() -> None:
    tables = [
        _table(
            "T12",
            "表12 力学性能",
            ["牌号", "抗拉强度", "屈服强度", "断后伸长率"],
            page_no=9,
            records=18,
        )
    ]
    intent = resolve_intent("室温拉伸抽取效果不好", tables)
    assert intent["scope"] == "table"
    assert intent["candidate_targets"][0]["table_id"] == "T12"
    assert "列语义命中" in intent["candidate_targets"][0]["reason"]
    assert "Rm" in intent["candidate_targets"][0]["measures_matched"]
    assert intent["confidence"] >= 0.7


def test_high_temperature_table_is_penalised() -> None:
    tables = [
        _table("T1", "表12 室温力学性能", ["牌号", "抗拉强度", "屈服强度"], page_no=9, records=12),
        _table("T2", "表13 高温力学性能", ["牌号", "抗拉强度", "屈服强度"], page_no=11, records=12),
    ]
    intent = resolve_intent("室温拉伸抽取效果不好", tables)
    assert intent["candidate_targets"][0]["table_id"] == "T1"
    reasons = {item["table_id"]: item["reason"] for item in intent["candidate_targets"]}
    assert "条件冲突" in reasons["T2"]


def test_clause_feedback_does_not_target_chemical_tables() -> None:
    tables = [
        _table(
            "T5",
            "表5 化学成分",
            ["牌号", "C", "Si", "Mn"],
            profile="chemical_composition",
            records=20,
        )
    ]
    intent = resolve_intent("化学成分试验方法没有正确抽取", tables)
    assert intent["scope"] == "clause"
    assert intent["concept_id"] == "clause.test_method"
    assert intent["candidate_targets"] == []


def test_impact_missing_targets_impact_table() -> None:
    tables = [
        _table("T8", "表8 冲击试验", ["牌号", "KV2", "KU2"], page_no=7, records=0),
        _table("T9", "表9 硬度", ["牌号", "HBW", "HRC"], page_no=8, records=4, profile="hardness"),
    ]
    intent = resolve_intent("冲击没有从文档中抽取出来", tables)
    assert intent["category"] == "missing_value"
    assert intent["scope"] == "table"
    assert intent["candidate_targets"][0]["table_id"] == "T8"


def test_hardness_matches_hardness_profile() -> None:
    tables = [
        _table("T9", "表9 硬度", ["牌号", "HBW", "HRC"], profile="hardness", records=3)
    ]
    intent = resolve_intent("硬度不对", tables)
    assert intent["scope"] == "table"
    assert intent["candidate_targets"][0]["table_id"] == "T9"


def test_english_tensile_properties_match_by_measure_semantics() -> None:
    tables = [
        _table(
            "T3",
            "Tensile Properties at Room Temperature",
            ["Grade", "Tensile strength", "Yield strength", "Elongation"],
            page_no=6,
            records=10,
        )
    ]
    intent = resolve_intent("tensile properties extraction is wrong", tables)
    assert intent["candidate_targets"][0]["table_id"] == "T3"
    assert "列语义命中" in intent["candidate_targets"][0]["reason"]


def test_unknown_utterance_falls_back_to_document_scope() -> None:
    tables = [_table("T1", "表1 力学性能", ["牌号", "Rm"], records=2)]
    intent = resolve_intent("整体感觉不行", tables)
    assert intent["scope"] == "document"
    assert intent["concept_id"] == ""
    assert intent["candidate_targets"] == []
    assert intent["confidence"] <= 0.3


def test_room_tensile_requirement_complaint_targets_requirement_field() -> None:
    tables = [
        _table(
            "T12",
            "表12 室温拉伸性能",
            ["牌号", "抗拉强度(Rm)", "规定塑性延伸强度(Rp0.2)"],
            page_no=9,
            records=18,
        )
    ]
    intent = resolve_intent("室温拉伸标准要求抽取不正确", tables)
    assert intent["subject"] == "室温拉伸"
    assert intent["field"] == "标准要求"
    assert intent["category"] == "wrong_requirement"
    assert intent["candidate_targets"][0]["table_id"] == "T12"


def test_chemical_method_complaint_is_document_level() -> None:
    tables = [
        _table(
            "T2",
            "表2 化学成分",
            ["牌号", "Ti", "Pd", "Fe", "C"],
            profile="chemical_composition",
            records=3,
        )
    ]
    intent = resolve_intent("化学成分试验方法没有抽取出来", tables)
    assert intent["subject"] == "化学成分"
    assert intent["field"] == "试验方法"
    assert intent["method_field"] is True
    assert intent["scope"] == "clause"
    assert intent["candidate_targets"] == []


def test_bend_missing_complaint_targets_bend_table() -> None:
    tables = [
        _table(
            "T6",
            "表6 弯曲性能",
            ["牌号", "厚度mm", "弯曲压头直径mm", "弯曲角(°)"],
            page_no=8,
            records=0,
        ),
        _table(
            "T9",
            "表9 硬度",
            ["牌号", "HBW", "HRC"],
            page_no=10,
            profile="hardness",
            records=4,
        ),
    ]
    intent = resolve_intent("弯曲项目没有抽取", tables)
    assert intent["subject"] == "弯曲"
    assert intent["field"] == "项目名称"
    assert intent["missing_project"] is True
    assert intent["scope"] == "table"
    assert intent["candidate_targets"][0]["table_id"] == "T6"


def test_equally_scored_tables_ask_one_clarifying_question() -> None:
    tables = [
        _table("T1", "表1 力学性能", ["牌号", "抗拉强度"], page_no=5, records=6),
        _table("T2", "表2 力学性能", ["牌号", "抗拉强度"], page_no=6, records=6),
    ]
    intent = resolve_intent("室温拉伸抽取效果不好", tables)
    assert intent["clarifying_question"] is not None
    assert "T1" in intent["clarifying_question"]
    assert "T2" in intent["clarifying_question"]


def test_repair_context_targets_unbound_columns() -> None:
    tables = [
        _table(
            "T5",
            "表5 化学成分",
            ["牌号", "C", "Si", "Mn"],
            page_no=8,
            profile="chemical_composition",
        )
    ]
    diagnostics = [
        {
            "code": "MEASURE_COLUMN_MISSING",
            "severity": "warning",
            "detail": {"table_id": "T5", "headers": ["牌号", "C", "Si", "Mn"]},
        }
    ]
    recipe = {
        "recipe_id": "chemical_element_rows_v1",
        "version": "1.2.3",
        "profile": "chemical_composition",
        "bindings": {"row_key": ["元素"], "conditions": ["牌号"], "measures": {}},
    }
    feedback = {
        "feedback_id": "fb-1",
        "run_id": "run-1",
        "description": "化学成分没有正确抽取",
        "target": {"rule_id": "DOC-UNBOUND-COLUMNS", "table_id": "T5"},
    }
    intent = resolve_intent(
        feedback["description"], tables, diagnostics=diagnostics
    )
    context = build_repair_context(
        feedback=feedback,
        tables=tables,
        records=[],
        diagnostics=diagnostics,
        recipe=recipe,
        intent=intent,
    )
    assert context["problem"]["target"]["table_id"] == "T5"
    assert context["task"]["acceptance"] == {
        "metric": "required_items",
        "current": 0,
        "target": 1,
    }
    assert context["recipe"]["unbound_columns"] == ["C", "Mn", "Si"]
    assert context["constraints"]["admissible"]["columns"] == ["C", "Mn", "Si"]
    assert context["constraints"]["allowed_operators"] == [
        "recipe.binding_override",
        "column_alias.add",
        "table_repair.add",
    ]
    assert len(context["context_hash"]) == 16
    again = build_repair_context(
        feedback=feedback,
        tables=tables,
        records=[],
        diagnostics=diagnostics,
        recipe=recipe,
        intent=intent,
    )
    assert again["context_hash"] == context["context_hash"]


def test_repair_context_uses_intent_candidate_when_target_missing() -> None:
    tables = [
        _table(
            "T12",
            "表12 力学性能",
            ["牌号", "抗拉强度", "屈服强度"],
            page_no=9,
            records=5,
        )
    ]
    feedback = {
        "feedback_id": "fb-2",
        "description": "室温拉伸抽取效果不好",
        "target": {"rule_id": "DOC-LOW-COVERAGE"},
    }
    intent = resolve_intent(feedback["description"], tables)
    records = [
        {
            "record_id": f"T12-R{index}",
            "table_id": "T12",
            "grade": "Q355B",
            "properties": {"Rm": {"raw": "470"}},
        }
        for index in range(1, 6)
    ]
    context = build_repair_context(
        feedback=feedback,
        tables=tables,
        records=records,
        diagnostics=[],
        recipe={"recipe_id": "mechanical_properties_v1", "version": "1.6.1"},
        intent=intent,
    )
    assert context["problem"]["target"]["table_id"] == "T12"
    assert context["task"]["acceptance"]["metric"] == "complete_items"
    assert context["task"]["acceptance"]["target"] == 6


def test_repair_context_no_tables_routes_to_engine() -> None:
    feedback = {"description": "整篇没有表", "target": {"rule_id": "DOC-NO-TABLES"}}
    context = build_repair_context(
        feedback=feedback,
        tables=[],
        records=[],
        diagnostics=[],
        recipe={},
    )
    assert context["constraints"]["allowed_levels"] == ["engine"]
    assert context["constraints"]["allowed_operators"] == []
    assert context["task"]["acceptance"]["metric"] == "tables"
