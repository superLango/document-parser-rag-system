from __future__ import annotations

from services.agent.agents.review import _sample_evidence, _sample_records


def _records(count: int, table_id: str) -> list[dict]:
    return [
        {
            "record_id": f"{table_id}-{index}",
            "table_id": table_id,
            "evidence_refs": [f"{table_id}-E{index}"],
        }
        for index in range(count)
    ]


def test_sample_records_keeps_every_table() -> None:
    records = _records(200, "T1") + _records(3, "T2") + _records(3, "T3")
    sampled = _sample_records(records)
    assert len(sampled) == 60
    assert {item["table_id"] for item in sampled} == {"T1", "T2", "T3"}
    assert sum(1 for item in sampled if item["table_id"] == "T2") == 3


def test_sample_evidence_prefers_referenced_ids() -> None:
    records = [{"record_id": "T1-0", "table_id": "T1", "evidence_refs": ["E1"]}]
    evidence = [{"evidence_id": f"E{index}"} for index in range(200)]
    sampled = _sample_evidence(evidence, records, limit=10)
    assert len(sampled) == 10
    assert sampled[0]["evidence_id"] == "E1"
