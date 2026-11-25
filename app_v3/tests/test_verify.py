from __future__ import annotations

from app_v3.verify.conditions import validate_conditions
from app_v3.verify.conflicts import detect_conflicts
from app_v3.verify.conservation import validate_conservation
from app_v3.verify.evidence import validate_evidence
from app_v3.verify.pipeline import verify_records
from app_v3.verify.queue import build_queue


def _ocr():
    return {
        "pages": [{"page_no": 1}],
        "tables": [{
            "table_id": "T1",
            "rows": [["牌号", "抗拉强度Rm"], ["N4", "345"]],
        }],
    }


def test_evidence_stale_table():
    record = {"record_id": "T9-R1-C1", "category": "室温拉伸", "item": "抗拉强度(Rm)",
              "grade": "N4", "requirement": "≥345", "unit": "MPa",
              "source_table": "T9", "page_no": 1, "channel": "table"}
    diagnostics = validate_evidence(record, {"T1": {}}, page_count=1)
    assert any(item["code"] == "stale_table_reference" for item in diagnostics)


def test_conservation_value_not_in_source():
    record = {"record_id": "T1-R1-C1", "category": "室温拉伸", "item": "抗拉强度(Rm)",
              "grade": "N4", "requirement": "≥999", "unit": "MPa", "source_table": "T1"}
    diagnostics = validate_conservation(record, {"T1": _ocr()["tables"][0]})
    assert any(item["code"] == "value_not_in_source" for item in diagnostics)


def test_conditions_temperature_conflict():
    record = {"category": "室温拉伸", "item": "抗拉强度(Rm)", "requirement": "≥345",
              "conditions": {"试验温度": "100℃"}}
    diagnostics = validate_conditions(record)
    assert any(item["code"] == "temperature_category_conflict" for item in diagnostics)


def test_conflicts_same_key_different_value():
    records = [
        {"category": "室温拉伸", "item": "抗拉强度(Rm)", "grade": "N4", "requirement": "≥345", "conditions": {}},
        {"category": "室温拉伸", "item": "抗拉强度(Rm)", "grade": "N4", "requirement": "≥380", "conditions": {}},
    ]
    diagnostics, summaries = detect_conflicts(records)
    assert summaries
    assert 0 in diagnostics and 1 in diagnostics


def test_verify_pipeline_and_queue():
    records = [
        {"record_id": "T9-R1-C1", "category": "室温拉伸", "item": "抗拉强度(Rm)",
         "grade": "N4", "requirement": "≥999", "unit": "MPa", "source_table": "T9", "page_no": 1},
    ]
    result = verify_records(records, _ocr())
    assert result["summary"]["total"] == 1
    assert result["queue"]
    assert any(item["code"] == "stale_table_reference" for item in result["records"][0]["verification"]["diagnostics"])


def test_build_queue_skips_clean():
    records = [{"record_id": "r1", "verification": {"status": "ok", "diagnostics": []}}]
    assert build_queue(records) == []
