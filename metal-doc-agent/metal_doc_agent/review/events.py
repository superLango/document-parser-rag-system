"""Field-level review events and feedback store (M4.1-04, M4.2-01).

Events are append-only and human-owned. ``edit`` must carry a new value and a
reason, ``reject`` must carry a reason; ``accept`` is a no-op record used for
audit and first-pass metrics. Feedback datasets only take edit/reject with a
reason, so an unexplained click never reaches training.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from ..contracts import Contract

FIELD_PATH_RE = re.compile(
    r"records(?:\.|\[)(?P<record>[^.\]]+)(?:\]\.|\.)properties\.(?P<property>.+)"
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ReviewEvent(Contract):
    event_id: str = Field(default_factory=lambda: f"rev-{uuid.uuid4().hex[:12]}")
    doc_id: str
    job_id: str | None = None
    field_path: str
    action: Literal["accept", "edit", "reject"]
    old_value: dict[str, Any] = Field(default_factory=dict)
    new_value: dict[str, Any] | None = None
    reason: str = ""
    reviewer: str
    created_at: str = Field(default_factory=_now)

    @model_validator(mode="after")
    def _validate_action(self) -> "ReviewEvent":
        if self.action == "edit" and self.new_value is None:
            raise ValueError("edit requires new_value")
        if self.action in {"edit", "reject"} and not self.reason.strip():
            raise ValueError(f"{self.action} requires a reason")
        if not parse_field_path(self.field_path):
            raise ValueError(f"invalid field_path: {self.field_path}")
        return self


def parse_field_path(field_path: str) -> tuple[str, str] | None:
    match = FIELD_PATH_RE.match(field_path)
    if match is None:
        return None
    return match.group("record"), match.group("property")


def field_path_for(record_key: str, prop: str) -> str:
    return f"records.{record_key}.properties.{prop}"


class FeedbackStore:
    """JSONL feedback dataset: only edit/reject with a reason are accepted."""

    def __init__(self, root: str | Path) -> None:
        self.path = Path(root) / "feedback.jsonl"
        self.root = Path(root)

    def append(self, event: ReviewEvent) -> bool:
        if event.action == "accept" or not event.reason.strip():
            return False
        self.root.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(event.model_dump_json() + "\n")
        return True

    def append_many(self, events: list[ReviewEvent]) -> int:
        return sum(1 for event in events if self.append(event))

    def list(self, limit: int = 1000) -> list[ReviewEvent]:
        if not self.path.exists():
            return []
        rows: list[ReviewEvent] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rows.append(ReviewEvent.model_validate_json(line))
        return rows[-limit:]

    def export(self, events: list[ReviewEvent]) -> Path:
        return self.path


def latest_events(events: list[ReviewEvent]) -> dict[str, ReviewEvent]:
    """Keep the last event per field_path in input order (oldest first)."""
    latest: dict[str, ReviewEvent] = {}
    for event in events:
        latest[event.field_path] = event
    return latest


def apply_events(
    records: list[dict[str, Any]], events: list[ReviewEvent]
) -> list[dict[str, Any]]:
    """Overlay human edits/rejects on machine records (for read paths)."""
    latest = latest_events(events)
    output = [dict(record) for record in records]
    for index, record in enumerate(output):
        record_key = str(record.get("record_id") or "")
        properties = dict(record.get("properties") or {})
        for field_path, event in latest.items():
            parsed = parse_field_path(field_path)
            if parsed is None:
                continue
            record_part, prop = parsed
            if not _record_matches(record_part, index, record_key):
                continue
            if prop not in properties:
                continue
            value = dict(properties[prop]) if isinstance(properties[prop], dict) else {}
            if event.action == "edit" and event.new_value:
                value.update(event.new_value)
                value["reviewed"] = "edit"
            elif event.action == "reject":
                value["reviewed"] = "reject"
                value["reject_reason"] = event.reason
            properties[prop] = value
        record["properties"] = properties
    return output


def _record_matches(record_part: str, index: int, record_key: str) -> bool:
    if record_part.isdigit():
        return int(record_part) == index
    return record_part == record_key


def diff_records(
    machine_records: list[dict[str, Any]], events: list[ReviewEvent]
) -> list[dict[str, Any]]:
    """Machine vs human diff for the review workbench."""
    latest = latest_events(events)
    diffs: list[dict[str, Any]] = []
    for field_path, event in latest.items():
        parsed = parse_field_path(field_path)
        if parsed is None:
            continue
        record_part, prop = parsed
        record = _find_record(machine_records, record_part)
        old = (record.get("properties") or {}).get(prop) if record else None
        diffs.append(
            {
                "field_path": field_path,
                "record_id": str(record.get("record_id")) if record else record_part,
                "property": prop,
                "action": event.action,
                "machine": old,
                "human": event.new_value,
                "reason": event.reason,
                "reviewer": event.reviewer,
                "created_at": event.created_at,
                "changed": event.action == "edit"
                and (event.new_value or {}).get("value") != (old or {}).get("value"),
            }
        )
    return diffs


def _find_record(
    records: list[dict[str, Any]], record_part: str
) -> dict[str, Any] | None:
    if record_part.isdigit() and int(record_part) < len(records):
        return records[int(record_part)]
    for record in records:
        if str(record.get("record_id")) == record_part:
            return record
    return None


def events_from_payloads(payloads: list[dict[str, Any]]) -> list[ReviewEvent]:
    return [ReviewEvent.model_validate(payload) for payload in payloads]
