from metal_doc_agent.contracts import DocumentMeta, TableGrid
from metal_doc_agent.extraction.matrix import (
    extract_element_matrix,
    extract_grade_property_matrix,
    extract_property_matrix,
    extract_property_rows,
)
from metal_doc_agent.items.discover import (
    _inspection_table_items,
    _profile_fallback_items,
)
from metal_doc_agent.items.taxonomy import classify_item
from metal_doc_agent.schema_projection import (
    _plausible_grade,
    _requirement_from_test_requirement_tables,
)
from metal_doc_agent.tablegrid.normalize import (
    canonical_element,
    canonical_property,
)
from metal_doc_agent.tablegrid.profile import _is_element_header, classify_profile


def _grid(
    table_id: str,
    caption: str,
    headers: list[list[str]],
    rows: list[list[str]],
    *,
    profile: str = "unknown",
    header_rows: int = 1,
) -> TableGrid:
    return TableGrid(
        table_id=table_id,
        page_no=1,
        caption=caption,
        n_rows=len(rows),
        n_cols=max(len(row) for row in rows),
        header_rows=header_rows,
        rows=rows,
        header_paths=headers,
        profile=profile,
    )


def test_inclusion_table_is_not_chemistry() -> None:
    grid = _grid(
        "T18",
        "表5 -4非金属夹杂物检验要求",
        [
            ["A类", "粗系"], ["A类", "细系"], ["B类", "粗系"], ["B类", "细系"],
            ["C类", "粗系"], ["C类", "细系"], ["D类", "粗系"], ["D类", "细系"],
            ["DS类"],
        ],
        [
            ["A类", "A类", "B类", "B类", "C类", "C类", "D类", "D类", "DS类"],
            ["粗系", "细系", "粗系", "细系", "粗系", "细系", "粗系", "细系", "DS类"],
            ["≤1.5", "≤1.5", "≤1.5", "≤1.5", "≤1.0", "≤1.0", "≤1.0", "≤1.0", "≤1.0"],
        ],
        header_rows=2,
    )
    assert classify_profile(grid) == "inspection"


def test_english_chemistry_table_is_not_admin() -> None:
    grid = _grid(
        "T3",
        "",
        [["Alloying Element"], ["Composition, % (Heat Analysis)"]],
        [
            ["Alloying Element", "Composition, % (Heat Analysis)"],
            ["Carbon, Max", "0.22"],
            ["Manganese, Max", "1.60"],
            ["Silicon", "0.15-0.35"],
        ],
    )
    assert classify_profile(grid) == "chemical_composition"


def test_conversion_appendix_is_not_extracted() -> None:
    grid = _grid(
        "T5",
        "表A.1 HRC3值与旧标准HRC值的对应关系",
        [["HRC3值"], ["HRC值"]],
        [["HRC3值", "HRC值"], ["31.5", "32"]],
        profile="mechanical_properties",
    )
    assert classify_profile(grid) == "admin"


def test_english_elements_and_properties() -> None:
    assert canonical_element("Carbon, Max") == "C"
    assert canonical_element("Manganese") == "Mn"
    assert _is_element_header("B类") is False
    assert _is_element_header("Si") is True
    assert canonical_property("Tensile strength (MPa)") == "Rm"
    assert canonical_property("Yield strength") == "Rp0.2"
    assert canonical_property("Elongation") == "A"
    assert canonical_property("Reduction of area") == "Z"


def test_cross_reference_noise_does_not_hijack_property() -> None:
    prefix = "经淬火回火(见表A.4)后试样的力学性能和硬度 "
    assert canonical_property(f"{prefix}规定非比例延伸强度Rp0.2/(N/mm2) 不小于") == "Rp0.2"
    assert canonical_property(f"{prefix}抗拉强度Rm/(N/mm2) 不小于") == "Rm"
    assert canonical_property(f"{prefix}断后伸长率A/% 不小于") == "A"
    assert canonical_property(f"{prefix}断面收缩率Zb/% 不小于") == "Z"
    assert canonical_property(f"{prefix}HBW 不小于") == "HB"


def test_english_item_classification() -> None:
    assert classify_item("Tensile strength")[0] == "tensile"
    assert classify_item("Hardness, HBW")[0] == "hardness"
    assert classify_item("Chemical composition")[0] == "chemical_composition"
    assert classify_item("Ultrasonic test")[0] == "ndt"


def test_property_row_matrix_is_extracted() -> None:
    grid = _grid(
        "T17",
        "表5 -3力学性能要求",
        [["性能"], ["室温"], ["350℃"], ["0℃"]],
        [
            ["性能", "室温", "350℃", "0℃"],
            ["抗拉强度Rm(MPa)", "760~960", "/", "/"],
            ["屈服强度Rp0.2(MPa)", "≥590", "≥490", "/"],
            ["断后伸长率A(%)", "≥15", "/", "/"],
            ["断面收缩率Z(%)", "≥50", "/", "/"],
            ["硬度(HBW)", "228~285", "/", "/"],
        ],
        profile="mechanical_properties",
    )
    output = extract_property_matrix(
        grid,
        DocumentMeta(doc_id="doc", source_path="x.pdf", file_name="x.pdf"),
    )
    assert output is not None
    by_key = {
        (record.properties[next(iter(record.properties))].raw, record.condition)
        for record in output.records
    }
    assert ("760~960", "室温") in by_key
    assert ("≥590", "室温") in by_key
    assert ("≥490", "350℃") in by_key
    tensile = next(
        record
        for record in output.records
        if next(iter(record.properties)) == "Rm"
    )
    value = tensile.properties["Rm"]
    assert value.unit == "MPa"
    assert value.comparator == "range"
    hardness = next(
        record
        for record in output.records
        if next(iter(record.properties)) == "HB"
    )
    assert hardness.properties["HB"].unit == "HB"


def test_test_requirement_matrix_supplies_requirements() -> None:
    tables = {
        "T3": {
            "table_id": "T3",
            "caption": "表1 盘前封严挡板力学性能测试条件和验收要求",
            "header_rows": 1,
            "header_paths": [
                ["测试类别"], ["位置"], ["试样数量"], ["测试条件"], ["验收指标"],
            ],
            "rows": [
                ["测试类别", "位置", "试样数量", "测试条件", "验收指标"],
                ["室温拉伸", "1", "1", "室温", "按**-0505-2004"],
                ["室温拉伸", "2", "1", "室温", "按**-0505-2004"],
                ["蠕变", "2", "1", "595℃、825MPa下进行50h蠕变试验",
                 "在25h试验后蠕变塑性伸长率不应超过0.2%"],
            ],
        }
    }
    assert _requirement_from_test_requirement_tables("室温拉伸", tables) == "按**-0505-2004"
    assert (
        _requirement_from_test_requirement_tables("蠕变", tables)
        == "在25h试验后蠕变塑性伸长率不应超过0.2%"
    )
    assert _requirement_from_test_requirement_tables("低周疲劳", tables) is None


def test_test_requirement_table_yields_items() -> None:
    grid = _grid(
        "T3",
        "表1 盘前封严挡板力学性能测试条件和验收要求",
        [["测试类别"], ["位置"], ["试样数量"], ["测试条件"], ["验收指标"]],
        [
            ["测试类别", "位置", "试样数量", "测试条件", "验收指标"],
            ["室温拉伸", "1", "1", "室温", "按**-0505-2004"],
            ["高温拉伸", "1", "1", "650℃", "按**-0505-2004"],
            ["蠕变", "2", "1", "595℃、825MPa", "≤0.2%"],
            ["光滑低周疲劳", "3", "2", "455℃", "≥10^5 次"],
        ],
        profile="inspection",
    )
    entries = _inspection_table_items(grid, None, [])
    assert [entry.item_raw for entry in entries] == [
        "室温拉伸",
        "高温拉伸",
        "蠕变",
        "光滑低周疲劳",
    ]
    assert entries[0].facets.get("sampling_quantity") == "1"
    assert entries[0].facets.get("sampling_position") == "1"


def test_fake_numeric_grades_are_rejected() -> None:
    assert _plausible_grade("4892") is False
    assert _plausible_grade("6219") is False
    assert _plausible_grade("4963") is False
    assert _plausible_grade("6061") is True
    assert _plausible_grade("7075") is True
    assert _plausible_grade("2A12") is True


def test_test_plan_table_is_inspection_and_not_a_matrix() -> None:
    grid = _grid(
        "T17",
        "表5 -2试验项目及试验方法",
        [
            ["检验项目", "拉伸试验"],
            ["试样状态", "调质"],
            ["取样方向", "纵向"],
            ["试验温度℃", "室温"],
            ["试验方法", "GB/T 228.1-2021"],
            ["试样数量", "详见取样附图"],
        ],
        [
            ["检验项目", "试样状态", "取样方向", "试验温度℃", "试验方法", "试样数量"],
            ["拉伸试验", "调质", "纵向", "室温", "GB/T 228.1-2021", "详见"],
            ["冲击试验", "调质", "纵向", "0", "GB/T 229-2007", "详见"],
        ],
        profile="mechanical_properties",
    )
    assert classify_profile(grid) == "inspection"
    assert (
        extract_property_matrix(
            grid,
            DocumentMeta(doc_id="doc", source_path="x.pdf", file_name="x.pdf"),
        )
        is None
    )


def test_english_chemistry_fallback_item() -> None:
    grid = _grid(
        "T3",
        "",
        [["Alloying Element"], ["Composition, % (Heat Analysis)"]],
        [
            ["Alloying Element", "Composition, % (Heat Analysis)"],
            ["Carbon, Max", "0.22"],
            ["Manganese, Max", "1.60"],
            ["Silicon", "0.15-0.35"],
            ["Nickel, Max", "1.00"],
        ],
        profile="chemical_composition",
    )
    entries = _profile_fallback_items(grid)
    assert len(entries) == 1
    assert entries[0].item_family == "chemical_composition"
    assert {"C", "Mn", "Si", "Ni"}.issubset(set(entries[0].properties))


def test_chemistry_fallback_resolves_footnote_element() -> None:
    grid = _grid(
        "T6",
        "表4-1化学成分要求(质量百分数 wt%)",
        [["元素"], ["熔炼分析"], ["成品分析"]],
        [
            ["元素", "熔炼分析", "成品分析"],
            ["C", "0.08~0.20", "0.06~0.22"],
            ["Na", "≤0.012", "≤0.017"],
            ["Nb", "≤0.020", "≤0.025"],
            ["注：a、总铝和氮元素含量的比值应满足Al:N≥2。",
             "注：a、总铝和氮元素含量的比值应满足Al:N≥2。",
             "注：a、总铝和氮元素含量的比值应满足Al:N≥2。"],
        ],
        profile="chemical_composition",
    )
    entries = _profile_fallback_items(grid)
    assert len(entries) == 1
    properties = entries[0].properties
    assert "N" in properties
    assert "Na" not in properties


def test_english_mechanical_fallback_item() -> None:
    grid = _grid(
        "T10",
        "",
        [["Hardness"], ["HBW"]],
        [["Hardness", "HBW"], ["Hardness, max", "174"]],
        profile="mechanical_properties",
    )
    entries = _profile_fallback_items(grid)
    assert len(entries) == 1
    assert entries[0].item_family == "hardness"
    assert entries[0].properties == ["HB"]


def test_english_element_key_value_matrix() -> None:
    grid = _grid(
        "T3",
        "",
        [["Alloying Element"], ["Composition, % (Heat Analysis)"]],
        [
            ["Alloying Element", "Composition, % (Heat Analysis)"],
            ["Carbon, Max", "0.22"],
            ["Manganese, Max", "1.60"],
            ["Phosphorous, Max", "Refer Table 1A"],
            ["Silicon", "0.15-0.35"],
            ["Nickel, Max", "1.00**"],
        ],
        profile="chemical_composition",
    )
    output = extract_element_matrix(
        grid,
        DocumentMeta(doc_id="doc", source_path="x.pdf", file_name="x.pdf"),
    )
    assert output is not None
    by_element = {
        next(iter(record.properties)): record.properties[
            next(iter(record.properties))
        ]
        for record in output.records
    }
    # A "Refer Table 1A" pointer is a text requirement, not a missing limit.
    assert set(by_element) == {"C", "Mn", "P", "Si", "Ni"}
    assert by_element["C"].comparator == "max"
    assert by_element["C"].unit == "%"
    assert by_element["Si"].comparator == "range"
    assert by_element["Ni"].raw == "1.00"
    assert by_element["P"].comparator == "text"
    assert by_element["P"].text == "Refer Table 1A"


def test_iso_element_values_with_decimal_commas_and_remainder() -> None:
    grid = _grid(
        "T1",
        "",
        [["Element"], ["Compositional limits mass fraction%"]],
        [
            ["Element", "Compositional limits mass fraction%"],
            ["Aluminium", "5,5 to 6,75"],
            ["Iron", "0,3 max."],
            ["Nitrogen", "0.05(500ppm)"],
            ["Titanium", "remainder"],
        ],
        profile="chemical_composition",
    )
    output = extract_element_matrix(
        grid,
        DocumentMeta(doc_id="doc", source_path="x.pdf", file_name="x.pdf"),
    )
    assert output is not None
    by_element = {
        next(iter(record.properties)): record.properties[
            next(iter(record.properties))
        ]
        for record in output.records
    }
    assert by_element["Al"].comparator == "range"
    assert (by_element["Al"].lower, by_element["Al"].upper) == (5.5, 6.75)
    assert by_element["Fe"].comparator == "max"
    assert by_element["Fe"].value == 0.3
    assert by_element["N"].value == 0.05
    assert by_element["Ti"].comparator == "text"
    assert by_element["Ti"].text == "余量"


def test_astm_grade_row_chemistry_is_extracted() -> None:
    grid = _grid(
        "T1",
        "",
        [
            ["Grade"], ["Carbon max."], ["Manganese, Max"], ["Silicon"],
            ["Iron range or max."], ["Titanium"],
        ],
        [
            ["Grade", "Carbon max.", "Manganese, Max", "Silicon",
             "Iron range or max.", "Titanium"],
            ["32", "0.08", "0.5", "0.1", "0.25", "remainder"],
            ["33", "0.08", "0.3", "0.1", "0.30", "-"],
        ],
        profile="chemical_composition",
    )
    output = extract_element_matrix(
        grid,
        DocumentMeta(doc_id="doc", source_path="x.pdf", file_name="x.pdf"),
    )
    assert output is not None
    record = next(row for row in output.records if row.grade == "32")
    assert set(record.properties) == {"C", "Mn", "Si", "Fe", "Ti"}
    assert record.properties["C"].comparator == "max"
    assert record.properties["C"].value == 0.08
    assert record.properties["Ti"].text == "余量"


def test_astm_grade_row_mechanical_prefers_mpa() -> None:
    grid = _grid(
        "T3",
        "",
        [
            ["Grade"],
            ["Tensile Strength,min", "ksi"],
            ["Tensile Strength,min", "MPa"],
            ["Elongation in 4D, min, %"],
            ["Reduction of Area, min %"],
            ["Hardness, max"],
        ],
        [
            ["Grade", "Tensile Strength,min", "Tensile Strength,min",
             "Elongation in 4D, min, %", "Reduction of Area, min %",
             "Hardness, max"],
            ["Grade", "ksi", "MPa", "Elongation in 4D, min, %",
             "Reduction of Area, min %", "Hardness, max"],
            ["1", "35", "240", "24", "30", "187"],
        ],
        profile="mechanical_properties",
        header_rows=2,
    )
    output = extract_grade_property_matrix(
        grid,
        DocumentMeta(doc_id="doc", source_path="x.pdf", file_name="x.pdf"),
    )
    assert output is not None
    record = output.records[0]
    assert record.grade == "1"
    assert record.properties["Rm"].unit == "MPa"
    assert record.properties["Rm"].value == 240
    assert record.properties["Rm"].comparator == "min"
    assert record.properties["A"].value == 24
    assert record.properties["A"].unit == "%"
    assert record.properties["Z"].value == 30
    assert record.properties["HB"].comparator == "max"
    assert record.properties["HB"].value == 187


def test_ams_property_value_rows() -> None:
    grid = _grid(
        "T3",
        "",
        [["Property"], ["Value"]],
        [
            ["Property", "Value"],
            ["Tensile Strength, Minimum", "80 ksi(552 MPa)"],
            ["Yield Strength at 0.2% Offset", "70 to 95 ksi(483 to 655 MPa)"],
            ["Elongation in 2 Inches(50.8 mm) or 4D, Minimum", "15%"],
        ],
        profile="mechanical_properties",
    )
    output = extract_property_rows(
        grid,
        DocumentMeta(doc_id="doc", source_path="x.pdf", file_name="x.pdf"),
    )
    assert output is not None
    by_prop = {
        next(iter(record.properties)): record.properties[
            next(iter(record.properties))
        ]
        for record in output.records
    }
    assert by_prop["Rm"].unit == "MPa"
    assert by_prop["Rm"].value == 552
    assert by_prop["Rm"].comparator == "min"
    assert by_prop["Rp0.2"].comparator == "range"
    assert (by_prop["Rp0.2"].lower, by_prop["Rp0.2"].upper) == (483, 655)
    assert by_prop["A"].value == 15
    assert by_prop["A"].unit == "%"


def test_element_and_content_row_pairs_are_extracted() -> None:
    grid = _grid(
        "T2",
        "表2 化学成分",
        [["元素"], ["C"], ["Mn"], ["Si"], ["Ni"], ["Fe"]],
        [
            ["元素", "C", "Mn", "Si", "Ni", "Fe"],
            ["含量", "≤0.08", "≤0.35", "≤0.35", "-", "-"],
            ["元素", "Ni", "Mo", "Nb", "Ti", "Fe"],
            ["含量", "50.0~55.0", "2.80~3.30", "4.75~5.50", "0.65~1.15", "余量"],
        ],
        profile="chemical_composition",
    )
    output = extract_element_matrix(
        grid,
        DocumentMeta(doc_id="doc", source_path="x.pdf", file_name="x.pdf"),
    )
    assert output is not None
    by_element = {
        next(iter(record.properties)): record.properties[
            next(iter(record.properties))
        ]
        for record in output.records
    }
    assert by_element["C"].comparator == "max"
    assert by_element["Ni"].comparator == "range"
    assert (by_element["Ni"].lower, by_element["Ni"].upper) == (50.0, 55.0)
    assert by_element["Fe"].comparator == "text"
    assert by_element["Fe"].text == "余量"
