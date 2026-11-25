from __future__ import annotations

from app_v3.normalize.conditions import (
    classify_temperature,
    normalize_conditions,
    normalize_direction,
    normalize_size,
    normalize_state,
    normalize_temperature,
    normalize_unit,
)


def test_state_normalization():
    assert normalize_state("M", {"M": "软态(M)"}) == "软态(M)"
    assert normalize_state("Y") == "冷加工态(Y)"
    assert normalize_state("固溶退火态(ST)") == "固溶退火态(ST)"


def test_direction_normalization():
    assert normalize_direction("Longitudinal") == "纵向"
    assert normalize_direction("L") == "纵向"
    assert normalize_direction("Transverse") == "横向"
    assert normalize_direction("Short transverse") == "短横向"
    assert normalize_direction("纵向/横向") == "纵向/横向"


def test_temperature_normalization():
    assert normalize_temperature("RT") == "室温"
    assert normalize_temperature("room temperature") == "室温"
    assert normalize_temperature("100℃") == "100℃"
    assert normalize_temperature("20°C") == "20℃"
    assert classify_temperature("室温") == "room"
    assert classify_temperature("100℃") == "high"
    assert classify_temperature("-196℃") == "low"


def test_size_normalization():
    assert normalize_size("≤150") == "≤150mm"
    assert normalize_size(">1.5~4.0") == ">1.5~4.0mm"
    assert normalize_size("0.1~1.5mm") == "0.1~1.5mm"
    assert normalize_size("所有厚度") == "所有厚度"


def test_unit_normalization():
    assert normalize_unit("维氏硬度(HV)") == "HV"
    assert normalize_unit("MPa") == "MPa"
    assert normalize_unit("兆帕") == "MPa"
    assert normalize_unit("HBW") == "HBW"


def test_conditions_normalization():
    result = normalize_conditions(
        {"试样状态": "M", "尺寸厚度": "0.1~1.5", "方向": "L", "试验温度": "RT"},
        aliases={"M": "软态(M)"},
    )
    assert result["试样状态"] == "软态(M)"
    assert result["尺寸厚度"] == "0.1~1.5mm"
    assert result["方向"] == "纵向"
    assert result["试验温度"] == "室温"
