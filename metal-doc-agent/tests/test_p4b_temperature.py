from metal_doc_agent.contracts import TableBlock, TableGrid
from metal_doc_agent.extraction.qwen import (
    ColumnMapping,
    QwenExtractor,
    _implausible_property,
    _primary_measure_group,
    _same_header_group,
)
from metal_doc_agent.recipes.binding import (
    _resolve_property,
    _resolve_role,
    load_aliases,
)
from metal_doc_agent.schema_projection import _dedupe_hanson_rows
from metal_doc_agent.tablegrid.normalize import canonical_property


def test_symbol_headers_bind_to_tensile_properties() -> None:
    assert canonical_property("δ%") == "A"
    assert canonical_property("Psi%") == "Z"
    assert canonical_property("akuJ/cm²") == "KU2"

    cfg = load_aliases()
    assert (
        _resolve_property(["力学性能，不小于", "δ%"], "mechanical_properties", cfg, None)
        == "A"
    )
    assert (
        _resolve_property(["力学性能，不小于", "Psi%"], "mechanical_properties", cfg, None)
        == "Z"
    )
    assert (
        _resolve_role(
            "δ%",
            "力学性能，不小于 δ%",
            "A",
            "tensile",
            cfg,
        )
        == "measure"
    )


def test_hardness_indentation_is_not_reported_as_hardness() -> None:
    cfg = load_aliases()
    role = _resolve_role(
        "布氏硬度(压痕直径)mm",
        "布氏硬度(压痕直径)mm",
        "HBW",
        "hardness",
        cfg,
    )
    # Keep the measure role so the inspection item survives alignment; the
    # millimetre reading itself is rejected as an implausible HBW value.
    assert role == "measure"
    assert _implausible_property("HBW", "3.30~3.55") is True


def test_primary_measure_group_and_condition_filter() -> None:
    header_paths = [
        ["热处理制度"],
        ["试验温度℃"],
        ["力学性能，不小于", "σbMPa"],
        ["力学性能，不小于", "δ%"],
        ["持久试验", "试验温度℃"],
        ["布氏硬度(压痕直径)mm"],
    ]
    mapping = ColumnMapping(
        condition_cols=[0, 1, 4, 5],
        property_cols={2: "Rm", 3: "A", 5: "HBW"},
    )
    block = TableBlock(
        block_id="B1",
        start_row=0,
        header_rows=2,
        header_paths=header_paths,
    )
    assert _same_header_group("力学性能，不小于", "力学性能")
    assert _primary_measure_group(block, mapping) == "力学性能，不小于"

    table = TableGrid(
        table_id="T1",
        page_no=1,
        n_rows=3,
        n_cols=6,
        header_rows=2,
        rows=[
            [
                "热处理制度",
                "试验温度℃",
                "力学性能，不小于",
                "力学性能，不小于",
                "持久试验",
                "布氏硬度(压痕直径)mm",
            ],
            ["", "", "σbMPa", "δ%", "试验温度℃", ""],
            ["固溶", "室温", "1130", "17", "750", "3.30~3.55"],
        ],
        header_paths=header_paths,
        profile="mechanical_properties",
    )
    condition = QwenExtractor._row_condition(
        table, block, table.rows[-1], mapping
    )
    assert "室温" in (condition or "")
    assert "750" not in (condition or "")
    assert "3.30" not in (condition or "")


def test_duplicate_rows_merge_but_temperatures_stay_separate() -> None:
    rows = [
        {
            "项目名称": "抗拉强度 Rm",
            "材料牌号": "GH4698",
            "试验温度": "室温",
            "标准要求": "≥1130",
            "单位": "MPa",
        },
        {
            "项目名称": "抗拉强度",
            "材料牌号": "GH4698",
            "试验温度": "室温",
            "标准要求": "≥1130",
            "试验方法": "GB/T 228",
            "单位": "MPa",
        },
        {
            "项目名称": "抗拉强度",
            "材料牌号": "GH4698",
            "试验温度": "750℃",
            "标准要求": "≥740",
            "试验方法": "GB/T 4338",
            "单位": "MPa",
        },
    ]
    merged = _dedupe_hanson_rows(rows)
    assert len(merged) == 2
    room = next(row for row in merged if row["试验温度"] == "室温")
    hot = next(row for row in merged if row["试验温度"] == "750℃")
    assert room["试验方法"] == "GB/T 228"
    assert hot["标准要求"] == "≥740"


def test_distinct_requirements_are_not_collapsed() -> None:
    rows = [
        {
            "项目名称": "抗拉强度 Rm",
            "材料牌号": "0Cr17Ni4Cu4Nb",
            "试验温度": "室温",
            "标准要求": "≥1310",
            "单位": "MPa",
        },
        {
            "项目名称": "抗拉强度",
            "材料牌号": "0Cr17Ni4Cu4Nb",
            "试验温度": "室温",
            "标准要求": "≥1310",
            "试验方法": "GB/T 228",
        },
        {
            "项目名称": "抗拉强度",
            "材料牌号": "0Cr17Ni4Cu4Nb",
            "试验温度": "室温",
            "标准要求": "≥1170",
        },
        {
            "项目名称": "抗拉强度",
            "材料牌号": "0Cr17Ni4Cu4Nb",
            "试验温度": "室温",
            "标准要求": "≥1070",
        },
    ]
    merged = _dedupe_hanson_rows(rows)
    assert [row["标准要求"] for row in merged] == ["≥1310", "≥1170", "≥1070"]
    assert merged[0]["试验方法"] == "GB/T 228"
