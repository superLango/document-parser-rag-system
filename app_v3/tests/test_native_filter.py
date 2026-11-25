from __future__ import annotations

from app_v3.channels.native_filter import filter_native_records


def test_filter_native_keeps_supported_items_and_dedupes():
    base = [{
        "record_id": "T1-R1-C1", "category": "化学成分", "item": "Pb",
        "grade": "TU00", "requirement": "≤0.01", "source_table": "T1",
    }]
    native = [
        {"record_id": "N1", "category": "化学成分", "item": "Pb", "grade": "TU00", "requirement": "≤0.01"},
        {"record_id": "N2", "category": "化学成分", "item": "Pb", "grade": "TU00", "requirement": "≤0.02"},
        {"record_id": "N3", "category": "热处理制度", "item": "淬火温度", "grade": "TU00", "requirement": "≤500"},
    ]
    kept, stats = filter_native_records(native, base)
    assert [record["record_id"] for record in kept] == ["N2"]
    assert stats["dropped_duplicate"] == 1
    assert stats["dropped_item"] == 1
