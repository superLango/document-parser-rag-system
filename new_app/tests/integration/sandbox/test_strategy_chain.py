from __future__ import annotations

from services.sandbox.runtime.builtin import parse_table
from services.sandbox.runtime.strategies import (
    grade_property_matrix,
    hardness_minmax,
    property_matrix,
    property_rows,
)

MECHANICAL = {
    "recipe_id": "mechanical_properties_v1",
    "version": "1.3.0",
    "profile": "mechanical_properties",
    "bindings": {
        "row_key": ["牌号"],
        "measures": {
            "Rm": {"unit": "MPa"},
            "Rp0.2": {"unit": "MPa"},
            "A": {"unit": "%"},
            "HB": {"unit": "HBW"},
        },
    },
    "rules": {"strip_footnote_marks": True},
}

CTX = {
    "recipe_id": "mechanical_properties_v1",
    "recipe_version": "1.3.0",
    "profile": "mechanical_properties",
    "measures": ["Rm", "Rp0.2", "A", "HB", "HBW"],
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


def test_property_matrix_temperature_columns() -> None:
    table = _table(
        ["Property", "20℃", "100℃"],
        [["Tensile Strength", "500", "480"], ["Yield Strength", "350", "330"]],
    )
    result = property_matrix(table, CTX)
    assert result is not None
    records, evidence = result
    assert len(records) == 4
    first = records[0]
    assert first["properties"]["Rm"]["value"] == 500.0
    assert first["properties"]["Rm"]["unit"] == "MPa"
    assert first["conditions"] == {"温度": "20℃"}
    assert first["condition_key"] == "20℃"
    assert evidence[0]["evidence_id"] == first["record_id"]


def test_grade_property_matrix_applies_header_limit() -> None:
    table = _table(
        [
            "Grade",
            "Tensile Strength / max / MPa",
            "Yield Strength(0.2% Offset) / max / ksi",
        ],
        [["12", "225", "45"]],
    )
    result = grade_property_matrix(table, CTX)
    assert result is not None
    records, _ = result
    props = records[0]["properties"]
    assert props["Rm"]["operator"] == "≤"
    assert props["Rp0.2"]["operator"] == "≤"


def test_grade_property_matrix_prefers_mpa() -> None:
    table = _table(
        [
            "Grade",
            "Tensile Strength / ksi",
            "Tensile Strength / MPa",
            "Elongation / %",
        ],
        [["1", "35", "240", "24"]],
    )
    result = grade_property_matrix(table, CTX)
    assert result is not None
    records, _ = result
    assert len(records) == 1
    properties = records[0]["properties"]
    assert properties["Rm"]["value"] == 240.0
    assert properties["Rm"]["unit"] == "MPa"
    assert properties["A"]["value"] == 24.0


def test_property_rows_vertical_table() -> None:
    table = _table(
        ["Property", "Value"],
        [["Tensile Strength", "≥ 500"], ["Elongation", "20"]],
    )
    result = property_rows(table, CTX)
    assert result is not None
    records, _ = result
    assert len(records) == 2
    assert records[0]["properties"]["Rm"]["value"] == 500.0
    assert records[0]["properties"]["Rm"]["operator"] == "≥"
    assert records[0]["grade"] == "~"


def test_hardness_minmax_range() -> None:
    table = _table(
        ["Grade", "Hardness, min", "Hardness, max"],
        [["1", "120", "150"]],
    )
    result = hardness_minmax(table, CTX)
    assert result is not None
    records, _ = result
    assert len(records) == 1
    value = records[0]["properties"]["HBW"]
    assert value["value"] == 120.0
    assert value["upper"] == 150.0
    assert value["operator"] == "range"


def test_builtin_falls_back_to_strategy_chain() -> None:
    table = _table(
        ["Property", "20℃", "100℃"],
        [["Tensile Strength", "500", "480"]],
    )
    diagnostics: list[dict] = []
    records, _, _ = parse_table(table, MECHANICAL, None, diagnostics)
    assert len(records) == 2
    codes = {item["code"] for item in diagnostics}
    assert "STRATEGY_HIT" in codes


def test_no_strategy_match_keeps_no_records() -> None:
    table = _table(
        ["Note", "Text"],
        [["Refer to Section 6", "Material shall be supplied annealed"]],
    )
    diagnostics: list[dict] = []
    records, _, _ = parse_table(table, MECHANICAL, None, diagnostics)
    assert records == []
    codes = {item["code"] for item in diagnostics}
    assert "NO_RECORDS" in codes
    assert "STRATEGY_HIT" not in codes


def test_mechanical_recipe_skips_composition_columns() -> None:
    """Element columns must not be read as mechanical measures."""
    table = _table(
        ["Grade", "H", "N", "O", "Si", "Ni"],
        [["1", "0.015", "0.03", "0.18", "0.10", "0.25"]],
    )
    diagnostics: list[dict] = []
    records, _, _ = parse_table(table, MECHANICAL, None, diagnostics)
    assert records == []
    codes = {item["code"] for item in diagnostics}
    assert "STRATEGY_HIT" not in codes


def test_other_elements_header_is_not_rel() -> None:
    """`Other Elements` contains the substring "rel" but is not ReL."""
    table = _table(
        ["Grade", "Other Elements, max. each"],
        [["1", "0.4"]],
    )
    diagnostics: list[dict] = []
    records, _, _ = parse_table(table, MECHANICAL, None, diagnostics)
    assert records == []
    codes = {item["code"] for item in diagnostics}
    assert "STRATEGY_HIT" not in codes
