"""Unified table IR (P6-B) tests."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from metal_doc_agent.contracts import (
    ColumnBinding,
    ColumnBindingResult,
    DocumentMeta,
    TableBlock,
    TableGrid,
)
from metal_doc_agent.extraction.ir_matrix import (
    compare_extraction_outputs,
    extract_bound_matrix_ir,
    extract_element_matrix_ir,
    extract_hardness_minmax_ir,
    extract_property_matrix_ir,
)
from metal_doc_agent.extraction.matrix import (
    extract_bound_matrix,
    extract_element_matrix,
    extract_hardness_minmax,
    extract_property_matrix,
)
from metal_doc_agent.extraction.nonrecord import (
    compare_nonrecord_outputs,
    extract_nonrecord,
    extract_nonrecord_ir,
)
from metal_doc_agent.pipeline import run_pipeline
from metal_doc_agent.tablegrid.ir import build_table_ir, table_grid_from_ir


def _document() -> DocumentMeta:
    return DocumentMeta(doc_id="doc", source_path="doc.pdf", file_name="doc.pdf")


def _chemistry_grid() -> TableGrid:
    rows = [
        ["牌号", "化学成分", "化学成分"],
        ["牌号", "C", "Si"],
        ["Q355", "≤0.20", "0.50"],
        ["注：a、单位为质量分数。", "注：a、单位为质量分数。", "注：a、单位为质量分数。"],
    ]
    paths = [["牌号", "牌号"], ["化学成分", "C"], ["化学成分", "Si"]]
    return TableGrid(
        table_id="T2",
        page_no=3,
        caption="表2 化学成分",
        n_rows=len(rows),
        n_cols=3,
        header_rows=2,
        rows=rows,
        header_paths=paths,
        units=["%"],
        footnotes=["注：a、单位为质量分数。"],
        profile="chemical_composition",
        orientation="grade_rows",
        blocks=[
            TableBlock(
                block_id="T2-B1",
                start_row=0,
                header_rows=2,
                header_paths=paths,
                rows=rows,
            )
        ],
    )


def _impact_grid() -> TableGrid:
    return TableGrid(
        table_id="T13",
        page_no=1,
        n_rows=5,
        n_cols=4,
        header_rows=3,
        rows=[
            ["牌号", "牌号", "KV2", "KV2"],
            ["钢级", "质量等级", "20℃", "20℃"],
            ["钢级", "质量等级", "纵向", "横向"],
            ["Q355、Q390", "B", "34", "27"],
            ["Q355", "C", "-", "30a"],
        ],
        header_paths=[
            ["牌号", "钢级"],
            ["牌号", "质量等级"],
            ["以下试验温度的冲击吸收能量最小值 KV2/J", "20℃", "纵向"],
            ["以下试验温度的冲击吸收能量最小值 KV2/J", "20℃", "横向"],
        ],
        profile="mechanical_properties",
    )


def _impact_binding() -> ColumnBindingResult:
    return ColumnBindingResult(
        table_id="T13",
        bindings=[
            ColumnBinding(column=0, header_path=["牌号", "钢级"], role="row_key"),
            ColumnBinding(column=1, header_path=["牌号", "质量等级"], role="row_key"),
            ColumnBinding(
                column=2,
                header_path=["冲击", "20℃", "纵向"],
                property="KV2",
                role="measure",
                unit="J",
            ),
            ColumnBinding(
                column=3,
                header_path=["冲击", "20℃", "横向"],
                property="KV2",
                role="measure",
                unit="J",
            ),
        ],
    )


def test_ir_round_trip_keeps_extractable_fields() -> None:
    table = _chemistry_grid()
    ir = build_table_ir(table, doc_id="doc")
    restored = table_grid_from_ir(ir)

    assert restored.table_id == table.table_id
    assert restored.page_no == table.page_no
    assert restored.caption == table.caption
    assert restored.rows == table.rows
    assert restored.header_paths == table.header_paths
    assert restored.header_rows == table.header_rows
    assert restored.n_rows == table.n_rows
    assert restored.n_cols == table.n_cols
    assert restored.units == table.units
    assert restored.footnotes == table.footnotes
    assert restored.profile == table.profile
    assert restored.orientation == table.orientation
    assert [block.block_id for block in restored.blocks] == ["T2-B1"]
    assert restored.blocks[0].header_paths == table.header_paths


def test_cells_carry_role_property_unit_and_evidence() -> None:
    ir = build_table_ir(_impact_grid(), binding=_impact_binding(), doc_id="doc")
    cells = {(cell.row, cell.col): cell for cell in ir.cells}

    measure = cells[(3, 2)]
    assert measure.role == "measure"
    assert measure.property == "KV2"
    assert measure.unit == "J"
    assert measure.value_type == "number"
    assert measure.comparator == "eq"
    assert measure.evidence_id == "ev:doc:T13:r3:c2"
    assert measure.header_path == ["以下试验温度的冲击吸收能量最小值 KV2/J", "20℃", "纵向"]

    header = cells[(0, 0)]
    assert header.role == "header"
    assert header.raw_role == "header"
    assert header.evidence_id == ""

    key = cells[(3, 0)]
    assert key.role == "row_key"
    assert key.property is None

    assert cells[(4, 2)].value_type == "na"
    assert cells[(4, 2)].comparator == "na"
    assert cells[(4, 3)].value_type == "number"


def test_cell_value_types_describe_raw_cells() -> None:
    table = _chemistry_grid()
    ir = build_table_ir(table, doc_id="doc")
    cells = {(cell.row, cell.col): cell for cell in ir.cells}
    assert cells[(2, 1)].value_type == "number"
    assert cells[(2, 1)].comparator == "max"
    assert cells[(2, 2)].value_type == "number"
    assert cells[(2, 2)].comparator == "eq"
    assert cells[(3, 0)].raw_role == "footnote"
    assert cells[(3, 0)].role == "footnote"

    placeholder_grid = TableGrid(
        table_id="T7",
        page_no=1,
        n_rows=3,
        n_cols=2,
        header_rows=1,
        rows=[["元素", "熔炼分析"], ["Hg", "提供数据"], ["S", "Refer Table 1A"]],
        header_paths=[["元素"], ["熔炼分析"]],
        profile="chemical_composition",
    )
    ir = build_table_ir(placeholder_grid, doc_id="doc")
    cells = {(cell.row, cell.col): cell for cell in ir.cells}
    assert cells[(1, 1)].value_type == "placeholder"
    assert cells[(1, 1)].comparator == "text"
    assert cells[(2, 1)].value_type == "text"


def test_element_row_values_inherit_the_row_property() -> None:
    table = TableGrid(
        table_id="T7",
        page_no=9,
        n_rows=3,
        n_cols=3,
        header_rows=1,
        rows=[
            ["元素", "熔炼分析", "成品分析"],
            ["C", "0.08-0.15", "0.08-0.15"],
            ["Si", "≤1.00", "≤1.00"],
        ],
        header_paths=[["元素"], ["熔炼分析"], ["成品分析"]],
        profile="chemical_composition",
        orientation="element_rows",
    )
    ir = build_table_ir(table, doc_id="doc")
    cells = {(cell.row, cell.col): cell for cell in ir.cells}
    for col in (1, 2):
        assert cells[(1, col)].role == "measure"
        assert cells[(1, col)].property == "C"
        assert cells[(1, col)].unit == "%"
        assert cells[(1, col)].value_type == "range"
        assert cells[(2, col)].property == "Si"
    assert cells[(1, 0)].role == "row_key"


def test_ir_matrix_matches_legacy_output() -> None:
    table = _impact_grid()
    binding = _impact_binding()
    legacy = extract_bound_matrix(table, binding, _document())
    current = extract_bound_matrix_ir(
        build_table_ir(table, binding=binding, doc_id="doc"), binding, _document()
    )
    assert legacy is not None and current is not None
    diff = compare_extraction_outputs(legacy, current)
    assert diff["status"] == "identical"
    assert diff["records_equal"] is True
    assert diff["evidence_equal"] is True
    assert [row.grade for row in current.records] == [
        "Q355B",
        "Q390B",
        "Q355B",
        "Q390B",
        "Q355C",
    ]
    assert current.records[0].condition == "20℃/纵向"


def test_ir_matrix_matches_legacy_on_thickness_bands() -> None:
    table = TableGrid(
        table_id="T3",
        page_no=1,
        n_rows=4,
        n_cols=4,
        header_rows=2,
        rows=[
            ["牌号", "牌号", "碳当量", "碳当量"],
            ["钢级", "质量等级", "≤30", ">30~63"],
            ["Q355", "B", "0.36", "0.39"],
            ["Q390", "C", "0.40", "0.43"],
        ],
        header_paths=[
            ["牌号", "钢级"],
            ["牌号", "质量等级"],
            ["碳当量CEV(质量分数)/%不大于", "≤30"],
            ["碳当量CEV(质量分数)/%不大于", ">30~63"],
        ],
        profile="chemical_composition",
    )
    binding = ColumnBindingResult(
        table_id="T3",
        bindings=[
            ColumnBinding(column=0, header_path=["牌号", "钢级"], role="row_key"),
            ColumnBinding(column=1, header_path=["牌号", "质量等级"], role="row_key"),
            ColumnBinding(
                column=2, header_path=["碳当量", "≤30"], property="CEV",
                role="measure", unit="%",
            ),
            ColumnBinding(
                column=3, header_path=["碳当量", ">30~63"], property="CEV",
                role="measure", unit="%",
            ),
        ],
    )
    legacy = extract_bound_matrix(table, binding, _document())
    current = extract_bound_matrix_ir(
        build_table_ir(table, binding=binding, doc_id="doc"), binding, _document()
    )
    assert compare_extraction_outputs(legacy, current)["status"] == "identical"


def test_ir_element_matrix_matches_legacy_output() -> None:
    table = TableGrid(
        table_id="T6",
        page_no=9,
        n_rows=6,
        n_cols=3,
        header_rows=1,
        caption="表4-1 化学成分要求",
        rows=[
            ["元素", "熔炼分析", "成品分析"],
            ["C", "0.08~0.20", "0.06~0.22"],
            ["Na", "≤0.012", "≤0.017"],
            ["Nb", "≤0.020", "≤0.025"],
            ["Ni", "≤0.30", "≤0.35"],
            ["注： a、总铝和氮元素含量的比值应满足Al:N≥2。",
             "注： a、总铝和氮元素含量的比值应满足Al:N≥2。",
             "注： a、总铝和氮元素含量的比值应满足Al:N≥2。"],
        ],
        header_paths=[["元素"], ["熔炼分析"], ["成品分析"]],
        footnotes=["注： a、总铝和氮元素含量的比值应满足Al:N≥2。"],
        profile="chemical_composition",
        orientation="element_rows",
    )
    legacy = extract_element_matrix(table, _document())
    current = extract_element_matrix_ir(
        build_table_ir(table, doc_id="doc"), _document()
    )
    assert compare_extraction_outputs(legacy, current)["status"] == "identical"
    assert current is not None
    assert {key for record in current.records for key in record.properties} == {
        "C",
        "N",
        "Nb",
        "Ni",
    }


def test_ir_property_matrix_matches_legacy_output() -> None:
    table = TableGrid(
        table_id="T12",
        page_no=1,
        n_rows=3,
        n_cols=3,
        header_rows=1,
        rows=[
            ["性能", "室温", "300℃"],
            ["抗拉强度Rm(MPa)", "440~570", "≥423"],
            ["屈服强度Rp0.2(MPa)", "/", "≥153"],
        ],
        header_paths=[["性能"], ["室温"], ["300℃"]],
        profile="mechanical_properties",
    )
    legacy = extract_property_matrix(table, _document())
    current = extract_property_matrix_ir(
        build_table_ir(table, doc_id="doc"), _document()
    )
    assert compare_extraction_outputs(legacy, current)["status"] == "identical"
    assert current is not None
    values = {
        (record.condition, key): value
        for record in current.records
        for key, value in record.properties.items()
    }
    assert (values[("室温", "Rm")].lower, values[("室温", "Rm")].upper) == (440.0, 570.0)
    assert values[("300℃", "Rp0.2")].value == 153.0


def test_ir_hardness_minmax_matches_legacy_output() -> None:
    table = TableGrid(
        table_id="T10",
        page_no=1,
        n_rows=2,
        n_cols=3,
        header_rows=1,
        rows=[
            ["Material Designation", "Minimum Brinell Hardness",
             "Maximum Brinell Hardness"],
            ["60 K", "HBW 174", "HBW 237 (22 HRC) (As per NACE MR0103)"],
        ],
        header_paths=[
            ["Material Designation"],
            ["Minimum Brinell Hardness"],
            ["Maximum Brinell Hardness"],
        ],
        profile="mechanical_properties",
    )
    legacy = extract_hardness_minmax(table, _document())
    current = extract_hardness_minmax_ir(
        build_table_ir(table, doc_id="doc"), _document()
    )
    assert compare_extraction_outputs(legacy, current)["status"] == "identical"
    assert current is not None
    values = {
        value.comparator: (value.lower, value.upper)
        for record in current.records
        for value in record.properties.values()
    }
    assert values == {"range": (174.0, 237.0)}


def test_ir_nonrecord_matches_legacy_output() -> None:
    table = TableGrid(
        table_id="T3",
        page_no=6,
        n_rows=4,
        n_cols=5,
        header_rows=1,
        rows=[
            ["测试类别", "位置", "试样数量", "测试条件", "验收指标"],
            ["室温拉伸", "1", "1", "室温", "按**-0505-2004"],
            ["室温拉伸", "2", "1", "室温", "按**-0505-2004"],
            ["光滑持久", "2", "1", "650℃×725MPa", "按**-0505-2004"],
        ],
        header_paths=[
            ["测试类别"], ["位置"], ["试样数量"], ["测试条件"], ["验收指标"],
        ],
        profile="inspection",
        caption="表1 力学性能测试条件和验收要求",
    )
    legacy = extract_nonrecord(table, _document())
    current = extract_nonrecord_ir(
        build_table_ir(table, doc_id="doc"), _document()
    )
    assert compare_nonrecord_outputs(legacy, current)["status"] == "identical"
    assert len(current.inspection_items) == 2
    assert current.inspection_items[0].sample_location == "1/2"


SAMPLE = """# Page 1

表1 冲击性能

<table border="1">
  <tr><td rowspan="2">牌号</td><td colspan="2">冲击吸收能量KV2/J</td></tr>
  <tr><td>20℃ 纵向</td><td>20℃ 横向</td></tr>
  <tr><td>Q355</td><td>34</td><td>27</td></tr>
</table>
"""


def test_pipeline_writes_table_ir_and_dual_run_diff() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        doc = root / "impact.md"
        doc.write_text(SAMPLE, encoding="utf-8")
        out = root / "out"
        run_pipeline(doc, out)

        bundle = json.loads((out / "table_ir.json").read_text(encoding="utf-8"))
        assert bundle["doc_id"]
        assert len(bundle["tables"]) == 1
        ir = bundle["tables"][0]
        assert ir["header_rows"] == 2
        assert any(cell["role"] == "measure" for cell in ir["cells"])

        diff = json.loads((out / "table_ir_diff.json").read_text(encoding="utf-8"))
        assert diff["summary"]["mismatch"] == 0
        assert diff["summary"]["tables"] == len(diff["tables"])
        assert diff["summary"]["identical"] >= 1

        result = json.loads((out / "result.json").read_text(encoding="utf-8"))
        assert result["artifacts"]["table_ir"] == "table_ir.json"
        assert result["artifacts"]["table_ir_diff"] == "table_ir_diff.json"
