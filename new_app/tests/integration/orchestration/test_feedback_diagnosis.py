from __future__ import annotations

from services.orchestration.feedback.context import (
    build_repair_context,
    choose_target_table,
)
from services.orchestration.feedback.diagnosis import diagnose
from services.orchestration.feedback.intent import resolve_intent


def _table(
    table_id: str,
    caption: str | None,
    headers: list[str],
    *,
    page_no: int = 1,
    profile: str = "mechanical_properties",
    rows: list[list[str]] | None = None,
) -> dict:
    return {
        "table_id": table_id,
        "page_no": page_no,
        "caption": caption,
        "profile": profile,
        "orientation": "grade_rows",
        "header_paths": [headers],
        "rows": rows or [],
    }


def _diagnose(
    *,
    description: str,
    tables: list[dict],
    records: list[dict] | None = None,
    diagnostics: list[dict] | None = None,
    rule_id: str | None = None,
    table_id: str = "",
    recipe: dict | None = None,
) -> dict:
    records = records or []
    diagnostics = diagnostics or []
    target = {"rule_id": rule_id} if rule_id else {}
    if table_id:
        target["table_id"] = table_id
    feedback = {
        "feedback_id": "fb-1",
        "description": description,
        "target": target,
    }
    intent = resolve_intent(description, tables, records, diagnostics, target=target)
    context = build_repair_context(
        feedback=feedback,
        tables=tables,
        records=records,
        diagnostics=diagnostics,
        recipe=recipe or {},
        intent=intent,
    )
    return diagnose(
        intent=intent,
        repair_context=context,
        tables=tables,
        records=records,
        diagnostics=diagnostics,
    )


def test_missing_project_with_rows_but_no_records_is_table_repair() -> None:
    tables = [
        _table(
            "T6",
            "表6 弯曲性能",
            ["牌号", "厚度mm", "弯曲角(°)"],
            page_no=8,
            rows=[
                ["牌号", "厚度mm", "弯曲角(°)"],
                ["TA1G", "0.4~1.0", "≥140"],
            ],
        )
    ]
    diagnosis = _diagnose(
        description="弯曲项目没有抽取", tables=tables, table_id="T6"
    )
    assert diagnosis["root_cause"] == "table_structure"
    assert diagnosis["action"] == "table_repair"


def test_unbound_columns_with_admissible_is_recipe_binding() -> None:
    tables = [
        _table(
            "T5",
            "表5 化学成分",
            ["牌号", "C", "Si", "Mn"],
            profile="chemical_composition",
            rows=[["Q355B", "0.20", "0.55", "1.50"]],
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
        "bindings": {"row_key": ["元素"], "measures": {}},
    }
    diagnosis = _diagnose(
        description="化学成分没有正确抽取",
        tables=tables,
        diagnostics=diagnostics,
        rule_id="DOC-UNBOUND-COLUMNS",
        table_id="T5",
        recipe=recipe,
    )
    assert diagnosis["root_cause"] == "recipe_binding"
    assert diagnosis["action"] == "rule_fix"
    assert diagnosis["needs_model"] is False
    assert "C" in diagnosis["mechanism"] or "measure" in diagnosis["mechanism"]


def test_unbound_columns_without_admissible_is_table_structure() -> None:
    tables = [_table("T4", "表4 尺寸", ["牌号", "外径", "壁厚"], rows=[["Q355B", "50", "5"]])]
    diagnostics = [
        {
            "code": "MEASURE_COLUMN_MISSING",
            "severity": "warning",
            "detail": {"table_id": "T4", "headers": ["牌号", "外径", "壁厚"]},
        }
    ]
    diagnosis = _diagnose(
        description="化学成分没有正确抽取",
        tables=tables,
        diagnostics=diagnostics,
        rule_id="DOC-UNBOUND-COLUMNS",
        table_id="T4",
        recipe={"recipe_id": "chemical_composition_v1", "bindings": {"measures": {}}},
    )
    assert diagnosis["root_cause"] == "table_structure"
    assert diagnosis["action"] == "table_repair"


def test_no_tables_is_ocr_error() -> None:
    diagnosis = _diagnose(
        description="冲击没有从文档中抽取出来",
        tables=[],
        rule_id="DOC-NO-TABLES",
    )
    assert diagnosis["root_cause"] == "ocr_error"
    assert diagnosis["action"] == "report_only"
    assert diagnosis["needs_model"] is False


def test_table_with_rows_but_no_records_is_table_structure() -> None:
    tables = [
        _table(
            "T8",
            "表8 冲击试验",
            ["牌号", "KV2"],
            page_no=7,
            rows=[["Q355B", "27"], ["Q355C", "27"]],
        )
    ]
    diagnosis = _diagnose(
        description="冲击没有从文档中抽取出来",
        tables=tables,
        rule_id="DOC-NO-RECORDS",
        table_id="T8",
    )
    assert diagnosis["root_cause"] == "table_structure"
    assert diagnosis["action"] == "table_repair"
    assert "2" in diagnosis["first_divergence"]


def test_duplicate_keys_is_extraction_rule() -> None:
    tables = [_table("T2", "表2 力学性能", ["牌号", "Rm"], rows=[["Q355B", "470"]])]
    records = [
        {
            "record_id": "r1",
            "table_id": "T2",
            "grade": "Q355B",
            "properties": {"Rm": {"raw": "470"}},
        },
        {
            "record_id": "r2",
            "table_id": "T2",
            "grade": "Q355B",
            "properties": {"Rm": {"raw": "470"}},
        },
    ]
    diagnosis = _diagnose(
        description="同一牌号重复了",
        tables=tables,
        records=records,
        rule_id="DOC-DUP-KEYS",
        table_id="T2",
    )
    assert diagnosis["root_cause"] == "extraction_rule"
    assert diagnosis["action"] == "rule_fix"
    assert diagnosis["rule_change"]["rule_id"] == "bindings.conditions"


def test_expected_is_derived_from_source_cell_on_mismatch() -> None:
    tables = [
        _table(
            "T12",
            "表12 力学性能",
            ["牌号", "Rm", "Rp0.2"],
            page_no=9,
            rows=[["Q355B", "470", "355"]],
        )
    ]
    records = [
        {
            "record_id": "T12-R1",
            "table_id": "T12",
            "grade": "Q355B",
            "properties": {"Rm": {"raw": "407"}, "Rp0.2": {"raw": "355"}},
        }
    ]
    diagnosis = _diagnose(
        description="室温拉伸数值不对",
        tables=tables,
        records=records,
        table_id="T12",
    )
    assert diagnosis["root_cause"] == "value_parsing"
    assert diagnosis["action"] == "rule_fix"
    assert diagnosis["expected"] == "470"
    assert diagnosis["evidence"][0]["quote"] == "470"
    assert "407" in diagnosis["first_divergence"]


def test_unresolved_value_complaint_marks_needs_model() -> None:
    tables = [_table("T12", "表12 力学性能", ["牌号", "Rm"], page_no=9, rows=[])]
    records = [
        {
            "record_id": "T12-R1",
            "table_id": "T12",
            "grade": "Q355B",
            "properties": {"Rm": {"raw": "470"}},
        }
    ]
    diagnosis = _diagnose(
        description="室温拉伸数值不对",
        tables=tables,
        records=records,
        table_id="T12",
    )
    assert diagnosis["root_cause"] == "value_parsing"
    assert diagnosis["expected"] is None
    assert diagnosis["needs_model"] is True


def test_unit_missing_is_recipe_binding() -> None:
    tables = [_table("T2", "表2 力学性能", ["牌号", "Rm"], rows=[["Q355B", "470"]])]
    diagnosis = _diagnose(
        description="单位缺失",
        tables=tables,
        rule_id="DOC-UNIT-MISSING",
        table_id="T2",
    )
    assert diagnosis["root_cause"] == "recipe_binding"
    assert diagnosis["action"] == "rule_fix"
    assert diagnosis["rule_change"]["rule_id"] == "bindings.measures.unit"


def test_low_coverage_targets_uncovered_table() -> None:
    """Document-level findings must resolve to the table that produced nothing."""
    tables = [
        _table("T1", "表1 化学成分", ["牌号", "C"], rows=[["Q355B", "0.20"]]),
        _table(
            "T8",
            "表8 冲击试验",
            ["牌号", "KV2"],
            page_no=7,
            rows=[["Q355B", "27"], ["Q355C", "27"], ["Q355D", "27"]],
        ),
    ]
    for table in tables:
        table["records"] = 1 if table["table_id"] == "T1" else 0
    tables[0]["recipe_id"] = "chemical_composition_v1"
    tables[1]["recipe_id"] = "mechanical_properties_v1"
    feedback = {
        "feedback_id": "fb-low",
        "description": "most detected tables produced no records",
        "target": {
            "level": "document",
            "rule_id": "DOC-LOW-COVERAGE",
            "table_ids": ["T1", "T8"],
        },
    }
    chosen = choose_target_table(
        feedback=feedback, tables=tables, diagnostics=[], records=[]
    )
    assert chosen["table_id"] == "T8"
    assert chosen["recipe_id"] == "mechanical_properties_v1"

    intent = resolve_intent(
        feedback["description"], tables, [], [], target=feedback["target"]
    )
    context = build_repair_context(
        feedback=feedback,
        tables=tables,
        records=[],
        diagnostics=[],
        recipe={"recipe_id": "mechanical_properties_v1", "bindings": {"measures": {}}},
        intent=intent,
    )
    assert context["problem"]["target"]["table_id"] == "T8"
    diagnosis = diagnose(
        intent=intent,
        repair_context=context,
        tables=tables,
        records=[],
        diagnostics=[],
    )
    assert diagnosis["root_cause"] == "table_structure"
    assert diagnosis["action"] == "table_repair"


def test_no_records_without_table_id_picks_table_with_rows() -> None:
    tables = [
        _table("T3", "表3 尺寸", ["牌号", "外径"], rows=[]),
        _table("T9", "表9 拉伸", ["牌号", "Rm"], page_no=4, rows=[["Q355B", "470"]]),
    ]
    tables[0]["records"] = 0
    tables[1]["records"] = 0
    feedback = {
        "feedback_id": "fb-no-records",
        "description": "document contains tables but no records were extracted",
        "target": {"level": "document", "rule_id": "DOC-NO-RECORDS"},
    }
    chosen = choose_target_table(
        feedback=feedback, tables=tables, diagnostics=[], records=[]
    )
    assert chosen["table_id"] == "T9"
