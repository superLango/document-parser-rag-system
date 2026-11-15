from __future__ import annotations

import json

from services.orchestration.feedback.promotion import (
    OverlayStore,
    build_overlay,
    load_overlay,
    save_overlay,
)


def _case(**overrides) -> dict:
    base = {
        "fingerprint": "abc123",
        "rule_id": "DOC-NO-RECORDS",
        "level": "L1",
        "concept_id": "mechanical.room_tensile",
        "operator": "table_repair.add",
        "root_cause": "table_structure",
        "patch": {"table_repair": {"table_id": "T1", "spec": {"header_rows": 1}}},
        "feedback_id": "f1",
        "verified_at": "2026-11-13T10:00:00+00:00",
    }
    base.update(overrides)
    return base


def test_build_overlay_promotes_repeated_groups_only() -> None:
    cases = [
        _case(feedback_id="f1"),
        _case(feedback_id="f2", verified_at="2026-11-13T11:00:00+00:00"),
        _case(feedback_id="f3", fingerprint="other"),
    ]
    payload = build_overlay(cases, min_hits=2)
    assert len(payload["entries"]) == 1
    entry = payload["entries"][0]
    assert entry["fingerprint"] == "abc123"
    assert entry["hits"] == 2
    assert entry["feedback_ids"] == ["f1", "f2"]
    assert entry["last_verified"] == "2026-11-13T11:00:00+00:00"


def test_build_overlay_does_not_merge_different_patches() -> None:
    cases = [
        _case(),
        _case(patch={"ops": [{"op": "add", "path": "/rules/x", "value": 1}]}),
    ]
    assert build_overlay(cases, min_hits=2)["entries"] == []


def test_overlay_roundtrip_and_tamper_detection(tmp_path) -> None:
    payload = build_overlay([_case(), _case(feedback_id="f2")], min_hits=2)
    path = tmp_path / "overlay.json"
    save_overlay(path, payload)
    assert len(load_overlay(path)) == 1

    tampered = json.loads(path.read_text(encoding="utf-8"))
    tampered["entries"][0]["patch"] = {"ops": [{"op": "remove", "path": "/rules"}]}
    path.write_text(json.dumps(tampered, ensure_ascii=False), encoding="utf-8")
    assert load_overlay(path) == []


def test_overlay_store_finds_by_fingerprint_and_rule(tmp_path) -> None:
    payload = build_overlay([_case(), _case(feedback_id="f2")], min_hits=2)
    path = tmp_path / "overlay.json"
    save_overlay(path, payload)
    store = OverlayStore(path)
    assert len(store.find("abc123")) == 1
    assert len(store.find("abc123", rule_id="DOC-NO-RECORDS", level="L1")) == 1
    assert store.find("abc123", rule_id="DOC-DUP-KEYS") == []
