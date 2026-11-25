from __future__ import annotations

from app_v3.analyze.grade_cleanup import clean_grade, cleanup_record_grades


def test_clean_grade_footnote():
    assert clean_grade("BZn9-29f") == ("BZn9-29", "BZn9-29f")
    assert clean_grade("TU00") == ("TU00", "")
    assert clean_grade("TC4") == ("TC4", "")


def test_cleanup_record_grades():
    records = [
        {"record_id": "r1", "grade": "BZn9-29f"},
        {"record_id": "r2", "grade": "N4"},
    ]
    cleaned, stats = cleanup_record_grades(records)
    assert cleaned[0]["grade"] == "BZn9-29"
    assert cleaned[0]["grade_aliases"] == ["BZn9-29f"]
    assert cleaned[1]["grade"] == "N4"
    assert stats["cleaned"] == 1
