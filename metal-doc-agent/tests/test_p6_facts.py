"""P6-D fact fixes and fact-level validation tests."""

from __future__ import annotations

from metal_doc_agent.contracts import (
    DocumentMeta,
    Evidence,
    ExtractedValue,
    Record,
    TableGrid,
)
from metal_doc_agent.extraction.matrix import (
    extract_element_matrix,
    extract_hardness_minmax,
    extract_property_matrix,
)
from metal_doc_agent.tablegrid.profile import classify_profile
from metal_doc_agent.extraction.nonrecord import _extract_inspection
from metal_doc_agent.tablegrid.normalize import (
    canonical_element,
    canonical_property,
)
from metal_doc_agent.validation.facts import check_facts


def _document() -> DocumentMeta:
    return DocumentMeta(doc_id="doc", source_path="doc.pdf", file_name="doc.pdf")


def _grid(
    table_id: str,
    headers: list[list[str]],
    rows: list[list[str]],
    *,
    profile: str = "unknown",
    caption: str = "",
) -> TableGrid:
    return TableGrid(
        table_id=table_id,
        page_no=1,
        caption=caption,
        n_rows=len(rows),
        n_cols=max(len(row) for row in rows),
        header_rows=1,
        rows=rows,
        header_paths=headers,
        profile=profile,
    )


def test_hg_na_and_aluminium_are_not_shrunk() -> None:
    assert canonical_element("Hg") == "Hg"
    assert canonical_element("Na") == "Na"
    assert canonical_element("总铝(Alt)a") == "Al"
    assert canonical_element("Feb") == "Fe"
    assert canonical_element("Als") == "Al"
    assert canonical_element("Ni+Ta") == "Ni"


def test_element_sums_are_rejected() -> None:
    assert canonical_element("Cr+Cu+Mo+Ni") is None
    assert canonical_element("Cu+6Sn") is None


def test_hardness_aliases() -> None:
    assert canonical_property("洛氏硬度") == "HRC"
    assert canonical_property("维氏硬度") == "HV"
    assert canonical_property("硬度(HBW)") == "HB"
    assert canonical_property("硬度") == "HB"


def test_property_matrix_keeps_range_bounds() -> None:
    table = _grid(
        "T12",
        [["性能"], ["室温"], ["300℃"]],
        [
            ["性能", "室温", "300℃"],
            ["抗拉强度Rm(MPa)", "440~570", "≥423"],
            ["屈服强度Rp0.2(MPa)", "/", "≥153"],
        ],
        profile="mechanical_properties",
    )
    output = extract_property_matrix(table, _document())
    assert output is not None
    values = {
        (record.condition, key): value
        for record in output.records
        for key, value in record.properties.items()
    }
    room = values[("室温", "Rm")]
    assert room.comparator == "range"
    assert (room.lower, room.upper) == (440.0, 570.0)
    hot = values[("300℃", "Rp0.2")]
    assert hot.value == 153.0
    assert hot.condition == "300℃"


def test_element_matrix_keeps_placeholders_and_bounds() -> None:
    table = _grid(
        "T7",
        [["元素"], ["熔炼分析"]],
        [
            ["元素", "熔炼分析"],
            ["C", "0.08~0.15"],
            ["Hg", "提供数据"],
            ["S", "Refer Table 1A"],
            ["Cu+6Sn", "≤0.33%"],
        ],
        profile="chemical_composition",
        caption="表4-1 化学成分要求",
    )
    output = extract_element_matrix(table, _document())
    assert output is not None
    properties = {
        key: value
        for record in output.records
        for key, value in record.properties.items()
    }
    assert (properties["C"].lower, properties["C"].upper) == (0.08, 0.15)
    assert properties["Hg"].comparator == "text"
    assert properties["Hg"].text == "提供数据"
    assert properties["S"].comparator == "text"
    assert "Cu" not in properties


def test_side_by_side_element_blocks_merge_minimum_and_maximum() -> None:
    table = TableGrid(
        table_id="T8",
        page_no=6,
        n_rows=4,
        n_cols=6,
        header_rows=2,
        rows=[
            ["元素", "含量", "含量", "元素", "含量", "含量"],
            ["元素", "最小值", "最大值", "元素", "最小值", "最大值"],
            ["C", "0.015", "0.060", "B", "--", "0.006"],
            ["Cr", "17.00", "21.00", "Cu", "--", "0.30"],
        ],
        header_paths=[
            ["元素"],
            ["含量", "最小值"],
            ["含量", "最大值"],
            ["元素"],
            ["含量", "最小值"],
            ["含量", "最大值"],
        ],
        profile="chemical_composition",
        orientation="element_rows",
    )
    output = extract_element_matrix(table, _document())
    assert output is not None
    properties = {
        key: value
        for record in output.records
        for key, value in record.properties.items()
    }
    assert (properties["C"].comparator, properties["C"].lower,
            properties["C"].upper) == ("range", 0.015, 0.060)
    assert (properties["Cr"].lower, properties["Cr"].upper) == (17.0, 21.0)
    assert (properties["B"].comparator, properties["B"].value) == ("max", 0.006)
    assert (properties["Cu"].comparator, properties["Cu"].value) == ("max", 0.30)
    assert "Fe" not in properties
    # The empty minimum cell (--) must not become the evidence pointer.
    assert properties["B"].evidence_id.endswith(":c5")
    assert properties["C"].evidence_id.endswith(":c1")


def test_headerless_continuation_element_block_keeps_first_row() -> None:
    table = TableGrid(
        table_id="T10",
        page_no=7,
        n_rows=2,
        n_cols=6,
        header_rows=1,
        rows=[
            ["Co", "--", "1.00", "Te", "--", "0.00005"],
            ["Mn", "--", "0.35", "Tl", "--", "0.0001"],
        ],
        header_paths=[["Co"], ["--"], ["1.00"], ["Te"], ["--"], ["0.00005"]],
        profile="chemical_composition",
        orientation="element_rows",
    )
    output = extract_element_matrix(table, _document())
    assert output is not None
    properties = {
        key: value
        for record in output.records
        for key, value in record.properties.items()
    }
    assert set(properties) == {"Co", "Mn", "Te", "Tl"}
    assert (properties["Co"].comparator, properties["Co"].value) == ("max", 1.0)
    assert (properties["Mn"].comparator, properties["Mn"].value) == ("max", 0.35)
    assert (properties["Te"].comparator, properties["Te"].value) == ("max", 0.00005)


def test_inspection_plan_rows_carry_requirement_and_condition() -> None:
    table = _grid(
        "T4",
        [["测试类别"], ["位置"], ["试样数量"], ["测试条件"], ["验收指标"]],
        [
            ["测试类别", "位置", "试样数量", "测试条件", "验收指标"],
            ["蠕变", "2", "1", "595℃、825MPa下进行50h蠕变试验",
             "在25h试验后蠕变塑性伸长率不应超过0.2%，50h后蠕变伸长率应记录。"],
            ["硬度", "在对应拉伸试料上", "1", "室温", "≥363HB"],
        ],
        profile="inspection",
        caption="表2 力学性能测试条件和验收要求",
    )
    output = _extract_inspection(table, _document())
    items = {item.item: item for item in output.inspection_items}
    creep = items["蠕变"]
    assert creep.requirement and "0.2%" in creep.requirement
    assert creep.condition and "595℃" in creep.condition
    assert creep.sample_location == "2"
    assert items["硬度"].requirement == "≥363HB"


def test_fact_checks_catch_ungrounded_grade_and_value() -> None:
    table = _grid(
        "T1",
        [["牌号"], ["Rm"]],
        [["牌号", "Rm"], ["2A14", "430"]],
    )
    evidence = Evidence(
        evidence_id="ev:doc:T1:r1:c1",
        page_no=1,
        table_id="T1",
        row=1,
        col=1,
        quote="430",
    )
    record = Record(
        record_id="rec-1",
        source_table_id="T1",
        grade="9Z99",
        properties={
            "Rm": ExtractedValue(
                raw="430",
                value=530.0,
                unit="MPa",
                comparator="min",
                evidence_id="ev:doc:T1:r1:c1",
            )
        },
    )
    issues = check_facts(_document(), [record], [evidence], [table])
    codes = {issue.code for issue in issues}
    assert "GRADE_UNGROUNDED" in codes
    assert "VALUE_NOT_IN_SOURCE" in codes


def test_header_only_cover_table_is_not_chemistry() -> None:
    table = _grid(
        "T1",
        [["H"], ["P"], ["X"], ["4"], ["4"], ["3"], ["B"], ["N"]],
        [["H", "P", "X", "4", "4", "3", "B", "N"]],
        profile="chemical_composition",
    )
    assert classify_profile(table) == "admin"


def test_nitrogen_with_footnote_is_not_sodium() -> None:
    table = _grid(
        "T6",
        [["元素"], ["熔炼分析"], ["成品分析"]],
        [
            ["元素", "熔炼分析", "成品分析"],
            ["C", "0.08~0.20", "0.06~0.22"],
            ["Na", "≤0.012", "≤0.017"],
            ["Nb", "≤0.020", "≤0.025"],
            ["Ni", "≤0.30", "≤0.35"],
            ["注： a、总铝和氮元素含量的比值应满足Al:N≥2。",
             "注： a、总铝和氮元素含量的比值应满足Al:N≥2。",
             "注： a、总铝和氮元素含量的比值应满足Al:N≥2。"],
        ],
        profile="chemical_composition",
    )
    output = extract_element_matrix(table, _document())
    assert output is not None
    properties = {
        key for record in output.records for key in record.properties
    }
    assert properties == {"C", "N", "Nb", "Ni"}


def test_grade_row_chemistry_is_read_as_grade_records() -> None:
    table = _grid(
        "T1",
        [["牌号"], ["C"], ["Si"], ["Cr"]],
        [
            ["牌号", "C", "Si", "Cr"],
            ["04Cr13Ni5Mo", "≤0.04", "≤0.60", "12.00~13.50"],
        ],
        profile="chemical_composition",
    )
    output = extract_element_matrix(table, _document())
    assert output is not None
    assert [record.grade for record in output.records] == ["04Cr13Ni5Mo"]
    values = output.records[0].properties
    assert set(values) == {"C", "Si", "Cr"}
    assert values["Cr"].comparator == "range"
    assert (values["Cr"].lower, values["Cr"].upper) == (12.0, 13.5)


def test_hardness_minimum_and_maximum_columns_are_both_kept() -> None:
    table = _grid(
        "T10",
        [["Material Designation"], ["Minimum Brinell Hardness"],
         ["Maximum Brinell Hardness"]],
        [
            ["Material Designation", "Minimum Brinell Hardness",
             "Maximum Brinell Hardness"],
            ["60 K", "HBW 174", "HBW 237 (22 HRC) (As per NACE MR0103)"],
        ],
        profile="mechanical_properties",
    )
    output = extract_hardness_minmax(table, _document())
    assert output is not None
    values = {
        value.comparator: (value.lower, value.upper)
        for record in output.records
        for value in record.properties.values()
    }
    assert values == {"range": (174.0, 237.0)}


def test_fact_checks_catch_hardness_scale_mismatch() -> None:
    evidence = Evidence(
        evidence_id="ev:doc:T2:r1:c1",
        page_no=1,
        table_id="T2",
        row=1,
        col=1,
        quote="31.5",
    )
    record = Record(
        record_id="rec-2",
        source_table_id="T2",
        grade="GH4169",
        properties={
            "HB": ExtractedValue(
                raw="31.5",
                value=31.5,
                unit="HRC",
                comparator="min",
                evidence_id="ev:doc:T2:r1:c1",
            )
        },
    )
    issues = check_facts(_document(), [record], [evidence], [])
    codes = {issue.code for issue in issues}
    assert "HARDNESS_SCALE_MISMATCH" in codes
    assert "HARDNESS_VALUE_OUT_OF_SCALE" in codes
