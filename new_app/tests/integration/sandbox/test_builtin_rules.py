from __future__ import annotations

from services.sandbox.runtime.builtin import parse_table

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
            "A": {"unit": "%"},
            "KU2": {"unit": "J"},
            "HB": {"unit": "HBW"},
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
    assert properties["HBW"]["value"] == 170
    assert "HB" not in properties


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
