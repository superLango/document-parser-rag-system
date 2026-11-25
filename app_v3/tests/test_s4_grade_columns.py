from __future__ import annotations

from app_v3.analyze.grade_columns import analyze_table_grades
from app_v3.normalize.grade import parse_grade_cell


def test_numeric_grade_in_grade_header():
    result = parse_grade_cell("32", header="Grade")
    assert [item["grade"] for item in result["grades"]] == ["Grade 32"]


def test_infer_grade_column_before_uns():
    table = {
        "table_id": "T1",
        "header_rows": 1,
        "header_paths": [[], [], ["UNS Number"], ["Carbon"]],
        "rows": [
            ["", "", "UNS Number", "Carbon"],
            ["1", "R50250", "0.08", "0.10"],
            ["2", "R50400", "0.08", "0.10"],
        ],
    }
    result = analyze_table_grades(table)
    indexes = [column["index"] for column in result["grade_columns"]]
    assert 0 in indexes
    assert [item["grade"] for item in result["row_grades"][1]] == ["Grade 1"]


def test_prefer_non_uns_grade_candidate():
    table = {
        "table_id": "T1",
        "header_rows": 1,
        "header_paths": [["Grade"], ["UNS Number"]],
        "rows": [["Grade", "UNS Number"], ["32", "R55111"]],
    }
    result = analyze_table_grades(table)
    grades = [item["grade"] for item in result["row_grades"][1]]
    assert grades[0] == "Grade 32"
    assert any(grade.startswith("UNS") for grade in grades)
