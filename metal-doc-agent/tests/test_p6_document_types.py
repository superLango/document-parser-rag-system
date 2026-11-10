"""P6-A document type routing tests."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from metal_doc_agent.contracts import DocumentMeta, Page, TableGrid
from metal_doc_agent.pipeline import run_pipeline
from metal_doc_agent.coverage.plan import build_coverage
from metal_doc_agent.document_types import (
    APPROVAL_TEST,
    HEAT_TREATMENT_PLAN,
    MANUFACTURING_OUTLINE,
    PROCESS_DOCUMENT,
    PRODUCT_STANDARD,
    PURCHASE_SPEC,
    detect_document_type,
)


def _document(standard_no: str | None = None) -> DocumentMeta:
    return DocumentMeta(
        doc_id="doc",
        source_path="doc.pdf",
        file_name="doc.pdf",
        standard_no=standard_no,
    )


def _page(text: str, page_no: int = 1) -> Page:
    return Page(page_no=page_no, markdown=text)


def _table(caption: str, headers: list[list[str]], profile: str = "unknown") -> TableGrid:
    return TableGrid(
        table_id="T1",
        page_no=1,
        caption=caption,
        header_paths=headers,
        rows=[],
        n_rows=0,
        n_cols=len(headers),
        profile=profile,
    )


def _detect(text: str, tables: list[TableGrid] | None = None, standard_no=None):
    return detect_document_type(
        _document(standard_no),
        [_page(text)],
        tables or [],
    )


def _detect_pages(pages: list[str], tables: list[TableGrid] | None = None):
    return detect_document_type(
        _document(),
        [_page(text, index + 1) for index, text in enumerate(pages)],
        tables or [],
    )


def test_heat_treatment_plan_is_not_applicable() -> None:
    result = _detect(
        "AGT25燃气轮机零件热处理、化学热处理检查组别\n4.1 检查组别由设计部门确定。",
        [
            _table(
                "表1 检查组别",
                [["检查组别"], ["抽检比例"]],
                profile="inspection",
            )
        ],
    )
    assert result.doc_type == HEAT_TREATMENT_PLAN
    assert result.not_applicable is True
    assert result.confidence >= 0.8


def test_approval_test_from_cover_title() -> None:
    result = _detect(
        "GH4169 盘前后封严挡板锻件批准试验要求\n表1 力学性能测试条件和验收要求",
        [
            _table(
                "表1 力学性能测试条件和验收要求",
                [["测试类别"], ["验收指标"]],
                profile="inspection",
            )
        ],
    )
    assert result.doc_type == APPROVAL_TEST
    assert result.not_applicable is False


def test_manufacturing_outline_beats_purchase_mentions() -> None:
    result = _detect_pages(
        [
            "12Cr13 锻件制造大纲\n图册（文件）名称：蒸汽发生器定距螺杆用12Cr13锻件制造大纲",
            "5.3.2 力学性能应满足表5-3 中的要求。",
            "6 锻件在精加工完成后，应按采购合同约定的尺寸及公差进行检验。"
            "采购规范 DFHM-QCD-0706-000893。",
        ]
    )
    assert result.doc_type == MANUFACTURING_OUTLINE


def test_purchase_spec_from_title() -> None:
    result = _detect(
        "ZWB项目用304NG饼形锻件采购技术规格书\n"
        "1 范围 本采购技术规格书规定了锻件的技术要求。"
    )
    assert result.doc_type == PURCHASE_SPEC
    assert result.coverage_template == "purchase"


def test_english_material_specification_is_purchase() -> None:
    result = _detect(
        "Title: Material specification for forgings produced to ASTM A694 Gr F65.\n"
        "1. Scope: This specification specifies the required processes."
    )
    assert result.doc_type == PURCHASE_SPEC


def test_process_document() -> None:
    result = _detect(
        "GH4169 锻件工艺规程\n1 锻造工艺卡 2 热处理工序卡 3 作业指导书"
    )
    assert result.doc_type == PROCESS_DOCUMENT
    assert result.coverage_template == "enterprise"


def test_product_standard_from_standard_number() -> None:
    result = _detect(
        "GB/T 1220-2007 不锈钢棒\n"
        "1 范围 本标准规定了不锈钢棒的尺寸、外形、技术要求。\n"
        "2 规范性引用文件",
        standard_no="GB/T 1220-2007",
    )
    assert result.doc_type == PRODUCT_STANDARD


def test_unknown_document_is_not_forced() -> None:
    result = _detect("随机会议记录：讨论了交付时间和人员安排。")
    assert result.doc_type == "unknown"
    assert result.not_applicable is False


def test_coverage_marks_heat_plan_not_applicable() -> None:
    result = _detect("零件热处理、化学热处理检查组别", standard_no=None)
    plan = build_coverage(
        document=_document(),
        records=[],
        tables=[],
        evidence=[],
        template="product_full",
        document_type=result,
    )
    assert plan.items
    assert all(item.status == "not_applicable" for item in plan.items)


def test_pipeline_skips_projection_for_heat_plan() -> None:
    text = (
        "# 零件热处理、化学热处理检查组别\n\n"
        "4.1 检查组别由设计部门确定。\n\n"
        "4.3 根据经热处理零件试验种类的内容不同，检查组别应符合表1的规定。\n\n"
        "表1 检查组别和抽检比例\n\n"
        "<table border=\"1\"><tr><td>检查组别</td><td>抽检比例</td></tr>"
        "<tr><td>第1组</td><td>100%</td></tr></table>\n"
    )
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        doc = root / "heat_plan.md"
        doc.write_text(text, encoding="utf-8")
        out = root / "out"
        run_pipeline(doc, out)
        detected = json.loads(
            (out / "document_type.json").read_text(encoding="utf-8")
        )
        assert detected["doc_type"] == HEAT_TREATMENT_PLAN
        assert detected["not_applicable"] is True
        assert not (out / "schema_result.json").exists()
        coverage = json.loads(
            (out / "coverage_plan.json").read_text(encoding="utf-8")
        )
        assert coverage["items"]
        assert all(
            item["status"] == "not_applicable" for item in coverage["items"]
        )
