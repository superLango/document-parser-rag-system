"""Persist engine result artifacts into platform result tables.

The artifact files stay the source of truth; these tables make results
queryable by document/version without walking job directories on every read.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .models import (
    Document,
    DocumentClause,
    DocumentItem,
    DocumentRecord,
    EvidenceIndex,
    utcnow,
)

TERMINAL_STATUSES = {"succeeded", "review"}
logger = logging.getLogger(__name__)


def _dedupe(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for row in rows:
        value = str(row.get(key) or "")
        if value in seen:
            continue
        seen.add(value)
        unique.append(row)
    return unique


def _read_json(root: Path, names: tuple[str, ...]) -> dict[str, Any]:
    for name in names:
        path = root / name
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    raise FileNotFoundError(f"missing artifacts: {', '.join(names)}")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rows.append(json.loads(line))
    return rows


def _text(value: Any, limit: int = 255) -> str | None:
    if value is None:
        return None
    return str(value)[:limit]


def _sync_identity(document: Document, metadata: dict[str, Any]) -> None:
    """Backfill standard number/title from the engine's document metadata.

    Uploads are stored under a hash name, so the platform row is created with
    no standard number and a hash title. The engine recovers both from the
    cover page; copy them once results are synced.
    """

    standard_no = _text(metadata.get("standard_no"), 64)
    if standard_no and not document.standard_no:
        document.standard_no = standard_no
    title = _text(metadata.get("title"))
    current = (document.title or "").strip()
    generated = (
        not current
        or current == Path(document.file_name).stem
        or bool(re.fullmatch(r"[0-9a-f]{16,}", current))
    )
    if title and generated:
        document.title = title


def _sync_scope(db: Session, document_id: str, job_id: str) -> None:
    for model in (DocumentItem, DocumentRecord, DocumentClause, EvidenceIndex):
        db.execute(
            delete(model).where(
                model.document_id == document_id, model.job_id == job_id
            )
        )


def sync_results(
    db: Session, document: Document, state: Any
) -> dict[str, Any]:
    """Replace the stored result index for the job that produced ``state``."""

    root = Path(state.out_dir)
    inventory = _read_json(
        root, ("item_inventory_aligned.json", "item_inventory.json")
    )
    result = _read_json(root, ("result.json",))
    clauses = _read_jsonl(root / "clauses.jsonl")
    evidence = _dedupe(_read_jsonl(root / "evidence.jsonl"), "evidence_id")
    version = document.review_version or 1

    _sync_scope(db, document.id, state.job_id)

    items = [
        DocumentItem(
            document_id=document.id,
            job_id=state.job_id,
            version=version,
            item_index=index,
            item_raw=_text(item.get("item_raw"), 255) or "",
            item_canonical=_text(item.get("item_canonical")),
            item_family=_text(item.get("item_family"), 64) or "",
            facets=item.get("facets") or {},
            properties=item.get("properties") or [],
            property_matches=item.get("property_matches") or [],
            business_code=_text(item.get("business_code"), 64),
            business_name=_text(item.get("business_name")),
            business_category_code=_text(
                item.get("business_category_code"), 64
            ),
            business_category_name=_text(item.get("business_category_name")),
            match_type=_text(item.get("match_type"), 32),
            method_standard=_text(item.get("method_standard")),
            method_code=_text(item.get("method_code"), 64),
            method_name=_text(item.get("method_name")),
            status=_text(item.get("status"), 32) or "",
        )
        for index, item in enumerate(inventory.get("items") or [])
    ]
    db.add_all(items)

    records = [
        DocumentRecord(
            document_id=document.id,
            job_id=state.job_id,
            version=version,
            record_id=_text(record.get("record_id")) or "",
            source_table_id=_text(record.get("source_table_id"), 64),
            grade=_text(record.get("grade"), 128),
            grade_level=_text(record.get("grade_level"), 64),
            condition=_text(record.get("condition")),
            facets=record.get("facets") or {},
            properties=record.get("properties") or {},
        )
        for record in _dedupe(list(result.get("records") or []), "record_id")
    ]
    db.add_all(records)

    clause_rows = [
        DocumentClause(
            document_id=document.id,
            job_id=state.job_id,
            version=version,
            clause_id=_text(clause.get("clause_id")) or "",
            title=_text(clause.get("title")),
            page_no=clause.get("page_no"),
            kind=_text(clause.get("kind"), 64) or "",
            fields=clause.get("fields") or {},
            applies_to=clause.get("applies_to") or [],
            evidence=clause.get("evidence") or [],
            status=_text(clause.get("status"), 32) or "",
        )
        for clause in _dedupe(clauses, "clause_id")
    ]
    db.add_all(clause_rows)

    evidence_rows = [
        EvidenceIndex(
            document_id=document.id,
            job_id=state.job_id,
            version=version,
            evidence_id=_text(row.get("evidence_id")) or "",
            page_no=int(row.get("page_no") or 0),
            table_id=_text(row.get("table_id"), 64),
            row=row.get("row"),
            col=row.get("col"),
            quote_text=str(row.get("quote") or ""),
            bbox=row.get("bbox"),
            artifact_uri=_text(row.get("artifact_uri")),
        )
        for row in evidence
    ]
    db.add_all(evidence_rows)

    _sync_identity(document, result.get("document") or {})
    if state.status in TERMINAL_STATUSES:
        # The task state is authoritative; the row used to stay "queued"
        # after a manual requeue even though the job had finished.
        document.status = state.status
    document.results_job_id = state.job_id
    document.results_synced_at = utcnow()
    db.flush()
    return {
        "job_id": state.job_id,
        "version": version,
        "items": len(items),
        "records": len(records),
        "clauses": len(clause_rows),
        "evidence": len(evidence_rows),
        "synced_at": document.results_synced_at.isoformat(),
    }


def ensure_results_synced(
    db: Session, document: Document, state: Any
) -> bool:
    """Sync terminal results once per job; callers fall back to artifacts."""

    if state.status not in TERMINAL_STATUSES:
        return document.results_job_id == state.job_id
    if document.results_job_id == state.job_id:
        return True
    try:
        sync_results(db, document, state)
    except FileNotFoundError:
        return False
    except Exception:  # noqa: BLE001 - artifacts remain the source of truth
        db.rollback()
        logger.warning(
            "result index sync failed for %s/%s",
            document.id,
            state.job_id,
            exc_info=True,
        )
        return False
    db.commit()
    return True


def items_payload(db: Session, document: Document, state: Any) -> dict[str, Any]:
    rows = (
        db.execute(
            select(DocumentItem)
            .where(
                DocumentItem.document_id == document.id,
                DocumentItem.job_id == state.job_id,
            )
            .order_by(DocumentItem.item_index)
        )
        .scalars()
        .all()
    )
    coverage: dict[str, Any] = {}
    unknown: list[Any] = []
    try:
        inventory = _read_json(
            Path(state.out_dir),
            ("item_inventory_aligned.json", "item_inventory.json"),
        )
        coverage = inventory.get("coverage") or {}
        unknown = inventory.get("unknown_candidates") or []
    except FileNotFoundError:
        coverage = {}
        unknown = []
    return {
        "doc_id": document.id,
        "items": [
            {
                "item_raw": row.item_raw,
                "item_canonical": row.item_canonical,
                "item_family": row.item_family,
                "facets": row.facets or {},
                "properties": row.properties or [],
                "property_matches": row.property_matches or [],
                "business_code": row.business_code,
                "business_name": row.business_name,
                "business_category_code": row.business_category_code,
                "business_category_name": row.business_category_name,
                "match_type": row.match_type,
                "method_standard": row.method_standard,
                "method_code": row.method_code,
                "method_name": row.method_name,
                "status": row.status,
            }
            for row in rows
        ],
        "coverage": coverage,
        "unknown_candidates": unknown,
    }


def records_payload(
    db: Session, document: Document, state: Any
) -> list[dict[str, Any]]:
    rows = (
        db.execute(
            select(DocumentRecord)
            .where(
                DocumentRecord.document_id == document.id,
                DocumentRecord.job_id == state.job_id,
            )
            .order_by(DocumentRecord.record_id)
        )
        .scalars()
        .all()
    )
    return [
        {
            "record_id": row.record_id,
            "source_table_id": row.source_table_id,
            "grade": row.grade,
            "grade_level": row.grade_level,
            "condition": row.condition,
            "facets": row.facets or {},
            "properties": row.properties or {},
        }
        for row in rows
    ]


def clauses_payload(
    db: Session, document: Document, state: Any
) -> list[dict[str, Any]]:
    rows = (
        db.execute(
            select(DocumentClause)
            .where(
                DocumentClause.document_id == document.id,
                DocumentClause.job_id == state.job_id,
            )
            .order_by(DocumentClause.clause_id)
        )
        .scalars()
        .all()
    )
    return [
        {
            "clause_id": row.clause_id,
            "title": row.title,
            "page_no": row.page_no,
            "kind": row.kind,
            "fields": row.fields or {},
            "applies_to": row.applies_to or [],
            "evidence": row.evidence or [],
            "status": row.status,
        }
        for row in rows
    ]


def evidence_payload(
    db: Session, document: Document, state: Any, limit: int
) -> list[dict[str, Any]]:
    rows = (
        db.execute(
            select(EvidenceIndex)
            .where(
                EvidenceIndex.document_id == document.id,
                EvidenceIndex.job_id == state.job_id,
            )
            .order_by(EvidenceIndex.page_no, EvidenceIndex.evidence_id)
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return [
        {
            "evidence_id": row.evidence_id,
            "page_no": row.page_no,
            "table_id": row.table_id,
            "row": row.row,
            "col": row.col,
            "quote": row.quote_text,
            "bbox": row.bbox,
            "artifact_uri": row.artifact_uri,
        }
        for row in rows
    ]


def evidence_row_payload(row: EvidenceIndex) -> dict[str, Any]:
    return {
        "evidence_id": row.evidence_id,
        "page_no": row.page_no,
        "table_id": row.table_id,
        "row": row.row,
        "col": row.col,
        "quote": row.quote_text,
        "bbox": row.bbox,
        "artifact_uri": row.artifact_uri,
    }


def find_evidence(
    db: Session, document: Document, state: Any, evidence_id: str
) -> dict[str, Any] | None:
    row = db.scalar(
        select(EvidenceIndex).where(
            EvidenceIndex.document_id == document.id,
            EvidenceIndex.job_id == state.job_id,
            EvidenceIndex.evidence_id == evidence_id,
        )
    )
    return evidence_row_payload(row) if row is not None else None
