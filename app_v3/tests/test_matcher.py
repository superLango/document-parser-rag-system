from __future__ import annotations

from app_v3.eval.matcher import grade_match


def test_grade_wildcard_all_grades():
    assert grade_match("全部牌号", "优质钢") is True
    assert grade_match("所有牌号", "N4") is True
    assert grade_match("N4", "N5") is False
