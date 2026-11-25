from __future__ import annotations

import pytest

from app_v3.normalize.grade import (
    choose_grade_columns,
    is_header_phrase,
    normalize_grade,
    parse_grade_cell,
    split_grade_values,
)


def grades(value: str, header: str = "牌号") -> list[str]:
    return [item["grade"] for item in parse_grade_cell(value, header=header)["grades"]]


def test_choose_grade_columns_cn_en():
    assert choose_grade_columns(["牌号", "状态", "厚度mm"]) == [0]
    assert choose_grade_columns(["Grade", "Condition", "Thickness"]) == [0]
    assert choose_grade_columns(["材料牌号", "热处理制度"]) == [0]


def test_split_multi_grades():
    values = grades("N4、N5、NW4-0.07、NW4-0.1、NW4-0.15")
    assert values == ["N4", "N5", "NW4-0.07", "NW4-0.1", "NW4-0.15"]


def test_pure_letter_grade_allowed():
    assert "DN" in grades("N7、DN、NMg0.1、NSi0.19")


def test_state_code_not_grade():
    assert grades("M", header="状态") == []
    assert grades("M", header="牌号") == [] or "M" not in grades("M", header="牌号")


def test_reject_header_phrases():
    assert grades("Up to 2.000,incl(1)") == []
    assert grades("Sheet and stripc") == []
    assert is_header_phrase("Up to 2.000") is True
    assert is_header_phrase("Sheet and strip") is True
    assert is_header_phrase("N4") is False


def test_english_grades():
    assert grades("Ti-6Al-4V") == ["Ti-6Al-4V"]
    assert grades("6Al-4V") == ["6Al-4V"]
    assert grades("Grade 5") == ["Grade 5"]
    assert grades("UNS R56400") == ["UNS R56400"]


def test_normalize_grade_aliases():
    info = normalize_grade("Ti-6Al-4V")
    assert info["grade"] == "Ti-6Al-4V"
    assert "6Al-4V" in info["aliases"]
    info = normalize_grade("6Al-4V")
    assert "Ti-6Al-4V" in info["aliases"]


def test_split_grade_values_accepts_keywords():
    assert split_grade_values("N4、N5") == ["N4", "N5"]
