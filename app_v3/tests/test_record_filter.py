from __future__ import annotations

from app_v3.channels.record_filter import merge_quality, valid_record


def test_valid_record():
    assert valid_record({"requirement": "≤0.01", "grade": "TU00"}) is True
    assert valid_record({"requirement": "≤--", "grade": "TU00"}) is False
    assert valid_record({"requirement": "≤0.01", "grade": ""}) is False
    assert valid_record({"requirement": "text mm", "grade": "TU00"}) is False


def test_merge_quality_dedupes():
    base = [{"record_id": "B1", "category": "化学成分", "item": "Pb", "grade": "TU00", "requirement": "≤0.01"}]
    native = [
        {"record_id": "N1", "category": "化学成分", "item": "Pb", "grade": "TU00", "requirement": "≤0.01"},
        {"record_id": "N2", "category": "化学成分", "item": "Pb", "grade": "TU00", "requirement": "≤0.02"},
        {"record_id": "N3", "category": "热处理制度", "item": "淬火", "grade": "TU00", "requirement": "≤500℃"},
    ]
    merged, stats = merge_quality(base, native)
    assert [record["record_id"] for record in merged] == ["B1", "N2"]
    assert stats["kept"] == 1
