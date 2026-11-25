from __future__ import annotations

from app_v3.channels.router import choose_channel, filter_recovery_unresolved, record_keys, verification_score


def _ocr():
    return {"pages": [{"page_no": 1}], "tables": [{"table_id": "T1", "rows": [["牌号", "抗拉强度"], ["N4", "345"]]}]}


def test_verification_score_clean():
    records = [{
        "record_id": "T1-R1-C1", "category": "室温拉伸", "item": "抗拉强度(Rm)",
        "grade": "N4", "requirement": "≥345", "unit": "MPa",
        "source_table": "T1", "page_no": 1, "conditions": {"试验温度": "室温"},
    }]
    score = verification_score(records, _ocr())
    assert score["total"] == 1
    assert score["score"] > 0


def test_choose_channel_by_coverage_gain():
    s9 = [{
        "record_id": "T1-R1-C1", "category": "室温拉伸", "item": "抗拉强度(Rm)",
        "grade": "N4", "requirement": "≥345", "unit": "MPa",
        "source_table": "T1", "page_no": 1, "conditions": {"试验温度": "室温"},
    }]
    full = s9 + [
        {"record_id": "T2-R1-C1", "category": "高倍", "item": "晶粒度", "grade": "",
         "requirement": "≤3", "unit": "级", "source_table": "T2", "page_no": 2},
        {"record_id": "T3-R1-C1", "category": "高倍", "item": "非金属夹杂物", "grade": "",
         "requirement": "≤3", "unit": "级", "source_table": "T3", "page_no": 3},
    ]
    assert len(record_keys(full)) > len(record_keys(s9))
    routed = choose_channel(s9, full, _ocr())
    assert routed["channel"] == "full_rebind"


def test_choose_channel_keeps_s9_without_gain():
    s9 = [{
        "record_id": "T1-R1-C1", "category": "室温拉伸", "item": "抗拉强度(Rm)",
        "grade": "N4", "requirement": "≥345", "unit": "MPa",
        "source_table": "T1", "page_no": 1, "conditions": {"试验温度": "室温"},
    }]
    full = [dict(s9[0])]
    routed = choose_channel(s9, full, _ocr())
    assert routed["channel"] == "s9"


def test_filter_drops_unresolved_recovery():
    records = [
        {"record_id": "T1-R1-C1", "channel": "recovered", "category": "高倍",
         "item": "晶粒度", "grade": "", "requirement": "≤3", "unit": "级",
         "source_table": "T9", "conditions": {}},
        {"record_id": "T1-R1-C2", "channel": "table", "category": "高倍",
         "item": "晶粒度", "grade": "", "requirement": "≤3", "unit": "级",
         "source_table": "T9", "conditions": {}},
    ]
    filtered = filter_recovery_unresolved(records, _ocr())
    assert len(filtered) == 1
    assert filtered[0]["channel"] == "table"
