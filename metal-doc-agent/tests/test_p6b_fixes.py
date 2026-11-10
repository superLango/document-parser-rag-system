"""P6-B follow-up extraction fixes."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from metal_doc_agent.contracts import (
    ClauseRecord,
    DocumentMeta,
    ExtractedValue,
    ItemInventoryEntry,
    Record,
    TableGrid,
)
from metal_doc_agent.extraction.ir_matrix import (
    compare_extraction_outputs,
    extract_element_matrix_ir,
)
from metal_doc_agent.extraction.matrix import extract_element_matrix
from metal_doc_agent.extraction.nonrecord import extract_nonrecord
from metal_doc_agent.schema_projection import (
    _hanson_candidates,
    _requirement_from_qualitative_clauses,
    load_template,
    project_hanson_schema,
)
from metal_doc_agent.tablegrid.ir import build_table_ir

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = ROOT / "configs" / "schema_templates" / "product_standard.json"


def _document() -> DocumentMeta:
    return DocumentMeta(doc_id="doc", source_path="doc.pdf", file_name="doc.pdf")


def test_inspection_positions_merge_into_one_item() -> None:
    table = TableGrid(
        table_id="T3",
        page_no=6,
        n_rows=7,
        n_cols=5,
        header_rows=1,
        rows=[
            ["测试类别", "位置", "试样数量", "测试条件", "验收指标"],
            ["室温拉伸", "1", "1", "室温", "按**-0505-2004"],
            ["室温拉伸", "2", "1", "室温", "按**-0505-2004"],
            ["室温拉伸", "3", "1", "室温", "按**-0505-2004"],
            ["光滑持久", "2", "2", "650℃×725MPa", "按**-0505-2004"],
            ["光滑持久", "3", "2", "650℃×725MPa", "按**-0505-2004"],
        ],
        header_paths=[
            ["测试类别"], ["位置"], ["试样数量"], ["测试条件"], ["验收指标"],
        ],
        profile="inspection",
        caption="表1 力学性能测试条件和验收要求",
    )
    output = extract_nonrecord(table, _document())
    items = {item.item: item for item in output.inspection_items}
    assert set(items) == {"室温拉伸", "光滑持久"}
    assert items["室温拉伸"].sample_location == "1/2/3"
    assert items["光滑持久"].sample_location == "2/3"
    assert items["光滑持久"].quantities == {"试样数量": "2"}


def _approval_job(root: Path) -> Path:
    result = {
        "document": {
            "doc_id": "doc-approval",
            "source_path": "approval.pdf",
            "file_name": "approval.pdf",
            "title": "GH4169 盘前后封严挡板锻件批准试验要求",
            "page_count": 8,
        },
        "tables": [],
        "records": [],
        "inspection_items": [
            {
                "item": "光滑持久",
                "quantities": {"试样数量": "1"},
                "sample_location": "2",
                "condition": "650℃×725MPa",
                "requirement": "按**-0505-2004",
                "evidence_id": "ev:persistence-725",
            },
            {
                "item": "光滑持久",
                "quantities": {"试样数量": "2"},
                "sample_location": "2/3",
                "condition": "650℃×700MPa",
                "requirement": "按**-0505-2004",
                "evidence_id": "ev:persistence-700",
            },
        ],
        "classification_items": [{"grade": "GH4169", "evidence_id": "ev:t1"}],
        "clauses": [],
    }
    (root / "result.json").write_text(
        json.dumps(result, ensure_ascii=False), encoding="utf-8"
    )
    inventory = {
        "doc_id": "doc-approval",
        "items": [
            {
                "item_raw": "光滑持久",
                "item_family": "stress_rupture",
                "facets": {},
                "properties": [],
                "status": "confirmed",
            }
        ],
    }
    (root / "item_inventory.json").write_text(
        json.dumps(inventory, ensure_ascii=False), encoding="utf-8"
    )
    return root


def test_reported_footnote_elements_are_extracted() -> None:
    note = (
        "* The Values of Copper, Columbium (Niobium) and Boron are to be "
        "reported but no limits applies, However, alloy steel shall conform to "
        "the requirements for Grade L5 of Specification A707/A707M."
    )
    table = TableGrid(
        table_id="T3",
        page_no=2,
        n_rows=4,
        n_cols=2,
        header_rows=1,
        rows=[
            ["Alloying Element", "Composition, % (Heat Analysis)"],
            ["Carbon, Max", "0.22"],
            ["Manganese, Max", "1.60"],
            [note, note],
        ],
        header_paths=[
            ["Alloying Element"],
            ["Composition, % (Heat Analysis)"],
        ],
        profile="chemical_composition",
        orientation="element_rows",
    )
    output = extract_element_matrix(table, _document())
    assert output is not None
    properties = {
        key: value for record in output.records for key, value in record.properties.items()
    }
    assert {"C", "Mn", "Cu", "Nb", "B"} <= set(properties)
    for element in ("Cu", "Nb", "B"):
        assert properties[element].comparator == "text"
        assert properties[element].text == "to be reported"

    current = extract_element_matrix_ir(
        build_table_ir(table, doc_id="doc"), _document()
    )
    assert compare_extraction_outputs(output, current)["status"] == "identical"


def test_product_analysis_column_is_kept_when_different() -> None:
    table = TableGrid(
        table_id="T7",
        page_no=9,
        n_rows=3,
        n_cols=3,
        header_rows=1,
        rows=[
            ["元素", "熔炼分析", "成品分析"],
            ["C", "0.08~0.15", "0.06~0.22"],
            ["S", "≤0.030", "≤0.030"],
        ],
        header_paths=[["元素"], ["熔炼分析"], ["成品分析"]],
        profile="chemical_composition",
        orientation="element_rows",
    )
    output = extract_element_matrix(table, _document())
    assert output is not None
    rows = [
        (record.properties["C"].condition, record.properties["C"].lower,
         record.properties["C"].upper, record.facets.get("analysis"))
        for record in output.records
        if "C" in record.properties
    ]
    assert rows == [
        (None, 0.08, 0.15, "熔炼分析"),
        (None, 0.06, 0.22, "成品分析"),
    ]
    # S 两列完全相同，只保留熔炼分析。
    assert sum(1 for record in output.records if "S" in record.properties) == 1

    current = extract_element_matrix_ir(
        build_table_ir(table, doc_id="doc"), _document()
    )
    assert compare_extraction_outputs(output, current)["status"] == "identical"


def test_schema_prefers_heat_analysis_over_product_analysis() -> None:
    heat = Record(
        record_id="heat-c",
        source_table_id="T1",
        condition="化学成分",
        properties={"C": ExtractedValue(raw="0.08~0.15", lower=0.08, upper=0.15)},
    )
    product = Record(
        record_id="product-c",
        source_table_id="T1",
        condition="成品分析",
        facets={"analysis": "成品分析"},
        properties={
            "C": ExtractedValue(raw="0.08~0.15", lower=0.08, upper=0.15),
            "Ca": ExtractedValue(raw="≤0.0030", value=0.003, comparator="max"),
        },
    )
    product_cu = Record(
        record_id="product-cu",
        source_table_id="T1",
        condition="成品分析",
        facets={"analysis": "成品分析"},
        properties={"Cu": ExtractedValue(raw="≤0.20", value=0.2, comparator="max")},
    )
    item = ItemInventoryEntry(
        item_raw="化学成分",
        item_family="chemical_composition",
        properties=["C", "Cu"],
        status="confirmed",
    )
    selected = _hanson_candidates(
        item,
        "化学成分",
        [heat, product, product_cu],
        {"T1": {"profile": "chemical_composition"}},
    )
    assert [record.record_id for record in selected] == [
        "heat-c",
        "product-c",
        "product-cu",
    ]
    product_ca = next(record for record in selected if record.record_id == "product-c")
    assert set(product_ca.properties) == {"Ca"}


def test_product_analysis_keeps_different_values() -> None:
    heat = Record(
        record_id="heat",
        source_table_id="T3",
        grade="304",
        condition="熔炼分析",
        properties={
            "Mn": ExtractedValue(raw="≤2.00", value=2.0, comparator="max"),
            "Si": ExtractedValue(raw="≤1.00", value=1.0, comparator="max"),
        },
    )
    product = Record(
        record_id="product",
        source_table_id="T3",
        grade="304",
        condition="成品分析",
        facets={"analysis": "成品分析"},
        properties={
            "Mn": ExtractedValue(raw="≤2.04", value=2.04, comparator="max"),
            "Si": ExtractedValue(raw="≤1.05", value=1.05, comparator="max"),
        },
    )
    item = ItemInventoryEntry(
        item_raw="化学成分",
        item_family="chemical_composition",
        properties=["Mn", "Si"],
        status="confirmed",
    )
    selected = _hanson_candidates(
        item,
        "化学成分",
        [heat, product],
        {"T3": {"profile": "chemical_composition"}},
    )
    assert [record.record_id for record in selected] == ["heat", "product"]


def test_ndt_and_inclusion_clauses_feed_schema_requirements() -> None:
    text = "锻件的非金属夹杂物按照NB/T 20008.12 第8.3 节的要求。；检验结果满足表5-4 要求："
    clauses = [
        ClauseRecord(
            clause_id="5.3.3.1",
            title="非金属夹杂物",
            kind="other",
            fields={
                "requirement": ExtractedValue(
                    raw=text, text=text, comparator="text", evidence_id="ev:1"
                )
            },
            evidence=["ev:1"],
        ),
        ClauseRecord(
            clause_id="7.2",
            title="超声波检验",
            kind="other",
            fields={
                "requirement": ExtractedValue(
                    raw="超声检测的实施方法，按照NB/T 20008.12 第11.2 节的要求执行。",
                    text="超声检测的实施方法，按照NB/T 20008.12 第11.2 节的要求执行。",
                    comparator="text",
                    evidence_id="ev:2",
                )
            },
            evidence=["ev:2"],
        ),
    ]
    inclusion = _requirement_from_qualitative_clauses("非金属夹杂", clauses)
    assert inclusion and "表5-4" in inclusion and "NB/T 20008.12" in inclusion
    ultrasonic = _requirement_from_qualitative_clauses("超声波检测", clauses)
    assert ultrasonic and "第11.2 节" in ultrasonic


def test_schema_keeps_persistence_stress_and_positions() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        job = _approval_job(Path(tmp))
        payload = project_hanson_schema(job, load_template(TEMPLATE_PATH))
        categories = {
            category["feature"]: category
            for category in payload["categories"]
        }
        records = categories["高温光滑持久"]["records"]
        stresses = {
            record["标准要求"].split("试验应力")[-1]
            for record in records
            if "试验应力" in record["标准要求"]
        }
        assert stresses == {"725MPa", "700MPa"}
        assert {record["位置"] for record in records} == {"2", "2/3"}
