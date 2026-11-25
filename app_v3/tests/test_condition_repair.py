from __future__ import annotations

from app_v3.analyze.condition_repair import repair_conditions


def test_repair_temperature_state_size():
    ocr = {
        "tables": [{
            "table_id": "T9",
            "caption": "表7 室温力学性能",
            "header_rows": 2,
            "header_paths": [["牌号"], ["状态"], ["厚度mm"], ["抗拉强度Rm/MPa"]],
            "rows": [
                ["牌号", "状态", "厚度mm", "抗拉强度Rm/MPa"],
                ["N4", "M", "0.1~1.5", "≥345"],
            ],
        }]
    }
    records = [{
        "record_id": "T9-R1-C3",
        "category": "室温拉伸",
        "item": "抗拉强度(Rm)",
        "grade": "N4",
        "requirement": "≥345",
        "unit": "MPa",
        "source_table": "T9",
    }]
    repaired, stats = repair_conditions(records, ocr)
    conditions = repaired[0]["conditions"]
    assert conditions["试验温度"] == "室温"
    assert conditions["试样状态"] == "软态(M)"
    assert conditions["尺寸厚度"] == "0.1~1.5mm"
    assert stats["temperature"] == 1
    assert stats["state"] == 1


def test_repair_does_not_override_existing():
    ocr = {"tables": [{
        "table_id": "T1", "caption": "表1 室温性能",
        "header_paths": [["牌号"], ["试验温度/℃"]],
        "rows": [["牌号", "试验温度/℃"], ["N4", "100"]],
    }]}
    records = [{
        "record_id": "T1-R1-C1", "category": "高温拉伸", "item": "抗拉强度(Rm)",
        "grade": "N4", "requirement": "≥345", "unit": "MPa",
        "conditions": {"试验温度": "100℃"}, "source_table": "T1",
    }]
    repaired, stats = repair_conditions(records, ocr)
    assert repaired[0]["conditions"]["试验温度"] == "100℃"
    assert stats["temperature"] == 0
