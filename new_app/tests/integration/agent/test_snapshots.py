from __future__ import annotations

from hanson_contracts import AcceptedSnapshot

from services.orchestration.snapshots import (
    accepted_scope,
    build_snapshot,
    diff_against_snapshot,
    field_digests,
    next_patch_chain,
    records_digest,
)


def _record(
    record_id: str,
    grade: str,
    *,
    table_id: str = "T1",
    unit: str = "MPa",
    **props: float,
) -> dict:
    return {
        "record_id": record_id,
        "table_id": table_id,
        "grade": grade,
        "properties": {
            name: {"value": value, "unit": unit} for name, value in props.items()
        },
    }


def test_field_digests_and_scope() -> None:
    records = [
        _record("R1", "Q355B", Rm=470),
        _record("R2", "Q355B", table_id="T2", ReL=355, A=21),
    ]
    digests = field_digests(records)
    assert set(digests) == {"T1:Q355B:Rm", "T2:Q355B:ReL", "T2:Q355B:A"}
    tables, fields = accepted_scope(records)
    assert tables == ["T1", "T2"]
    assert fields == sorted(digests)


def test_records_digest_is_order_independent() -> None:
    a = [_record("R1", "A", Rm=1), _record("R2", "B", Rm=2)]
    b = list(reversed(a))
    assert records_digest(a) == records_digest(b)


def test_diff_detects_changed_and_missing_fields() -> None:
    snapshot = build_snapshot(
        [_record("R1", "Q355B", Rm=470, A=21)],
        document_id="doc-1",
        document_version=1,
        run_id="run-1",
    )
    changed = diff_against_snapshot(
        snapshot, [_record("R1", "Q355B", Rm=480)]
    )
    assert {item["field"] for item in changed} == {"T1:Q355B:Rm", "T1:Q355B:A"}
    assert {item["change"] for item in changed} == {"changed", "missing"}


def test_diff_ignores_unaccepted_new_fields() -> None:
    snapshot = build_snapshot(
        [_record("R1", "Q355B", Rm=470)],
        document_id="doc-1",
        document_version=1,
        run_id="run-1",
    )
    changed = diff_against_snapshot(
        snapshot, [_record("R1", "Q355B", Rm=470, A=21)]
    )
    assert changed == []


def test_diff_without_snapshot_is_empty() -> None:
    assert diff_against_snapshot(None, [_record("R1", "Q355B", Rm=470)]) == []
    empty = AcceptedSnapshot(document_id="doc-1", run_id="run-1")
    assert diff_against_snapshot(empty, [_record("R1", "Q355B", Rm=470)]) == []


def test_patch_chain_inherits_only_from_same_base() -> None:
    assert next_patch_chain(None, "", "fb-2", "1.4.0") == ["fb-2"]
    assert next_patch_chain(
        ["fb-1"], "1.4.1", "fb-2", "1.4.0"
    ) == ["fb-2"]
    assert next_patch_chain(
        ["fb-1"], "1.4.1", "fb-2", "1.4.1"
    ) == ["fb-1", "fb-2"]
