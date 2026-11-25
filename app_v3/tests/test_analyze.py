from __future__ import annotations

from app_v3.analyze.document_grade import infer_document_grades
from app_v3.analyze.grade_columns import analyze_table_grades
from app_v3.analyze.repair import repair_records


def test_analyze_table_grades():
    table = {
        "table_id": "T1",
        "header_rows": 1,
        "header_paths": [["牌号"], ["状态"], ["厚度mm"], ["抗拉强度Rm/MPa"]],
        "rows": [
            ["牌号", "状态", "厚度mm", "抗拉强度Rm/MPa"],
            ["N4、N5", "M", "0.1~1.5", "≥345"],
            ["N6", "Y", ">1.5~4.0", "≥620"],
        ],
    }
    result = analyze_table_grades(table)
    assert result["grade_columns"][0]["index"] == 0
    assert [item["grade"] for item in result["row_grades"][1]] == ["N4", "N5"]
    assert result["row_grades"][2][0]["grade"] == "N6"


def test_infer_document_grades_ti64():
    grades = infer_document_grades([
        "Titanium alloy Ti-6Al-4V (Grade 5)",
        "This specification covers Ti-6Al-4V alloy bars.",
    ])
    names = [item["grade"] for item in grades]
    assert "Ti-6Al-4V" in names


def test_repair_from_document_grade():
    records = [{
        "record_id": "T2-R1-C1",
        "category": "化学成分",
        "item": "Al",
        "grade": "Aluminum",
        "requirement": "5.50",
        "unit": "%",
    }]
    pages = [
        "This aerospace specification covers Ti-6Al-4V alloy bars, wire and forgings.",
        "The Ti-6Al-4V alloy shall conform to the chemical composition in Table 1.",
    ]
    repaired, stats = repair_records(records, ocr=None, pages_markdown=pages)
    assert repaired[0]["grade"] == "Ti-6Al-4V"
    assert stats["repaired_from_document"] == 1


def test_repair_keeps_valid_grade():
    records = [{"record_id": "r1", "category": "室温拉伸", "item": "抗拉强度(Rm)",
                "grade": "N4", "requirement": "≥345", "unit": "MPa"}]
    repaired, stats = repair_records(records)
    assert repaired[0]["grade"] == "N4"
    assert stats["already_ok"] == 1
