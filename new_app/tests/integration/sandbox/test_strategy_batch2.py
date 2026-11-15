from __future__ import annotations

from services.sandbox.runtime.builtin import parse_table
from services.sandbox.runtime.strategies import (
    DEFAULT_CHAIN,
    element_matrix,
    grade_property_tail,
    nonrecord,
)

MECHANICAL = {
    "recipe_id": "mechanical_properties_v1",
    "version": "1.4.0",
    "profile": "mechanical_properties",
    "bindings": {
        "row_key": ["牌号"],
        "measures": {"Rm": {"unit": "MPa"}, "Rp0.2": {"unit": "MPa"}, "A": {"unit": "%"}},
    },
    "rules": {"strip_footnote_marks": True},
}
MECH_CTX = {
    "recipe_id": "mechanical_properties_v1",
    "recipe_version": "1.4.0",
    "profile": "mechanical_properties",
    "measures": ["Rm", "Rp0.2", "A"],
}
CHEM_CTX = {
    "recipe_id": "chemical_composition_v1",
    "recipe_version": "1.1.0",
    "profile": "chemical_composition",
    "measures": ["C", "Si", "Mn", "P", "S"],
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


def test_default_chain_has_batch2_strategies() -> None:
    assert DEFAULT_CHAIN[0] == "nonrecord"
    assert "grade_property_tail" in DEFAULT_CHAIN
    assert "element_matrix" in DEFAULT_CHAIN


def test_nonrecord_blocks_tolerance_table() -> None:
    table = _table(
        ["Element", "Product Analysis Tolerances"],
        [["C", "0.01"]],
    )
    assert nonrecord(table, MECH_CTX) == ([], [])


def test_nonrecord_blocks_dimension_table() -> None:
    table = _table(
        ["外径", "壁厚", "长度"],
        [["20", "2.5", "6000"]],
    )
    assert nonrecord(table, MECH_CTX) == ([], [])


def test_nonrecord_blocks_inspection_table() -> None:
    table = _table(
        ["检验项目", "取样数量", "试验方法"],
        [["拉伸", "1", "GB/T 228.1"]],
    )
    assert nonrecord(table, MECH_CTX) == ([], [])


def test_nonrecord_blocks_inspection_profile_table() -> None:
    table = _table(
        ["钢的质量等级", "级别，不大于"],
        [["优质钢", "3"]],
        profile="inspection",
    )
    assert nonrecord(table, MECH_CTX) == ([], [])


def test_nonrecord_allows_property_table() -> None:
    table = _table(
        ["Grade", "Tensile Strength", "Yield Strength", "Elongation"],
        [["Q355B", "470", "355", "22"]],
    )
    assert nonrecord(table, MECH_CTX) is None


def test_grade_property_tail_realigns_shifted_row() -> None:
    table = _table(
        ["牌号", "直径", "状态", "抗拉强度 Rm", "屈服强度 Rp0.2", "断后伸长率 A"],
        [["Q355B", "20", "正火", "", "470", "355", "22"]],
    )
    result = grade_property_tail(table, MECH_CTX)
    assert result is not None
    records, _ = result
    assert len(records) == 1
    properties = records[0]["properties"]
    assert properties["Rm"]["value"] == 470.0
    assert properties["Rp0.2"]["value"] == 355.0
    assert properties["A"]["value"] == 22.0
    assert records[0]["grade"] == "Q355B"
    assert records[0]["conditions"] == {"状态": "20 / 正火"}


def test_element_matrix_transposed_chemistry() -> None:
    table = _table(
        ["元素", "Q355B", "Q235B"],
        [["C", "0.20", "0.22"], ["Si", "0.55", "0.35"], ["Mn", "1.60", "1.40"]],
    )
    result = element_matrix(table, CHEM_CTX)
    assert result is not None
    records, evidence = result
    assert len(records) == 2
    first = records[0]
    assert first["grade"] == "Q355B"
    assert first["properties"]["C"]["value"] == 0.2
    assert first["properties"]["C"]["unit"] == "%"
    assert first["properties"]["Mn"]["value"] == 1.6
    assert evidence[0]["cells"]["C"] == "0.20"


def test_builtin_blocks_nonrecord_table() -> None:
    table = _table(
        ["Element", "Permissible Variations"],
        [["C", "0.01"]],
    )
    diagnostics: list[dict] = []
    records, _, _ = parse_table(table, MECHANICAL, None, diagnostics)
    assert records == []
    codes = {item["code"] for item in diagnostics}
    assert "NONRECORD_TABLE" in codes


CHEMICAL = {
    "recipe_id": "chemical_composition_v1",
    "version": "1.1.0",
    "profile": "chemical_composition",
    "bindings": {
        "row_key": ["牌号", "钢号"],
        "measures": {
            "C": {"unit": "%"},
            "Si": {"unit": "%"},
            "Mn": {"unit": "%"},
            "P": {"unit": "%"},
            "Cu": {"unit": "%"},
        },
    },
    "rules": {"strip_footnote_marks": True},
}


def test_bound_parser_strips_limit_markers_from_headers() -> None:
    table = _table(
        ["钢号", "化学成分 / C", "化学成分 / P≤", "化学成分 / Cu≤"],
        [["Q355B", "0.20", "0.025", "0.30"]],
    )
    records, _, _ = parse_table(table, CHEMICAL, None, [])
    assert len(records) == 1
    assert set(records[0]["properties"]) == {"C", "P", "Cu"}
    assert records[0]["properties"]["P"]["value"] == 0.025


def test_bound_parser_does_not_treat_limit_labels_as_grades() -> None:
    table = _table(
        ["", "C", "Si", "Mn"],
        [["max", "0.54", "0.40", "0.80"], ["min", "0.50", "--", "0.50"]],
    )
    records, _, _ = parse_table(table, CHEMICAL, None, [])
    assert records
    assert {record["grade"] for record in records} == {"~"}
    assert all("max" not in record["grade"].lower() for record in records)


def test_nonrecord_blocks_revision_history_table() -> None:
    table = _table(
        ["版本号", "更改内容及说明", "日期", "更改人"],
        [["A", "初版", "2026-01-01", "张三"]],
    )
    assert nonrecord(table, MECH_CTX) == ([], [])


def test_bound_parser_joins_spaced_symbols() -> None:
    manifest = {
        "recipe_id": "mechanical_properties_v1",
        "version": "1.5.0",
        "profile": "mechanical_properties",
        "bindings": {
            "row_key": ["牌号"],
            "measures": {
                "Rm": {"unit": "MPa"},
                "Rp0.2": {"unit": "MPa"},
                "A": {"unit": "%"},
                "Z": {"unit": "%"},
                "KU2": {"unit": "J"},
            },
        },
        "rules": {"strip_footnote_marks": True},
    }
    table = _table(
        [
            "牌号",
            "R m MPa ≥",
            "R eL (R ) p0.2 MPa ≥",
            "A % ≥",
            "Z % ≥",
            "KU 2 (KV) 2 J ≥",
        ],
        [["30Mn2", "685", "440", "15", "50", "55"]],
    )
    records, _, _ = parse_table(table, manifest, None, [])
    assert len(records) == 1
    assert set(records[0]["properties"]) == {"Rm", "Rp0.2", "A", "Z", "KU2"}
    assert records[0]["properties"]["Rp0.2"]["value"] == 440.0


def test_bound_parser_binds_direction_and_greek_symbols() -> None:
    manifest = {
        "recipe_id": "mechanical_properties_v1",
        "version": "1.5.0",
        "profile": "mechanical_properties",
        "bindings": {
            "row_key": ["材料牌号"],
            "conditions": ["方向", "状态"],
            "measures": {
                "Rm": {"unit": "MPa"},
                "Rp0.2": {"unit": "MPa"},
                "A": {"unit": "%"},
                "Z": {"unit": "%"},
                "KU2": {"unit": "J"},
                "HB": {"unit": "HBW"},
            },
        },
        "rules": {"strip_footnote_marks": True},
    }
    table = {
        "table_id": "T3",
        "page_no": 1,
        "header_rows": 1,
        "header_paths": [
            ["材料牌号"],
            ["试样方向"],
            ["力学性能", "σbN/mm²"],
            ["力学性能", "σ0.2N/mm²"],
            ["力学性能", "δ5%"],
            ["力学性能", "ψ%"],
            ["力学性能", "AKUJ"],
            ["力学性能", "硬度HB"],
        ],
        "n_cols": 8,
        "rows": [
            ["材料牌号", "试样方向", "σbN/mm²", "σ0.2N/mm²", "δ5%", "ψ%", "AKUJ", "硬度HB"],
            ["25Cr2MoVA", "纵向", "835", "735", "15", "50", "47", "269-302"],
        ],
        "units": [],
    }
    records, _, _ = parse_table(table, manifest, None, [])
    assert len(records) == 1
    record = records[0]
    assert record["conditions"] == {"方向": "纵向"}
    assert set(record["properties"]) == {"Rm", "Rp0.2", "A", "Z", "KU2", "HB"}
    assert record["properties"]["Rp0.2"]["value"] == 735.0


def test_element_matrix_transposed_with_leading_label_column() -> None:
    table = _table(
        ["牌号", "牌号", "Co9998", "Co9995", ""],
        [
            ["化学成分/%", "Co不小于", "Co不小于", "99.98", "99.95"],
            ["化学成分/%", "杂质含量不大于", "C", "0.004", "0.005"],
            ["化学成分/%", "杂质含量不大于", "S", "0.001", "0.002"],
            ["化学成分/%", "杂质含量不大于", "Mn", "0.001", "0.008"],
            ["化学成分/%", "杂质含量不大于", "Fe", "0.003", "0.02"],
        ],
    )
    result = element_matrix(table, CHEM_CTX)
    assert result is not None
    records, _ = result
    assert [record["grade"] for record in records] == ["Co9998", "Co9995"]
    assert records[0]["properties"]["C"]["value"] == 0.004
    assert records[0]["properties"]["Mn"]["value"] == 0.001


def test_element_matrix_limit_headers_become_conditions() -> None:
    table = _table(
        ["元素", "元素含量，wt.% / Min", "元素含量，wt.% / Max"],
        [["C", "0.20", "0.30"], ["Si", "0.55", "0.65"], ["Mn", "1.40", "1.60"]],
    )
    result = element_matrix(table, CHEM_CTX)
    assert result is not None
    records, _ = result
    assert records[0]["grade"] == "~"
    assert records[0]["conditions"] == {"依据": "元素含量，wt.% Min"}
    assert records[1]["conditions"] == {"依据": "元素含量，wt.% Max"}
    assert records[0]["properties"]["C"]["value"] == 0.2
