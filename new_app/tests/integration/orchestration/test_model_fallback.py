from __future__ import annotations

from services.orchestration.model_fallback import (
    build_task,
    existing_features,
    merge_proposals,
    should_trigger,
    validate_proposals,
)

TEXT = (
    "6.1 晶粒度\n晶粒度应按 GB/T 6394 进行检验，晶粒度级别应不低于5级。\n"
    "6.2 低倍组织\n低倍组织应按 GB/T 226 进行检验，不得有裂纹。"
)


def test_trigger_requires_low_coverage_or_missing_items() -> None:
    assert should_trigger({}, []) == []
    reasons = should_trigger(
        {
            "stats": {
                "coverage": {
                    "record_features": ["室温拉伸"],
                    "aligned_ratio": 0.5,
                },
                "qualitative_items": 2,
                "qualitative_records": 1,
            }
        },
        [{"code": "ROW_KEY_NOT_FOUND"}, {"code": "NO_RECORDS"}, {"code": "NO_RECORDS"}],
    )
    assert reasons == [
        "inventory_coverage_low",
        "qualitative_missing",
        "matrix_diagnostics_high",
    ]


def test_validate_accepts_only_verbatim_quotes() -> None:
    accepted, rejected = validate_proposals(
        [
            {
                "feature": "晶粒度",
                "requirement": "晶粒度级别应不低于5级。",
                "quote": "晶粒度级别应不低于5级",
            },
            {
                "feature": "低倍",
                "requirement": "低倍组织不得有裂纹。",
                "quote": "文档里不存在的句子",
            },
            {
                "feature": "室温拉伸",
                "requirement": "不属于允许的定性项目。",
                "quote": "晶粒度应按 GB/T 6394 进行检验",
            },
        ],
        TEXT,
        existing={"尺寸"},
    )
    assert [item["feature"] for item in accepted] == ["晶粒度"]
    reasons = {item["reason"] for item in rejected}
    assert "quote_not_found" in reasons
    assert "feature_not_allowed" in reasons


def test_merge_proposals_adds_qualitative_records_and_evidence() -> None:
    accepted, _ = validate_proposals(
        [
            {
                "feature": "晶粒度",
                "requirement": "晶粒度级别应不低于5级。",
                "quote": "晶粒度级别应不低于5级",
                "method": "GB/T 6394",
            }
        ],
        TEXT,
        existing=set(),
    )
    records, evidence, added = merge_proposals([], [], accepted)
    assert len(added) == 1
    record = records[0]
    assert record["record_id"] == "MF-1"
    assert record["profile"] == "qualitative"
    assert record["properties"]["晶粒度"]["meta"]["试验方法"] == "GB/T 6394"
    assert record["source"]["model"] is True
    assert evidence[0]["evidence_id"] == "ev-mf-1"
    assert evidence[0]["quote"] == "晶粒度级别应不低于5级"


def test_build_task_carries_existing_features_and_schema() -> None:
    task = build_task(
        "run-1",
        "trace-1",
        TEXT,
        {"stats": {"coverage": {"inventory_features": ["尺寸"]}}},
        [
            {
                "record_id": "R1",
                "properties": {"Rm": {"value": 470}},
            }
        ],
        max_items=3,
    )
    assert task["role"] == "review"
    assert task["output_schema"]["properties"]["items"]["maxItems"] == 3
    assert "Rm" in task["inputs"]["existing_features"]
    assert "尺寸" in task["inputs"]["existing_features"]
    assert existing_features([], {}) == set()
