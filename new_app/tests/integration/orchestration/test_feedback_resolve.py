from __future__ import annotations

from services.orchestration.feedback.context import build_repair_context
from services.orchestration.feedback.diagnosis import diagnose
from services.orchestration.feedback.intent import resolve_intent
from services.orchestration.feedback.resolve import (
    normalize_text,
    resolve_clause,
    resolve_document_meta,
    resolve_expected,
)

PAGES = [
    {
        "page_no": 1,
        "markdown": (
            "中华人民共和国国家标准\nGB/T 1591-2018\n低合金高强度结构钢\n"
            "2018-05-14 发布"
        ),
    },
    {
        "page_no": 8,
        "markdown": (
            "6 试验方法\n"
            "6.1 室温拉伸试验按 GB/T 228.1 执行，抗拉强度 Rm 应不小于 470 MPa。\n"
            "| 牌号 | Rm |\n| Q355B | 470 |"
        ),
    },
]


def test_normalize_text_repairs_utf8_as_latin1() -> None:
    original = "GB/T 1591-2018 低合金高强度结构钢"
    broken = original.encode("utf-8").decode("latin-1")
    assert normalize_text(broken) == original


def test_resolve_document_meta_reads_cover() -> None:
    meta = resolve_document_meta(PAGES, description="标准号抽取不对")
    assert meta is not None
    assert meta["standard_no"] == "GB/T 1591-2018"
    assert meta["standard_name"] == "低合金高强度结构钢"
    assert meta["page_no"] == 1


def test_resolve_document_meta_requires_meta_intent() -> None:
    assert resolve_document_meta(PAGES, description="室温拉伸抽取效果不好") is None


def test_resolve_clause_returns_requirement_line() -> None:
    clause = resolve_clause(PAGES, description="标准要求抽取不对", properties=["Rm"])
    assert clause is not None
    assert "不小于 470 MPa" in clause["expected"]
    assert clause["page_no"] == 8
    assert clause["source"] == "clause"


def test_resolve_clause_skips_table_rows() -> None:
    pages = [{"page_no": 2, "markdown": "| 抗拉强度 | 470 | 485 |"}]
    assert resolve_clause(pages, description="标准要求不对", properties=["Rm"]) is None


def test_resolve_expected_prefers_cover() -> None:
    result = resolve_expected(
        PAGES, description="标准名称抽取不对", properties=["Rm"]
    )
    assert result is not None
    assert result["source"] == "cover"
    assert result["expected"] == "GB/T 1591-2018"


def test_diagnose_attaches_clause_expected() -> None:
    tables = [
        {
            "table_id": "T1",
            "caption": "表1 力学性能",
            "headers": ["牌号", "Rm"],
            "rows": [["牌号", "Rm"], ["Q355B", ""]],
        }
    ]
    description = "室温拉伸标准要求抽取不对"
    intent = resolve_intent(description, tables)
    context = build_repair_context(
        feedback={"description": description, "target": {"rule_id": "DOC-NO-RECORDS"}},
        tables=tables,
        records=[],
        diagnostics=[],
        recipe={"recipe_id": "mechanical_properties_v1", "version": "1.0"},
        intent=intent,
    )
    diagnosis = diagnose(
        intent=intent,
        repair_context=context,
        tables=tables,
        records=[],
        diagnostics=[],
        pages=PAGES,
        description=description,
    )
    assert "470" in str(diagnosis["expected"])
    assert diagnosis["expected_source"] == "clause"
    assert diagnosis["expected_evidence"]["page_no"] == 8


def test_diagnose_keeps_table_cell_expected_over_clause() -> None:
    tables = [
        {
            "table_id": "T1",
            "caption": "表1 力学性能",
            "headers": ["牌号", "Rm"],
            "rows": [["牌号", "Rm"], ["Q355B", "510"]],
        }
    ]
    records = [
        {
            "record_id": "R1",
            "table_id": "T1",
            "grade": "Q355B",
            "properties": {"Rm": {"raw": "500", "value": 500.0}},
        }
    ]
    description = "抗拉强度取值不对"
    intent = resolve_intent(description, tables, records)
    context = build_repair_context(
        feedback={"description": description, "target": {"rule_id": "DOC-VALUE-WRONG"}},
        tables=tables,
        records=records,
        diagnostics=[],
        recipe={"recipe_id": "mechanical_properties_v1", "version": "1.0"},
        intent=intent,
    )
    diagnosis = diagnose(
        intent=intent,
        repair_context=context,
        tables=tables,
        records=records,
        diagnostics=[],
        pages=PAGES,
        description=description,
    )
    assert diagnosis["expected"] == "510"
    assert diagnosis.get("expected_source") is None
