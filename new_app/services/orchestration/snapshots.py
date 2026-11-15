"""已验收快照：记录用户确认过的文档结果，用于增量修复时保护已验收区域。"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from hanson_contracts import AcceptedSnapshot, VerificationPackage
from sqlalchemy import select

from .db import SessionLocal
from .models import AcceptedSnapshot as AcceptedSnapshotRow
from .models import Artifact as ArtifactRow
from .models import Run as RunRow
from .simulation import reject_simulated


def _canonical(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(payload: Any) -> str:
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def field_key(record: dict[str, Any], name: str) -> str:
    return f"{record.get('table_id') or ''}:{record.get('grade') or ''}:{name}"


def field_digests(records: list[dict[str, Any]]) -> dict[str, str]:
    digests: dict[str, str] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        for name, value in (record.get("properties") or {}).items():
            if not isinstance(value, dict):
                continue
            digests[field_key(record, name)] = _digest(value)
    return dict(sorted(digests.items()))


def records_digest(records: list[dict[str, Any]]) -> str:
    normalized = [
        {
            "table_id": item.get("table_id"),
            "grade": item.get("grade"),
            "record_id": item.get("record_id"),
            "properties": item.get("properties") or {},
        }
        for item in records
        if isinstance(item, dict)
    ]
    normalized.sort(
        key=lambda item: (
            str(item["table_id"]),
            str(item["grade"]),
            str(item["record_id"]),
        )
    )
    return _digest(normalized)


def accepted_scope(records: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    tables = sorted(
        {
            str(item.get("table_id"))
            for item in records
            if isinstance(item, dict) and item.get("table_id")
        }
    )
    return tables, sorted(field_digests(records))


def diff_against_snapshot(
    snapshot: AcceptedSnapshot | None, records: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """已验收字段中发生值变化或消失的部分，需要用户重新确认。"""
    if snapshot is None or not snapshot.field_digests:
        return []
    current = field_digests(records)
    changed: list[dict[str, Any]] = []
    for key, previous in snapshot.field_digests.items():
        if key not in current:
            changed.append({"field": key, "change": "missing", "before": previous})
        elif current[key] != previous:
            changed.append(
                {
                    "field": key,
                    "change": "changed",
                    "before": previous,
                    "after": current[key],
                }
            )
    return changed


def next_patch_chain(
    previous_patch_chain: list[str] | None,
    previous_version: str,
    feedback_id: str,
    base_version: str,
) -> list[str]:
    if previous_patch_chain is not None and previous_version == base_version:
        return [*previous_patch_chain, feedback_id]
    return [feedback_id]


def build_snapshot(
    records: list[dict[str, Any]],
    *,
    document_id: str,
    document_version: int,
    run_id: str,
    feedback_id: str | None = None,
    actor: str = "operator",
) -> AcceptedSnapshot:
    tables, fields = accepted_scope(records)
    return AcceptedSnapshot(
        document_id=document_id,
        document_version=document_version,
        run_id=run_id,
        feedback_id=feedback_id,
        records=len(records),
        records_digest=records_digest(records),
        accepted_tables=tables,
        accepted_fields=fields,
        field_digests=field_digests(records),
        actor=actor,
        created_at=_now(),
    )


def _row_to_contract(row: AcceptedSnapshotRow) -> AcceptedSnapshot:
    return AcceptedSnapshot(
        document_id=row.document_id,
        document_version=row.document_version,
        run_id=row.run_id,
        feedback_id=row.feedback_id,
        records=row.records,
        records_digest=row.records_digest,
        accepted_tables=list(row.accepted_tables or []),
        accepted_fields=list(row.accepted_fields or []),
        field_digests=dict(row.field_digests or {}),
        actor=row.actor,
        created_at=row.created_at.isoformat() if row.created_at else "",
    )


async def _latest_row(session: Any, document_id: str) -> AcceptedSnapshotRow | None:
    result = await session.execute(
        select(AcceptedSnapshotRow)
        .where(AcceptedSnapshotRow.document_id == document_id)
        .order_by(AcceptedSnapshotRow.created_at.desc())
    )
    return result.scalars().first()


async def latest_snapshot(document_id: str) -> AcceptedSnapshot | None:
    async with SessionLocal() as session:
        row = await _latest_row(session, document_id)
    return _row_to_contract(row) if row is not None else None


async def _insert_snapshot(snapshot: AcceptedSnapshot) -> AcceptedSnapshot:
    async with SessionLocal() as session:
        existing = await session.execute(
            select(AcceptedSnapshotRow).where(
                AcceptedSnapshotRow.document_id == snapshot.document_id,
                AcceptedSnapshotRow.records_digest == snapshot.records_digest,
            )
        )
        row = existing.scalars().first()
        if row is None:
            row = AcceptedSnapshotRow(
                document_id=snapshot.document_id,
                document_version=snapshot.document_version,
                run_id=snapshot.run_id,
                feedback_id=snapshot.feedback_id,
                records=snapshot.records,
                records_digest=snapshot.records_digest,
                accepted_tables=snapshot.accepted_tables,
                accepted_fields=snapshot.accepted_fields,
                field_digests=snapshot.field_digests,
                actor=snapshot.actor,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
    return _row_to_contract(row)


async def save_snapshot(
    records: list[dict[str, Any]],
    *,
    document_id: str,
    document_version: int,
    run_id: str,
    feedback_id: str | None = None,
    actor: str = "operator",
) -> AcceptedSnapshot:
    snapshot = build_snapshot(
        records,
        document_id=document_id,
        document_version=document_version,
        run_id=run_id,
        feedback_id=feedback_id,
        actor=actor,
    )
    return await _insert_snapshot(snapshot)


async def save_snapshot_from_verification(
    verification: VerificationPackage,
    *,
    document_id: str,
    document_version: int,
    run_id: str,
    feedback_id: str | None,
    actor: str,
) -> AcceptedSnapshot:
    snapshot = AcceptedSnapshot(
        document_id=document_id,
        document_version=document_version,
        run_id=run_id,
        feedback_id=feedback_id,
        records=verification.record_count,
        records_digest=verification.records_digest,
        accepted_tables=list(verification.accepted_tables),
        accepted_fields=list(verification.accepted_fields),
        field_digests=dict(verification.field_digests),
        actor=actor,
        created_at=_now(),
    )
    return await _insert_snapshot(snapshot)


async def capture_run_snapshot(run_id: str, actor: str = "operator") -> AcceptedSnapshot:
    """把某次 run 的结果登记为已验收快照（用户确认解析结果时调用）。"""
    from .workflow import get_store

    async with SessionLocal() as session:
        run = await session.get(RunRow, run_id)
        if run is None:
            raise ValueError("run not found")
        result = await session.execute(
            select(ArtifactRow)
            .where(
                ArtifactRow.run_id == run_id,
                ArtifactRow.role.in_(("ocr", "records", "result")),
            )
            .order_by(ArtifactRow.created_at.desc())
        )
        artifacts = list(result.scalars())
    records_artifact = next((item for item in artifacts if item.role == "records"), None)
    if records_artifact is None:
        raise ValueError("records not ready")

    store = get_store()
    for item in artifacts:
        if item.role == "records":
            continue
        raw = await store.get_bytes(item.storage_key)
        try:
            payload = json.loads(raw)
        except ValueError:
            continue
        reject_simulated(payload, role=item.role)

    data = await store.get_bytes(records_artifact.storage_key)
    payload = json.loads(data)
    reject_simulated(payload, role="records")
    records = payload.get("records") if isinstance(payload, dict) else None
    if not isinstance(records, list):
        raise ValueError("records not ready")
    return await save_snapshot(
        records,
        document_id=run.document_id,
        document_version=run.document_version,
        run_id=run_id,
        actor=actor,
    )
