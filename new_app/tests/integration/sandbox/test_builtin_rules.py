from __future__ import annotations

from services.sandbox.runtime.builtin import (
    _detect_measure,
    _disambiguate_duplicate_keys,
    _document_grade_hint,
    _drop_orphan_records,
    _element_symbol,
    _extract_unit,
    _header_grade,
    _header_operator,
    _header_columns,
    _merge_fragments,
    _parse_value,
    apply_document_metadata,
    parse_table,
)


def test_english_element_names_with_limit_qualifiers() -> None:
    assert _element_symbol("Carbon, max.") == "C"
    assert _element_symbol("Iron range or max.") == "Fe"
    assert _element_symbol("Nitrogen, max.") == "N"
    assert _element_symbol("Molybdenum") == "Mo"


def test_hyphen_range_sets_range_operator() -> None:
    parsed = _parse_value("0.20-0.80", True)
    assert parsed == {"value": 0.2, "raw": "0.20-0.80", "operator": "~"}
    assert _parse_value("-0.01", True)["operator"] is None


def test_chemical_columns_apply_english_limit_headers() -> None:
    table = {
        "table_id": "T9",
        "page_no": 1,
        "header_rows": 1,
        "header_paths": [
            ["Grade"],
            ["Carbon, max."],
            ["Manganese, max."],
            ["Silicon, max."],
        ],
        "n_cols": 4,
        "rows": [
            ["Grade", "Carbon, max.", "Manganese, max.", "Silicon, max."],
            ["12", "0.08", "0.10", "0.20"],
        ],
        "units": [],
    }
    records, _, _ = parse_table(table, CHEMICAL, None, [])
    assert records
    props = records[0]["properties"]
    assert props["C"]["raw"] == "0.08"
    assert props["C"]["operator"] == "≤"
    assert props["Mn"]["operator"] == "≤"


CHEMICAL = {
    "recipe_id": "chemical_composition_v1",
    "version": "1.1.0",
    "profile": "chemical_composition",
    "bindings": {
        "row_key": ["牌号"],
        "measures": {
            "C": {"unit": "%"},
            "Si": {"unit": "%"},
            "Mn": {"unit": "%"},
            "P": {"unit": "%"},
            "S": {"unit": "%"},
            "Cr": {"unit": "%"},
            "Fe": {"unit": "%"},
        },
    },
    "rules": {"strip_footnote_marks": True},
}

MECHANICAL = {
    "recipe_id": "mechanical_properties_v1",
    "version": "1.1.0",
    "profile": "mechanical_properties",
    "bindings": {
        "row_key": ["牌号"],
        "measures": {
            "Rm": {"unit": "MPa"},
            "Rp0.2": {"unit": "MPa"},
            "A": {"unit": "%"},
            "KU2": {"unit": "J"},
            "HB": {"unit": "HBW"},
            "E": {"unit": "GPa"},
            "侧向膨胀值": {"unit": "mm"},
            "持久应力": {"unit": "MPa"},
        },
    },
    "rules": {"strip_footnote_marks": True},
}


def _table(headers: list[str], rows: list[list[str]], **extra) -> dict:
    return {
        "table_id": "T1",
        "page_no": 1,
        "header_rows": 1,
        "header_paths": [[header] for header in headers],
        "n_cols": len(headers),
        "rows": [headers, *rows],
        "units": [],
        **extra,
    }


def test_grouped_other_elements_and_palladium_columns() -> None:
    """GB/T 14845 表2：Pd 与“其他元素/单一|总和”分组表头必须成项。"""
    manifest = {
        "recipe_id": "chemical_composition_v1",
        "version": "1.1.217",
        "profile": "chemical_composition",
        "bindings": {
            "row_key": ["牌号"],
            "measures": {
                "Ti": {"unit": "%"},
                "Pd": {"unit": "%"},
                "Fe": {"unit": "%"},
                "C": {"unit": "%"},
                "N": {"unit": "%"},
                "H": {"unit": "%"},
                "O": {"unit": "%"},
                "其他元素（单一）": {"unit": "%", "aliases": ["其他元素/单一"]},
                "其他元素（总和）": {"unit": "%", "aliases": ["其他元素/总和"]},
            },
        },
        "rules": {"strip_footnote_marks": True},
    }
    table = {
        "table_id": "T2",
        "page_no": 6,
        "header_rows": 3,
        "header_paths": [
            ["牌号"],
            ["主要成分(质量分数)", "Ti"],
            ["主要成分(质量分数)", "Pd"],
            ["杂质(质量分数),不大于", "Fe"],
            ["杂质(质量分数),不大于", "C"],
            ["杂质(质量分数),不大于", "N"],
            ["杂质(质量分数),不大于", "H"],
            ["杂质(质量分数),不大于", "O"],
            ["杂质(质量分数),不大于", "其他元素", "单一"],
            ["杂质(质量分数),不大于", "其他元素", "总和"],
        ],
        "n_cols": 10,
        "rows": [
            [
                "牌号", "主要成分(质量分数)", "主要成分(质量分数)",
                "杂质(质量分数),不大于", "杂质(质量分数),不大于",
                "杂质(质量分数),不大于", "杂质(质量分数),不大于",
                "杂质(质量分数),不大于", "杂质(质量分数),不大于", "",
            ],
            [
                "牌号", "Ti", "Pd", "Fe", "C", "N", "H", "O",
                "其他元素", "其他元素",
            ],
            [
                "牌号", "Ti", "Pd", "Fe", "C", "N", "H", "O",
                "单一", "总和",
            ],
            [
                "TA8-1", "余量", "0.04~0.08", "0.15", "0.04", "0.02",
                "0.012", "0.18", "0.10", "0.40",
            ],
        ],
        "units": [],
    }
    records, _, _ = parse_table(table, manifest, None, [])
    assert records and records[0]["grade"] == "TA8-1"
    properties = records[0]["properties"]
    assert properties["Pd"]["raw"] == "0.04~0.08"
    assert properties["其他元素（单一）"]["raw"] == "0.10"
    assert properties["其他元素（总和）"]["raw"] == "0.40"
    assert properties["其他元素（单一）"]["unit"] == "%"


def test_single_letter_elements_match_exact_columns() -> None:
    table = _table(
        ["牌号", "C", "Si", "Mn", "P", "S", "Cr", "Ni"],
        [["Q355B", "0.18", "0.35", "1.40", "0.020", "0.010", "0.20", "0.30"]],
    )
    records, _, _ = parse_table(table, CHEMICAL, None, [])
    properties = records[0]["properties"]
    assert properties["C"]["value"] == 0.18
    assert properties["P"]["value"] == 0.02
    assert properties["S"]["value"] == 0.01
    # ``C`` must not consume the ``Cr`` column.
    assert properties["Cr"]["value"] == 0.2
    assert "Ni" not in properties


def test_merged_condition_cells_are_carried_forward() -> None:
    """Merged 状态/厚度 cells must not collapse rows into duplicate keys."""
    table = _table(
        ["牌号", "供应状态", "厚度mm", "Rm", "A"],
        [
            ["3105", "H14", ">0.20~0.50", "180", "2"],
            ["3105", "", ">0.50~1.50", "170", "3"],
            ["3105", "H24", ">0.20~0.50", "190", "4"],
        ],
    )
    records, _, _ = parse_table(table, MECHANICAL, None, [])
    assert len(records) == 3
    assert "H14" in records[1]["conditions"].values()
    assert len({record["condition_key"] for record in records}) == 3


def test_header_symbol_overrides_recipe_binding() -> None:
    table = _table(
        ["牌号", "Rm", "A", "KV2", "HBW"],
        [["Q355B", "470", "22", "34", "170"]],
    )
    records, _, _ = parse_table(table, MECHANICAL, None, [])
    properties = records[0]["properties"]
    assert properties["Rm"]["value"] == 470
    assert properties["A"]["value"] == 22
    assert properties["KV2"]["value"] == 34
    assert "KU2" not in properties
    # Brinell hardness is one measure; HBW is recorded as its unit.
    assert properties["HB"]["value"] == 170
    assert properties["HB"]["unit"] == "HBW"
    assert "HBW" not in properties


def test_sentence_like_row_keys_are_rejected() -> None:
    table = _table(
        ["牌号", "Rm"],
        [
            ["Q355B", "470"],
            ["注：表中数据为最小值。", "400"],
            ["在同一温度下，持久试验首次试验按高应力组数据进行。", "500"],
        ],
    )
    records, _, _ = parse_table(table, MECHANICAL, None, [])
    assert [record["grade"] for record in records] == ["Q355B"]


def test_transposed_element_rows_become_condition_records() -> None:
    manifest = {
        "recipe_id": "chemical_element_rows_v1",
        "version": "1.1.0",
        "profile": "chemical_composition",
        "bindings": {"row_key": ["元素"]},
        "rules": {"transposed": True, "strip_footnote_marks": True},
    }
    table = _table(
        ["元素", "熔炼分析", "成品分析"],
        [["C", "≤0.20", "≤0.22"], ["Mn", "1.15-1.60", "1.15-1.60"]],
    )
    records, evidence, _ = parse_table(table, manifest, None, [])
    assert len(records) == 2
    assert all(record["grade"] == "~" for record in records)
    assert records[0]["conditions"]["依据"] == "熔炼分析"
    assert records[0]["properties"]["C"]["value"] == 0.2
    assert records[1]["conditions"]["依据"] == "成品分析"
    assert records[1]["properties"]["Mn"]["raw"] == "1.15-1.60"
    assert len(evidence) == 2


def test_transposed_element_rows_with_merged_grade_label() -> None:
    manifest = {
        "recipe_id": "chemical_element_rows_v1",
        "version": "1.2.9",
        "profile": "chemical_composition",
        "bindings": {"row_key": ["元素"]},
        "rules": {"transposed": True, "strip_footnote_marks": True},
    }
    table = _table(
        ["牌号", "牌号", "Co9998", "Co9995", ""],
        [
            ["化学成分/%", "Co不小于", "Co不小于", "99.98", "99.95"],
            ["化学成分/%", "杂质含量不大于", "C", "0.004", "0.005"],
            ["化学成分/%", "杂质含量不大于", "S", "0.001", "0.002"],
            ["化学成分/%", "杂质含量不大于", "Mn", "0.001", "0.008"],
        ],
    )
    records, _, _ = parse_table(table, manifest, None, [])
    assert [record["grade"] for record in records] == ["Co9998", "Co9995"]
    assert records[0]["properties"]["C"]["value"] == 0.004
    assert records[1]["properties"]["Mn"]["value"] == 0.008
    assert records[0]["properties"]["Co"]["value"] == 99.98


def test_english_element_names_are_mapped_to_symbols() -> None:
    manifest = {
        "recipe_id": "chemical_element_rows_v1",
        "version": "1.2.3",
        "profile": "chemical_composition",
        "bindings": {"row_key": ["Element"]},
        "rules": {"transposed": True, "strip_footnote_marks": True},
    }
    table = _table(
        ["Element", "Min", "Max"],
        [
            ["Silicon", "—", "0.12"],
            ["Iron", "—", "0.15"],
            ["Copper", "2.0", "2.6"],
            ["Manganese", "—", "0.10"],
            ["Magnesium", "1.9", "2.6"],
            ["Zirconium", "0.08", "0.15"],
            ["Aluminum", "remainder", ""],
        ],
    )
    records, _, _ = parse_table(table, manifest, None, [])
    # Min/Max 合并为区间/上限语义（AMS Element/Min/Max 规则）。
    assert len(records) == 1
    properties = records[0]["properties"]
    assert properties["Cu"]["value"] == 2.0
    assert properties["Cu"]["raw"] == "2.0~2.6"
    assert properties["Mg"]["value"] == 1.9
    assert properties["Mg"]["raw"] == "1.9~2.6"
    assert properties["Fe"]["raw"] == "≤0.15"
    assert properties["Mn"]["raw"] == "≤0.10"
    assert properties["Zr"]["raw"] == "0.08~0.15"
    # Copper 必须映射为 Cu，不能按首字母启发式误判为 Co（钴）。
    assert "Co" not in properties
    # remainder 不是数值，不能进入属性。
    assert "Al" not in properties


def test_element_columns_layout_produces_one_record_per_row() -> None:
    manifest = {
        "recipe_id": "chemical_element_rows_v1",
        "version": "1.1.0",
        "profile": "chemical_composition",
        "bindings": {"row_key": ["元素"]},
        "rules": {"transposed": True, "strip_footnote_marks": True},
    }
    table = _table(
        ["元素", "C", "Si", "Mn"],
        [["标准", "≤0.05", "≤0.5", "≤1.0"]],
    )
    records, _, _ = parse_table(table, manifest, None, [])
    assert len(records) == 1
    assert records[0]["conditions"]["依据"] == "标准"
    assert records[0]["properties"]["C"]["value"] == 0.05
    assert records[0]["properties"]["Mn"]["value"] == 1.0


def test_grade_less_chemical_table_gets_synthetic_record() -> None:
    table = _table(
        ["主要成分%/Al", "主要成分%/V", "杂质合金不大于%/Fe", "杂质合金不大于%/C"],
        [["5.5~6.8", "3.5~4.5", "0.30", "0.10"]],
    )
    records, evidence, _ = parse_table(table, CHEMICAL, None, [])
    assert len(records) == 1
    assert records[0]["grade"] == "~"
    assert records[0]["properties"]["Al"]["value"] == 5.5
    assert records[0]["properties"]["C"]["value"] == 0.1
    assert len(evidence) == 1


def test_numeric_grades_use_material_column() -> None:
    table = _table(
        ["抗拉强度Rm/MPa", "参考硬度(HB)", "常用材料"],
        [["470", "120", "45"], ["400", "110", "-"], ["520", "150", "35"]],
    )
    records, _, _ = parse_table(table, MECHANICAL, None, [])
    assert [record["grade"] for record in records] == ["45", "35"]
    assert records[0]["properties"]["Rm"]["value"] == 470
    assert records[0]["properties"]["HB"]["value"] == 120


def test_negative_composition_values_are_ignored() -> None:
    table = _table(
        ["牌号", "C", "Cr"],
        [["Q355B", "-0.01", "-0.15"]],
    )
    records, _, _ = parse_table(table, CHEMICAL, None, [])
    assert records == []


def test_merged_grades_are_split_by_separators() -> None:
    table = _table(
        ["牌号", "Rm"],
        [["Q355M、Q390M、Q420M", "470"], ["20、25", "410"]],
    )
    records, _, _ = parse_table(table, MECHANICAL, None, [])
    assert [record["grade"] for record in records] == [
        "Q355M",
        "Q390M",
        "Q420M",
        "20",
        "25",
    ]
    assert records[0]["grade_raw"] == "Q355M、Q390M、Q420M"
    assert records[0]["condition_key"] == ""


def test_english_mechanical_headers_are_supported() -> None:
    table = _table(
        [
            "Temper",
            "Tensile Strength, minimum ksi",
            "Yield Strength at 0.2 percent Offset, minimum ksi",
            "Elongation in 2 in., minimum Percent",
        ],
        [["T3", "60", "50", "10"]],
    )
    records, _, _ = parse_table(table, MECHANICAL, None, [])
    assert len(records) == 1
    assert records[0]["grade"] == "T3"
    properties = records[0]["properties"]
    assert properties["Rm"]["value"] == 60
    assert properties["Rm"]["unit"] == "ksi"
    assert properties["Rp0.2"]["value"] == 50
    assert properties["A"]["value"] == 10
    assert properties["A"]["unit"] == "%"


def test_merged_cell_footnote_markers_are_removed_from_grades() -> None:
    table = _table(
        ["Temper", "Tensile Strength, minimum ksi"],
        [
            ["T3 4/\n(See 6.4)", "60"],
            ["T851 (See 6.4)", "67"],
            ["T361 6/", "68"],
        ],
    )
    records, _, _ = parse_table(table, MECHANICAL, None, [])
    assert [record["grade"] for record in records] == ["T3", "T851", "T361"]


def test_section_header_and_title_rows_are_rejected() -> None:
    table = _table(
        ["牌号", "Rm"],
        [
            ["结 梅 钢", "400"],
            ["不 锈 钢 及 耐 热 钢", "410"],
            ["ISO 5832-3 + ASTM F136-13", "420"],
            ["F1472-", "430"],
            ["Q355B", "470"],
        ],
    )
    records, _, _ = parse_table(table, MECHANICAL, None, [])
    assert [record["grade"] for record in records] == ["Q355B"]


def test_legacy_measure_aliases_are_supported() -> None:
    table = _table(
        ["牌号", "弹性模量", "持久应力", "侧向膨胀值"],
        [["Q355B", "206", "180", "0.5"]],
    )
    records, _, _ = parse_table(table, MECHANICAL, None, [])
    properties = records[0]["properties"]
    assert properties["E"]["value"] == 206
    assert properties["E"]["unit"] == "GPa"
    assert properties["持久应力"]["value"] == 180
    assert properties["侧向膨胀值"]["value"] == 0.5


def test_condition_fallback_binds_delivery_state() -> None:
    table = _table(
        ["牌号", "交货状态", "Rm"],
        [["Q355B", "正火", "470"]],
    )
    records, _, _ = parse_table(table, MECHANICAL, None, [])
    assert records[0]["conditions"] == {"交货状态": "正火"}
    assert records[0]["condition_key"] == "正火"


def test_transposed_element_units_use_recipe_bindings() -> None:
    manifest = {
        "recipe_id": "chemical_element_rows_v1",
        "version": "1.1.0",
        "profile": "chemical_composition",
        "bindings": {
            "row_key": ["元素"],
            "measures": {"C": {"unit": "%"}, "Ni": {"unit": "%"}},
        },
        "rules": {"transposed": True, "strip_footnote_marks": True},
    }
    table = _table(
        ["元素", "牌号A"],
        [["C", "0.05"], ["Ni", "0.03"]],
    )
    records, _, _ = parse_table(table, manifest, None, [])
    assert records[0]["properties"]["C"]["unit"] == "%"
    assert records[0]["properties"]["Ni"]["unit"] == "%"
    assert records[0]["properties"]["Ni"]["value"] == 0.03


def test_transposed_element_table_defaults_to_percent_unit() -> None:
    manifest = {
        "recipe_id": "chemical_element_rows_v1",
        "version": "1.1.0",
        "profile": "chemical_composition",
        "bindings": {"row_key": ["元素"], "measures": {}},
        "rules": {"transposed": True, "strip_footnote_marks": True},
    }
    table = _table(
        ["元素", "牌号A"],
        [["Ca", "0.08"], ["Ni", "0.03"]],
    )
    records, _, _ = parse_table(table, manifest, None, [])
    assert records[0]["properties"]["Ca"]["unit"] == "%"
    assert records[0]["properties"]["Ni"]["unit"] == "%"


def test_dimension_column_is_condition_not_grade() -> None:
    table = _table(
        ["Nominal Thickness Millimeters", "Tensile Strength MPa"],
        [["Over 51.00 to 76.00, incl", "503"]],
    )
    records, _, _ = parse_table(table, MECHANICAL, None, [])
    assert len(records) == 1
    assert records[0]["grade"] == "~"
    assert records[0]["conditions"]["规格"] == "Over 51.00 to 76.00, incl"
    assert records[0]["properties"]["Rm"]["value"] == 503


def test_english_thickness_and_orientation_are_conditions() -> None:
    table = _table(
        [
            "Nominal Thickness Millimeters",
            "Nominal Thickness Millimeters",
            "Specimen Orientation",
            "Tensile Strength MPa",
        ],
        [["Over", "51.00 to 76.00, incl", "Longitudinal", "503"]],
    )
    records, _, _ = parse_table(table, MECHANICAL, None, [])
    assert len(records) == 1
    assert records[0]["grade"] == "~"
    assert records[0]["conditions"]["规格"] == "Over 51.00 to 76.00, incl"
    assert records[0]["conditions"]["方向"] == "Longitudinal"
    assert records[0]["properties"]["Rm"]["value"] == 503


def test_duplicate_table_is_parsed_once() -> None:
    table = _table(["牌号", "Rm", "A"], [["Q355B", "470", "22"]])
    diagnostics: list[dict] = []
    first, _, _ = parse_table(dict(table), MECHANICAL, None, diagnostics)
    second, _, _ = parse_table(
        dict(table, table_id="T2"), MECHANICAL, None, diagnostics
    )
    assert first
    assert second == []
    assert any(item["code"] == "DUPLICATE_TABLE" for item in diagnostics)


def test_element_labels_are_not_parsed_as_values() -> None:
    manifest = {
        "recipe_id": "chemical_element_rows_v1",
        "version": "1.1.0",
        "profile": "chemical_composition",
        "bindings": {"row_key": ["元素"]},
        "rules": {"transposed": True, "strip_footnote_marks": True},
    }
    table = _table(
        ["元素", "C", "Mn"],
        [["含量", "0.20", "1.40"], ["元素", "Si", "P"]],
    )
    records, _, _ = parse_table(table, manifest, None, [])
    assert len(records) == 1
    assert records[0]["properties"]["C"]["value"] == 0.2


def test_duplicate_expanded_header_columns_are_collapsed() -> None:
    """OCR 把合并表头展开成重复列时，不应造成元素整体错位。"""
    table = {
        "table_id": "T1",
        "page_no": 1,
        "header_rows": 3,
        "header_paths": [
            ["牌号", "钢级"],
            ["牌号", "质量等级"],
            ["化学成分", "C"],
            ["化学成分", "C"],
            ["化学成分", "Si"],
            ["化学成分", "Mn"],
        ],
        "n_cols": 6,
        "rows": [
            ["牌号", "牌号", "化学成分", "化学成分", "化学成分", "化学成分"],
            ["钢级", "质量等级", "C", "C", "Si", "Mn"],
            ["钢级", "质量等级", "不大于", "不大于", "不大于", "不大于"],
            ["Q355", "B", "0.20", "0.20", "0.55", "1.60"],
        ],
        "units": ["%"],
    }
    records, _, _ = parse_table(table, CHEMICAL, None, [])
    assert len(records) == 1
    record = records[0]
    assert record["grade"] == "Q355B"
    properties = record["properties"]
    assert properties["C"]["value"] == 0.2
    assert properties["Si"]["value"] == 0.55
    assert properties["Mn"]["value"] == 1.6


def test_truncated_unit_in_header_is_completed() -> None:
    """列宽截断把 MPa 切成 “/MP” 时仍要识别为 MPa。"""
    table = _table(
        ["牌号", "抗拉强度 Rm/MP", "上屈服强度 ReH/MP"],
        [["Q355B", "470", "355"]],
    )
    records, _, _ = parse_table(table, MECHANICAL, None, [])
    properties = records[0]["properties"]
    assert properties["Rm"]["unit"] == "MPa"
    assert properties["Rm"]["value"] == 470
    assert properties["ReH"]["unit"] == "MPa"


def test_footnote_sentence_grade_is_rejected() -> None:
    table = _table(
        ["牌号", "Rm"],
        [["SMLS,非冷扩径[见API Spec 5L:2018中图5a)]", "470"]],
    )
    records, _, _ = parse_table(table, MECHANICAL, None, [])
    assert records == []


def test_printed_symbol_wins_over_shared_alias() -> None:
    manifest = {
        "recipe_id": "mechanical_properties_v1",
        "version": "1.5.0",
        "profile": "mechanical_properties",
        "bindings": {
            "row_key": ["牌号"],
            "measures": {"KU2": {"unit": "J"}, "KV2": {"unit": "J"}},
        },
        "rules": {"strip_footnote_marks": True},
    }
    table = _table(
        ["牌号", "冲击吸收能量(KV2)J"],
        [["20G", "27"]],
    )
    records, _, _ = parse_table(table, manifest, None, [])
    assert len(records) == 1
    assert set(records[0]["properties"]) == {"KV2"}
    assert records[0]["properties"]["KV2"]["value"] == 27.0


def test_measure_in_group_title_binds_via_fallback() -> None:
    manifest = {
        "recipe_id": "chemical_composition_v1",
        "version": "1.1.0",
        "profile": "chemical_composition",
        "bindings": {
            "row_key": ["钢级"],
            "measures": {"C": {"unit": "%"}, "CEV": {"unit": "%"}},
        },
        "rules": {"strip_footnote_marks": True},
    }
    table = {
        "table_id": "T10",
        "page_no": 1,
        "header_rows": 1,
        "header_paths": [
            ["钢级", "无缝管和焊管"],
            ["基于熔炼分析的质量分数 %", "最大", "C", "无缝管和焊管"],
            ["碳当量 %", "最大", "CEPcm", "无缝管和焊管"],
        ],
        "n_cols": 3,
        "rows": [
            ["钢级", "C", "CEPcm"],
            ["L245NH/BH", "0.16", "0.43"],
        ],
        "units": [],
    }
    records, _, _ = parse_table(table, manifest, None, [])
    assert len(records) == 1
    assert records[0]["properties"]["C"]["value"] == 0.16
    assert records[0]["properties"]["CEV"]["value"] == 0.43


def test_repeated_measure_groups_become_extra_records() -> None:
    table = {
        "table_id": "T6",
        "page_no": 1,
        "header_rows": 1,
        "header_paths": [
            ["牌号"],
            ["室温拉伸试验", "抗拉强度Rm/MPa"],
            ["350℃拉伸试验", "抗拉强度Rm/MPa"],
        ],
        "n_cols": 3,
        "rows": [
            ["牌号", "室温拉伸试验", "350℃拉伸试验"],
            ["抗拉强度Rm/MPa", "抗拉强度Rm/MPa", ""],
            ["06Cr19Ni10", "≥520", "≥394"],
        ],
        "units": [],
    }
    records, _, _ = parse_table(table, MECHANICAL, None, [])
    values = {record["properties"]["Rm"]["value"] for record in records}
    assert values == {520.0, 394.0}
    extra = [record for record in records if record["conditions"].get("温度")]
    assert extra and extra[0]["conditions"]["温度"] == "350℃拉伸试验"


TRANSPOSED_CHEMICAL = {
    "recipe_id": "chemical_element_rows_v1",
    "version": "1.2.0",
    "profile": "chemical_composition",
    "bindings": {"row_key": ["元素"], "conditions": ["牌号"], "measures": {}},
    "rules": {"transposed": True, "strip_footnote_marks": True},
}


def test_transposed_recipe_does_not_fire_on_grade_row_table() -> None:
    """板式化学成分表被误配成转置配方时，仍按牌号行解析而不是产出“~”记录。"""
    table = {
        "table_id": "T1",
        "page_no": 7,
        "header_rows": 1,
        "header_paths": [
            ["钢组"],
            ["序号"],
            ["统一数字代号"],
            ["牌号"],
            ["化学成分(质量分数)/%", "C"],
            ["化学成分(质量分数)/%", "Si"],
            ["化学成分(质量分数)/%", "Mn"],
        ],
        "n_cols": 7,
        "rows": [
            ["钢组", "序号", "统一数字代号", "牌号", "C", "Si", "Mn"],
            ["Mn", "1", "A00202", "20Mn2", "0.17~0.24", "0.17~0.37", "1.40~1.80"],
            ["Mn", "2", "A00302", "30Mn2", "0.27~0.34", "0.17~0.37", "1.40~1.80"],
            ["SiMn", "8", "A10272", "27SiMn", "0.24~0.32", "1.10~1.40", "1.10~1.40"],
        ],
        "units": ["%"],
    }
    records, _, _ = parse_table(table, TRANSPOSED_CHEMICAL, None, [])
    grades = [record["grade"] for record in records]
    assert "~" not in grades
    assert grades == ["20Mn2", "30Mn2", "27SiMn"]
    first = records[0]["properties"]
    assert first["C"]["raw"] == "0.17~0.24"
    assert first["Mn"]["unit"] == "%"


def test_unbound_element_columns_fall_back_to_row_records_with_grade() -> None:
    """配方未绑定元素度量时，元素列仍按行成记录，并保留真实牌号。"""
    table = {
        "table_id": "T2",
        "page_no": 8,
        "header_rows": 1,
        "header_paths": [
            ["牌号"],
            ["C"],
            ["Si"],
            ["Mn"],
            ["P"],
        ],
        "n_cols": 5,
        "rows": [
            ["牌号", "C", "Si", "Mn", "P"],
            ["022Cr17Ni12Mo2", "0.030", "0.75", "2.00", "0.045"],
            ["06Cr19Ni10", "0.045", "0.75", "2.00", "0.045"],
        ],
        "units": ["%"],
    }
    manifest = {
        "recipe_id": "chemical_element_rows_v1",
        "version": "1.2.0",
        "profile": "chemical_composition",
        "bindings": {"row_key": ["牌号"], "measures": {}},
        "rules": {"strip_footnote_marks": True},
    }
    records, _, _ = parse_table(table, manifest, None, [])
    assert [record["grade"] for record in records] == ["022Cr17Ni12Mo2", "06Cr19Ni10"]
    assert records[0]["properties"]["C"]["value"] == 0.03
    assert all(record["properties"]["C"]["unit"] == "%" for record in records)


def test_merged_grade_cell_is_forward_filled() -> None:
    """牌号列纵向合并时，续行沿用上一行牌号，而不是留空被丢弃。"""
    table = _table(
        ["牌号", "Rm", "A"],
        [
            ["20CrMnTi", "1080", "10"],
            ["", "980", "9"],
            ["", "880", "8"],
        ],
    )
    diagnostics: list[dict] = []
    records, _, _ = parse_table(table, MECHANICAL, None, diagnostics)
    assert [record["grade"] for record in records] == ["20CrMnTi"] * 3
    filled = [
        item for item in diagnostics if item["code"] == "MERGED_GRADE_FILLED"
    ]
    assert filled and filled[0]["detail"]["filled"] == 2


def test_merged_grade_fill_requires_existing_grade_column() -> None:
    """没有牌号列的表不能凭空沿用上一行，仍按占位符处理。"""
    table = _table(
        ["厚度", "Rm", "A"],
        [
            ["5", "1080", "10"],
            ["", "980", "9"],
        ],
    )
    records, _, _ = parse_table(table, MECHANICAL, None, [])
    assert all(record["grade"] == "~" for record in records)


def test_footnote_paragraph_row_is_not_parsed() -> None:
    """ASTM 版权说明这类长段落被 OCR 塞进表格时不能当成数据行。"""
    footnote = (
        "a. Maximum diameter or thickness equal to 75mm。b. Tensile, yield and "
        "bending requirements of sheet shall apply to material taken both "
        "parallel and perpendicular to the direction of rolling。c. Gauge length "
        "= 5,65sqrtS0 or 50mm, where S0 is the original cross-sectional area，"
        "with permission from ASTM International。"
    )
    table = _table(
        ["牌号", "Rm", "A"],
        [
            ["Q355B", "470", "22"],
            [footnote, "", ""],
        ],
    )
    records, _, _ = parse_table(table, MECHANICAL, None, [])
    assert len(records) == 1
    assert records[0]["grade"] == "Q355B"


def test_implausible_measure_values_are_dropped() -> None:
    """错列产生的超范围数值（如 Rp0.2=1MPa）不应进入记录。"""
    table = _table(
        ["牌号", "Rp0.2", "Rm"],
        [["50CrVA", "1", "2200"]],
    )
    diagnostics: list[dict] = []
    records, _, _ = parse_table(table, MECHANICAL, None, diagnostics)
    properties = records[0]["properties"]
    assert "Rp0.2" not in properties
    assert properties["Rm"]["value"] == 2200
    codes = {item["code"] for item in diagnostics}
    assert "VALUE_OUT_OF_RANGE" in codes


def test_orphan_impact_records_are_dropped() -> None:
    """无牌号、无条件列的独立冲击表不产出记录。"""
    records = [
        {
            "record_id": "T15-R1",
            "grade": "~",
            "conditions": {},
            "properties": {"KV2": {"value": 34}},
        },
        {
            "record_id": "T15-R2",
            "grade": "~",
            "conditions": {},
            "properties": {"KV2": {"value": 27}},
        },
    ]
    evidence = [{"evidence_id": "T15-R1"}, {"evidence_id": "T15-R2"}]
    diagnostics: list[dict] = []
    kept_records, kept_evidence = _drop_orphan_records(
        records, evidence, diagnostics, "T15"
    )
    assert kept_records == []
    assert kept_evidence == []
    assert diagnostics[0]["code"] == "ORPHAN_TABLE_SKIPPED"


def test_merge_fragments_combines_disjoint_properties() -> None:
    """同牌号同条件下的互补字段合并，字段重叠时保持独立记录。"""
    records = [
        {"grade": "Q355B", "condition_key": "", "properties": {"Rm": {"value": 470}}},
        {"grade": "Q355B", "condition_key": "", "properties": {"A": {"value": 22}}},
        {"grade": "Q355B", "condition_key": "", "properties": {"Rm": {"value": 480}}},
        {"grade": "Q235B", "condition_key": "", "properties": {"Rm": {"value": 400}}},
    ]
    merged = _merge_fragments(records)
    assert len(merged) == 3
    assert set(merged[0]["properties"]) == {"Rm", "A"}


def test_orphan_filter_keeps_conditioned_impact_records() -> None:
    """带温度等条件的冲击记录不属于无主表，必须保留。"""
    records = [
        {
            "record_id": "T5-R1",
            "grade": "~",
            "conditions": {"温度": "-40℃"},
            "properties": {"KV2": {"value": 27}},
        }
    ]
    kept_records, kept_evidence = _drop_orphan_records(
        records, [{"evidence_id": "T5-R1"}], [], "T5"
    )
    assert kept_records == records
    assert kept_evidence


def test_unit_row_is_not_parsed_as_record() -> None:
    """OCR 把单位行（ksi/ksi/%）识别成数据行时，应按列吸收为属性单位而不是产出记录。"""
    table = _table(
        ["Grade", "Tensile Strength,min", "Yield Strength,0.2% Offset", "Elongation,min,%"],
        [
            ["", "ksi", "ksi", "%"],
            ["1", "35", "20", "24"],
        ],
    )
    diagnostics: list[dict] = []
    records, _, summary = parse_table(table, MECHANICAL, None, diagnostics)
    assert summary["records"] == 1
    properties = records[0]["properties"]
    assert properties["Rm"]["value"] == 35
    assert properties["Rm"]["unit"] == "ksi"
    assert properties["Rp0.2"]["unit"] == "ksi"
    assert properties["A"]["unit"] == "%"


def test_extract_unit_ignores_qualifiers_and_offset_percent() -> None:
    """min/max 是限定词，0.2% Offset 的 % 不是单位；真正单位在后面。"""
    assert _extract_unit("Yield Strength,0.2% Offset,min,ksi", None) == "ksi"
    assert _extract_unit("Tensile Strength,min", None) == ""
    assert _extract_unit("Elongation,min,%", None) == "%"


def test_repeated_header_and_unit_rows_are_absorbed() -> None:
    """表头重复+双单位行（ksi/MPa、min/max）时按列取单位，且不产出伪记录。"""
    table = _table(
        [
            "Grade",
            "Tensile Strength,min",
            "Tensile Strength,min",
            "Yield Strength,0.2% Offset",
            "Yield Strength,0.2% Offset",
            "Elongation,min,%",
        ],
        [
            ["Grade", "ksi", "MPa", "min", "min", "Elongation in 2 in.,min,%"],
            ["Grade", "ksi", "MPa", "ksi", "MPa", "Elongation in 2 in.,min,%"],
            ["1", "35", "240", "20", "138", "24"],
        ],
    )
    diagnostics: list[dict] = []
    records, _, summary = parse_table(table, MECHANICAL, None, diagnostics)
    primary = next(item for item in records if item["grade"] == "1")
    assert primary["properties"]["Rm"]["value"] == 35
    assert primary["properties"]["Rm"]["unit"] == "ksi"
    assert primary["properties"]["Rp0.2"]["unit"] == "ksi"
    assert primary["properties"]["A"]["unit"] == "%"
    assert all(item["grade"] != "Grade" for item in records)


def test_key_column_prefers_real_grade_over_category() -> None:
    """两列都叫“材料牌号”时，取含数字/字母的真实牌号列而非“结构钢”类别列。"""
    table = _table(
        ["序号", "材料牌号", "材料牌号", "供应状态", "布氏硬度值HBS"],
        [
            ["1", "结构钢", "10A", "正火", "95.5~143"],
            ["2", "结构钢", "15A", "正火", "95.5~143"],
        ],
    )
    manifest = {
        "recipe_id": "hardness_v1",
        "version": "1.0.0",
        "profile": "mechanical_properties",
        "bindings": {"row_key": ["牌号"], "measures": {"HB": {"unit": "HBW"}}},
        "rules": {"strip_footnote_marks": True},
    }
    records, _, _ = parse_table(table, manifest, None, [])
    assert [record["grade"] for record in records] == ["10A", "15A"]


def test_merge_fragments_merges_identical_overlap_and_keeps_conflicts() -> None:
    """重叠字段值一致时合并跨页重复行；数值冲突时保持独立。"""
    records = [
        {
            "grade": "Q355",
            "condition_key": "",
            "properties": {"C": {"value": 0.2}, "Mn": {"value": 1.6}},
            "evidence_refs": ["T11-R2"],
        },
        {
            "grade": "Q355",
            "condition_key": "",
            "properties": {"C": {"value": 0.2}, "Mn": {"value": 1.6}},
            "evidence_refs": ["T11-R3"],
        },
        {
            "grade": "Q390",
            "condition_key": "",
            "properties": {"P": {"value": 0.035}},
            "evidence_refs": ["T11-R4"],
        },
        {
            "grade": "Q390",
            "condition_key": "",
            "properties": {"P": {"value": 0.2}},
            "evidence_refs": ["T11-R5"],
        },
    ]
    merged = _merge_fragments(records)
    assert len(merged) == 3
    assert merged[0]["evidence_refs"] == ["T11-R2", "T11-R3"]


def test_duplicate_key_disambiguation_appends_occurrence_index() -> None:
    records = [
        {
            "record_id": "T5-R9",
            "grade": "9",
            "conditions": {},
            "condition_key": "",
            "properties": {"A": {"value": 15}},
        },
        {
            "record_id": "T5-R10",
            "grade": "9",
            "conditions": {},
            "condition_key": "",
            "properties": {"A": {"value": 12}},
        },
    ]
    diagnostics: list[dict] = []
    adjusted_records, adjusted = _disambiguate_duplicate_keys(records, diagnostics)
    assert adjusted == 1
    assert adjusted_records[0]["condition_key"] == ""
    assert adjusted_records[1]["conditions"]["记录序号"] == "2"
    assert adjusted_records[1]["condition_key"] != adjusted_records[0]["condition_key"]
    assert diagnostics[0]["code"] == "DUPLICATE_KEY_DISAMBIGUATED"


def test_column_units_from_metadata_are_used() -> None:
    """W3：表头没有单位时，使用 TableGrid.column_units。"""
    manifest = {
        "recipe_id": "mechanical_properties_v1",
        "version": "1.0.0",
        "profile": "mechanical_properties",
        "bindings": {"row_key": ["牌号"], "measures": {"Rm": {}, "A": {}}},
        "rules": {"strip_footnote_marks": True},
    }
    table = _table(
        ["牌号", "抗拉强度", "断后伸长率"],
        [["Q355B", "470", "22"]],
        column_units=["", "MPa", "%"],
    )
    records, _, _ = parse_table(table, manifest, None, [])
    properties = records[0]["properties"]
    assert properties["Rm"]["unit"] == "MPa"
    assert properties["A"]["unit"] == "%"


def test_english_headers_ignore_offset_and_gauge_units() -> None:
    """英文表头：0.2% Offset 与标距长度不能当成单位。"""
    manifest = {
        "recipe_id": "mechanical_properties_v1",
        "version": "1.0.0",
        "profile": "mechanical_properties",
        "bindings": {"row_key": ["Grade"], "measures": {"Rp0.2": {}, "A": {}}},
        "rules": {"strip_footnote_marks": True},
    }
    table = _table(
        [
            "Grade",
            "Yield Strength at 0.2% Offset ksi",
            "Elongation in 2 in. or 50 mm",
        ],
        [["N06625", "60", "30"]],
    )
    records, _, _ = parse_table(table, manifest, None, [])
    properties = records[0]["properties"]
    assert properties["Rp0.2"]["unit"] == "ksi"
    assert properties["A"]["unit"] == "%"


def test_column_elements_from_metadata_bind_chinese_labels() -> None:
    """W3：中文元素标签无符号时，使用 TableGrid.column_elements。"""
    manifest = {
        "recipe_id": "chemical_composition_v1",
        "version": "1.0.0",
        "profile": "chemical_composition",
        "bindings": {
            "row_key": ["牌号"],
            "measures": {"Ni": {"unit": "%"}, "Cr": {"unit": "%"}},
        },
        "rules": {"strip_footnote_marks": True},
    }
    table = _table(
        ["牌号", "镍", "铬"],
        [["GH4169", "52.5", "19.0"]],
        column_elements=["", "Ni", "Cr"],
    )
    records, _, _ = parse_table(table, manifest, None, [])
    properties = records[0]["properties"]
    assert properties["Ni"]["value"] == 52.5
    assert properties["Cr"]["value"] == 19.0


def test_column_conditions_from_metadata_add_condition_columns() -> None:
    """W3：表头没有条件关键词时，用列级条件把该列绑定为条件列。"""
    table = _table(
        ["≤16", "抗拉强度"],
        [["纵向", "470"]],
        column_conditions=["方向", ""],
    )
    records, _, _ = parse_table(table, MECHANICAL, None, [])
    assert records[0]["conditions"]["方向"] == "纵向"
    assert records[0]["properties"]["Rm"]["value"] == 470


def test_binding_aliases_bind_new_edition_headers() -> None:
    """L2 候选包通过 manifest aliases 让新版本表头（UTS）绑定到 Rm。"""
    manifest = {
        "recipe_id": "mechanical_properties_v1",
        "version": "1.0.0",
        "profile": "mechanical_properties",
        "bindings": {
            "row_key": ["牌号"],
            "measures": {"Rm": {"unit": "MPa", "aliases": ["uts"]}},
        },
        "rules": {"strip_footnote_marks": True},
    }
    table = _table(["牌号", "UTS/MPa", "A/%"], [["Q355B", "470", "22"]])
    records, _, _ = parse_table(table, manifest, None, [])
    assert records[0]["properties"]["Rm"]["value"] == 470
    assert records[0]["properties"]["Rm"]["unit"] == "MPa"


def test_chinese_titanium_grade_hint() -> None:
    """ISO 5832-3 标题为中文“钛-6铝-4钒”，应补出文档级牌号。"""
    assert _document_grade_hint("外科植入物用锻造钛-6铝-4钒合金") == "Ti-6Al-4V"
    assert (
        _document_grade_hint("Wrought titanium 6-aluminum 4-vanadium alloy")
        == "Ti-6Al-4V"
    )
    assert (
        _document_grade_hint("Part 3: Wrought titanium 6-aluminium 4-vanadium alloy")
        == "Ti-6Al-4V"
    )


def test_explicit_uns_in_title_wins_over_alloy_family() -> None:
    """ASTM F136 标题含 “UNS R56401”，金标牌号是 UNS 号。"""
    title = (
        "Standard Specification for Wrought Titanium-6Aluminum-4Vanadium ELI "
        "(Extra Low Interstitial) Alloy for Surgical Implant Applications "
        "(UNS R56401)"
    )
    assert _document_grade_hint(title) == "R56401"


def test_ams_similar_to_uns_does_not_override_alloy_grade() -> None:
    """AMS 封面的 “Composition similar to UNS R56400” 只是成分对照。"""
    title = (
        "AEROSPACE MATERIAL SPECIFICATION AMS4911 REV. S "
        "Titanium Alloy, Sheet, Strip, and Plate, 6Al - 4V, Annealed "
        "(Composition similar to UNS R56400)"
    )
    assert _document_grade_hint(title) == "6Al-4V"


def test_iso_comma_proof_strength_header_is_rp02() -> None:
    assert (
        _detect_measure("Tensile strengthb / Rp0,2 / MPa minimum", "Rm")
        == "Rp0.2"
    )
    assert (
        _detect_measure("Yield strength / Rp0,2 / MPa minimum", "Rp0.2")
        == "Rp0.2"
    )


def test_merge_fragments_keeps_different_tables_separate() -> None:
    chemical = {
        "record_id": "T1-R1",
        "table_id": "T1",
        "profile": "chemical_composition",
        "grade": "1",
        "condition_key": "",
        "properties": {"C": {"raw": "0.08"}},
    }
    mechanical = {
        "record_id": "T4-R1",
        "table_id": "T4",
        "profile": "mechanical_properties",
        "grade": "1",
        "condition_key": "",
        "properties": {"Rm": {"raw": "35"}},
    }
    merged = _merge_fragments([chemical, mechanical])
    assert len(merged) == 2
    assert "C" in merged[0]["properties"]
    assert "Rm" in merged[1]["properties"]
    assert "C" not in merged[1]["properties"]


def test_chemical_columns_default_to_max_operator() -> None:
    """GB/T 5231 成分表只有元素名，未写“不大于”，金标语义是上限。"""
    table = _table(
        ["牌号", "P", "Ag"],
        [["TU00", "0.0003", "0.0025"]],
    )
    manifest = {
        **CHEMICAL,
        "bindings": {
            "row_key": ["牌号"],
            "measures": {
                "P": {"unit": "%"},
                "Ag": {"unit": "%"},
            },
        },
    }
    records, _, _ = parse_table(table, manifest, None, [])
    properties = records[0]["properties"]
    assert properties["P"]["operator"] == "≤"
    assert properties["Ag"]["operator"] == "≤"
    # “最小值”表头必须保留 ≥ 语义。
    assert _header_operator("化学成分(质量分数)/% / Cu+Ag(最小值)") == "≥"
    assert _header_operator("P, max") == "≤"


def test_merged_annotation_row_is_skipped() -> None:
    """OCR 把脚注 Te/Se/Mn 限值复制到整行时不能当成每个元素的值。"""
    table = _table(
        ["牌号", "P", "Ag", "Bi", "Sb"],
        [
            ["TU00", "0.0003", "0.0025", "0.0001", "0.0004"],
            [
                "TU00",
                "Te≤0.0002,Se≤0.0003,Mn≤0.00005",
                "Te≤0.0002,Se≤0.0003,Mn≤0.00005",
                "Te≤0.0002,Se≤0.0003,Mn≤0.00005",
                "Te≤0.0002,Se≤0.0003,Mn≤0.00005",
            ],
        ],
    )
    manifest = {
        **CHEMICAL,
        "bindings": {
            "row_key": ["牌号"],
            "measures": {
                "P": {"unit": "%"},
                "Ag": {"unit": "%"},
                "Bi": {"unit": "%"},
                "Sb": {"unit": "%"},
            },
        },
    }
    records, _, _ = parse_table(table, manifest, None, [])
    assert len(records) == 1
    assert records[0]["properties"]["P"]["raw"] == "0.0003"


def _inspection_table(headers: list[str], rows: list[list[str]]) -> dict:
    return {
        "table_id": "T99",
        "page_no": 20,
        "header_rows": 1,
        "header_paths": [[header] for header in headers],
        "n_cols": len(headers),
        "rows": [headers, *rows],
    }


def test_document_metadata_fills_method_and_sampling_from_inspection_table() -> None:
    ocr = {
        "markdown": (
            "8 试验方法\n"
            "8.1 检验项目应符合表13的规定。\n"
            "8.2 钢的化学成分试验按GB/T 4336、GB/T 20123、GB/T 223.3的规定进行。\n"
            "8.3 冲击试验的取样位置按GB/T 2975的规定。\n"
        ),
        "tables": [
            _inspection_table(
                ["序号", "检验项目", "取样数量", "取样部位及方法", "试验方法"],
                [
                    ["1", "化学成分", "1个/炉", "GB/T 20066", "见8.2"],
                    ["2", "拉伸试验", "1个/批", "钢材的一端，GB/T 2975-2018", "GB/T 228.1"],
                    ["3", "冲击试验", "3个/批", "钢材的一端，见8.3", "GB/T 229"],
                ],
            )
        ],
    }
    chemical = {
        "record_id": "T1-R1",
        "profile": "chemical_composition",
        "properties": {"C": {"value": 0.2, "raw": "0.2", "unit": "%", "operator": "≤"}},
        "conditions": {},
    }
    tensile = {
        "record_id": "T2-R1",
        "profile": "mechanical_properties",
        "properties": {"Rm": {"value": 470, "raw": "470", "unit": "MPa"}},
        "conditions": {},
    }
    diagnostics: list[dict] = []
    apply_document_metadata([chemical, tensile], ocr, diagnostics)
    chem = chemical["conditions"]
    assert "GB/T 4336" in chem["试验方法"]
    assert "GB/T 223.3" in chem["试验方法"]
    assert chem["位置"] == "按 GB/T 20066 的规定取样"
    assert chem["取样数量"] == "1"
    assert chem["取样说明"] == "1个/炉"
    tension = tensile["conditions"]
    assert tension["试验方法"] == "GB/T 228.1"
    assert tension["位置"] == "钢材的一端"
    assert tension["取样数量"] == "1"
    assert "GB/T 2975-2018" in tension["取样说明"]


def test_document_metadata_resolves_clause_methods_per_measure() -> None:
    ocr = {
        "markdown": (
            "4.3.1 化学成分按GB/T 223.3、GB/T 223.9的规定进行。\n"
            "4.3.2 力学性能按GB/T 228.1、GB/T 229、GB/T 230.1、GB/T 4161的规定进行。\n"
        ),
        "tables": [
            _inspection_table(
                ["序号", "检验项目", "取样数量和取样部位", "要求的章条号", "检验方法的章条号"],
                [
                    ["1", "化学成分", "每熔炼炉号1件", "3.2", "4.3.1"],
                    ["2", "力学性能", "每批抽1件", "3.4", "4.3.2"],
                ],
            )
        ],
    }
    record = {
        "record_id": "T8-R1",
        "profile": "mechanical_properties",
        "properties": {
            "Rm": {"value": 1570, "raw": "1570", "unit": "MPa"},
            "KU2": {"value": 39, "raw": "39", "unit": "J"},
            "HRC": {"value": 48, "raw": "48", "unit": "HRC"},
            "KIC": {"value": 100, "raw": "100", "unit": "MPa·m1/2"},
        },
        "conditions": {},
    }
    diagnostics: list[dict] = []
    apply_document_metadata([record], ocr, diagnostics)
    assert record["properties"]["Rm"]["meta"]["试验方法"] == "GB/T 228.1"
    assert record["properties"]["KU2"]["meta"]["试验方法"] == "GB/T 229"
    assert record["properties"]["HRC"]["meta"]["试验方法"] == "GB/T 230.1"
    assert record["properties"]["KIC"]["meta"]["试验方法"] == "GB/T 4161"
    assert record["properties"]["Rm"]["meta"]["取样数量"] == "1"


def test_document_metadata_falls_back_to_prose() -> None:
    ocr = {
        "markdown": "拉伸试验按GB/T 228.1的规定进行。冲击试验按GB/T 229的规定进行。",
        "tables": [],
    }
    record = {
        "record_id": "T2-R1",
        "profile": "mechanical_properties",
        "properties": {
            "Rm": {"value": 470, "raw": "470", "unit": "MPa"},
            "KV2": {"value": 34, "raw": "34", "unit": "J"},
        },
        "conditions": {},
    }
    apply_document_metadata([record], ocr, [])
    assert record["properties"]["Rm"]["meta"]["试验方法"] == "GB/T 228.1"
    assert record["properties"]["KV2"]["meta"]["试验方法"] == "GB/T 229"


def test_chemical_grade_letter_contamination_is_cleaned() -> None:
    table = _table(
        ["钢级", "质量等级", "C", "Si"],
        [
            ["Q355", "B0.24", "B0.24", "0.55"],
            ["Q355", "C", "C0.20", "0.22"],
        ],
    )
    manifest = {
        **CHEMICAL,
        "bindings": {
            "row_key": ["钢级"],
            "measures": {"C": {"unit": "%"}, "Si": {"unit": "%"}},
        },
    }
    records, _, _ = parse_table(table, manifest, None, [])
    assert [record["grade"] for record in records] == ["Q355B", "Q355C"]
    assert records[0]["properties"]["C"]["raw"] == "0.24"
    assert records[1]["properties"]["C"]["raw"] == "0.20"


def test_header_remnant_values_are_not_records_or_properties() -> None:
    table = _table(
        ["牌号", "C", "Si"],
        [
            ["Q355B", "不大于", "不大于"],
            ["Q355B", "0.20", "0.55"],
        ],
    )
    manifest = {
        **CHEMICAL,
        "bindings": {
            "row_key": ["牌号"],
            "measures": {"C": {"unit": "%"}, "Si": {"unit": "%"}},
        },
    }
    records, _, _ = parse_table(table, manifest, None, [])
    assert len(records) == 1
    assert records[0]["properties"]["C"]["raw"] == "0.20"


def test_document_metadata_uses_prose_sampling() -> None:
    """没有检验表时，正文取样条款也要回填位置/取样说明。"""
    ocr = {
        "markdown": (
            "7 化学成分\n"
            "7.1 要求 铸锭化学成分应符合表1的要求。"
            "除氢外各元素均可从铸锭取样分析。"
            "氢元素应从终产品取样分析。\n"
            "10 机械性能\n"
            "10.3 对于直径或厚度大于50mm的产品，可将其轧制成板材后再取样。"
            "对于直径或厚度小于或等于50mm的产品，应从产品上取样。\n"
        ),
        "tables": [],
    }
    chemical = {
        "record_id": "T1-R1",
        "profile": "chemical_composition",
        "properties": {"C": {"value": 0.04, "raw": "0.04", "unit": "%"}},
        "conditions": {},
    }
    tensile = {
        "record_id": "T4-R1",
        "profile": "mechanical_properties",
        "properties": {"Rm": {"value": 551, "raw": "551", "unit": "MPa"}},
        "conditions": {},
    }
    apply_document_metadata([chemical, tensile], ocr, [])
    chem = chemical["properties"]["C"]["meta"]
    assert "铸锭" in chem["位置"]
    assert "终产品" in chem["取样说明"]
    tension = tensile["properties"]["Rm"]["meta"]
    assert "产品上取样" in tension["取样说明"]


def test_combined_inspection_note_includes_position_rule() -> None:
    ocr = {
        "markdown": "取样部位按锻件图样或专用技术条件规定。",
        "tables": [
            _inspection_table(
                ["序号", "检验项目", "取样数量和取样部位", "检验方法的章条号"],
                [["1", "化学成分", "每熔炼炉号1件", "4.3.1"]],
            )
        ],
    }
    record = {
        "record_id": "T1-R1",
        "profile": "chemical_composition",
        "properties": {"C": {"value": 0.09, "raw": "0.09", "unit": "%"}},
        "conditions": {},
    }
    apply_document_metadata([record], ocr, [])
    note = record["properties"]["C"]["meta"]["取样说明"]
    assert note.startswith("取样部位按锻件图样或专用技术条件规定")
    assert "每熔炼炉号1件" in note

def test_transposed_alloy_uns_headers_become_grades() -> None:
    """ASME SB575 表1：列头 AlloyN06035 应成为牌号，而不是 grade=~ + 依据。"""
    manifest = {
        "recipe_id": "chemical_element_rows_v1",
        "version": "1.2.3",
        "profile": "chemical_composition",
        "bindings": {"row_key": ["Element"]},
        "rules": {"transposed": True, "strip_footnote_marks": True},
    }
    table = _table(
        ["Element", "AlloyN06035", "AlloyN06686"],
        [
            ["Molybdenum", "7.60-9.00", "15.0-17.0"],
            ["Chromium", "32.25-34.25", "19.0-23.0"],
        ],
    )
    records, _, _ = parse_table(table, manifest, None, [])
    assert [record["grade"] for record in records] == ["N06035", "N06686"]
    assert all(record["conditions"] == {} for record in records)
    assert records[0]["properties"]["Mo"]["raw"] == "7.60-9.00"
    assert records[1]["properties"]["Cr"]["raw"] == "19.0-23.0"


def test_long_descriptive_header_uses_uns_as_grade() -> None:
    """ASTM B708 表1：长描述表头中的 R05200/R05255 仍是牌号。"""
    assert (
        _header_grade(
            "Electron-Beam Cast(R05200) Vacuum-Arc Cast(R05200)Unalloyed Tantalum"
        )
        == "R05200"
    )
    assert _header_grade("Sintered(R05400)UnalloyedTantalum") == "R05400"
    assert _header_grade("Min") == ""
    assert _header_grade("Composition Limits, %") == ""


def test_ocr_multiline_chemical_header_is_repaired() -> None:
    """GB/T 3211：OCR 只标了首行表头，元素行/比较符行落在数据区。"""
    table = {
        "table_id": "T36",
        "page_no": 6,
        "profile": "chemical_composition",
        "header_rows": 1,
        "header_paths": [
            ["牌号"],
            ["化学成分(质量分数)/%"],
            ["化学成分(质量分数)/%"],
        ],
        "n_cols": 3,
        "rows": [
            ["牌号", "化学成分(质量分数)/%", "化学成分(质量分数)/%"],
            ["牌号", "Cr", "Fe"],
            ["牌号", "不小于", "不大于"],
            ["JCr99.4", "99.4", "0.12"],
            ["JCr99.2", "99.2", "0.25"],
        ],
        "units": ["%"],
    }
    headers, data = _header_columns(table)
    assert headers == ["牌号", "Cr / 不小于", "Fe / 不大于"]
    assert data[0][0] == "JCr99.4"
    records, _, _ = parse_table(table, CHEMICAL, None, [])
    properties = {record["grade"]: record["properties"] for record in records}
    assert properties["JCr99.4"]["Cr"]["operator"] == "≥"
    assert properties["JCr99.4"]["Fe"]["operator"] == "≤"
