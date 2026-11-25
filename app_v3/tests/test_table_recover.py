from __future__ import annotations

from app_v3.channels.table_recover import classify_header, recover_missing_columns


def test_classify_header():
    assert classify_header("中心偏析a") == ("高倍", "中心偏析", "级")
    assert classify_header("弯曲角α(°)")[0] == "弯曲试验"
    assert classify_header("抗拉强度Rm/MPa")[0] == "室温拉伸"


def test_recover_missing_columns():
    ocr = {
        "tables": [{
            "table_id": "T17",
            "header_rows": 2,
            "header_paths": [["钢的质量等级"], ["锭型偏析"], ["中心偏析a"], ["中心疏松"]],
            "rows": [
                ["钢的质量等级", "锭型偏析", "中心偏析a", "中心疏松"],
                ["钢的质量等级", "级别", "级别", "级别"],
                ["优质钢", "3", "3", "3"],
            ],
        }]
    }
    records = [{
        "record_id": "T17-R2-C1",
        "category": "高倍",
        "item": "非金属夹杂物",
        "grade": "优质钢",
        "requirement": "≤3",
        "source_table": "T17",
    }]
    recovered, stats = recover_missing_columns(records, ocr)
    assert stats["records"] >= 2
    assert any(record["item"] == "中心偏析" for record in recovered)
    assert all(record["record_id"].endswith("-R") for record in recovered)
