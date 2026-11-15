from __future__ import annotations

from services.orchestration.feedback.document_repair import (
    apply_metadata_override,
    build_metadata_override,
    find_method_evidence,
)

INVENTORY = {
    "items": [
        {
            "item": "化学成分a",
            "feature": "化学成分",
            "method": "GB/T 4698、YS/T 1262",
            "sampling": {
                "quantity": "1",
                "location": "成品",
                "note": "每批任取 1 份试样",
            },
        },
        {
            "item": "弯曲性能",
            "feature": "弯曲",
            "method": "GB/T 232",
            "sampling": {},
        },
    ]
}


def test_find_method_evidence_by_subject() -> None:
    assert find_method_evidence(INVENTORY, "化学成分", "试验方法") == {
        "试验方法": "GB/T 4698、YS/T 1262"
    }


def test_find_sampling_evidence() -> None:
    fields = find_method_evidence(INVENTORY, "化学成分", "取样")
    assert fields["取样说明"] == "每批任取 1 份试样"
    assert fields["位置"] == "成品"
    assert fields["取样数量"] == "1"


def test_missing_evidence_returns_empty() -> None:
    assert find_method_evidence(INVENTORY, "冲击", "试验方法") == {}
    assert find_method_evidence({}, "化学成分", "试验方法") == {}


def test_apply_override_fills_only_empty_values() -> None:
    records = [
        {
            "table_id": "T2",
            "profile": "chemical_composition",
            "conditions": {"试验方法": "已有方法"},
            "properties": {
                "C": {"meta": {"试验方法": "已有方法"}},
                "Fe": {"meta": {}},
            },
        },
        {
            "table_id": "T5",
            "profile": "mechanical_properties",
            "properties": {"Rm": {"meta": {}}},
        },
    ]
    override = build_metadata_override(
        "T2", "chemical_composition", {"试验方法": "GB/T 4698"}
    )
    filled = apply_metadata_override(records, override)
    assert filled == 1
    assert records[0]["properties"]["C"]["meta"]["试验方法"] == "已有方法"
    assert records[0]["properties"]["Fe"]["meta"]["试验方法"] == "GB/T 4698"
    assert records[0]["conditions"]["试验方法"] == "已有方法"
    assert records[1]["properties"]["Rm"]["meta"].get("试验方法") is None


def test_apply_override_writes_conditions_when_meta_missing() -> None:
    records = [
        {
            "table_id": "T2",
            "profile": "chemical_composition",
            "conditions": {},
            "properties": {},
        }
    ]
    override = build_metadata_override(
        "T2", "chemical_composition", {"取样说明": "每批任取 1 份试样"}
    )
    assert apply_metadata_override(records, override) == 1
    assert records[0]["conditions"]["取样说明"] == "每批任取 1 份试样"
