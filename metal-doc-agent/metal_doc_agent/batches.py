"""Batch store for the bulk API (M3.4-01).

A batch is a named group of jobs. Status is derived from the job store on read,
so a batch never lies about its children, and ``idempotency_key`` makes retries
safe.
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from pydantic import Field

from .contracts import Artifact, Contract
from .jobs import JobStore


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class BatchItem(Contract):
    job_id: str
    source_name: str | None = None
    path: str | None = None
    lane: str = "production"


class BatchState(Artifact):
    batch_id: str
    status: str = "queued"
    created_at: str
    updated_at: str
    idempotency_key: str | None = None
    items: list[BatchItem] = Field(default_factory=list)
    summary: dict[str, int] = Field(default_factory=dict)


class BatchStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _path(self, batch_id: str) -> Path:
        if not batch_id.isalnum():
            raise ValueError(f"invalid batch id: {batch_id}")
        return self.root / f"{batch_id}.json"

    def _index_path(self) -> Path:
        return self.root / "index.json"

    def _load_index(self) -> dict[str, str]:
        if not self._index_path().exists():
            return {}
        try:
            data = json.loads(self._index_path().read_text(encoding="utf-8"))
        except ValueError:
            return {}
        return {str(key): str(value) for key, value in data.items()}

    def _save_index(self, index: dict[str, str]) -> None:
        self._index_path().write_text(
            json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    def find(self, idempotency_key: str) -> BatchState | None:
        batch_id = self._load_index().get(idempotency_key)
        return self.get(batch_id) if batch_id else None

    def create(
        self,
        items: list[dict],
        *,
        idempotency_key: str | None = None,
    ) -> tuple[BatchState, bool]:
        with self._lock:
            if idempotency_key:
                existing = self.find(idempotency_key)
                if existing is not None:
                    return existing, False
            batch_id = uuid.uuid4().hex[:12]
            state = BatchState(
                batch_id=batch_id,
                created_at=_now(),
                updated_at=_now(),
                idempotency_key=idempotency_key,
                items=[BatchItem.model_validate(item) for item in items],
            )
            self.save(state)
            if idempotency_key:
                index = self._load_index()
                index[idempotency_key] = batch_id
                self._save_index(index)
            return state, True

    def save(self, state: BatchState) -> BatchState:
        state.updated_at = _now()
        self._path(state.batch_id).write_text(
            state.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
        return state

    def get(self, batch_id: str | None) -> BatchState | None:
        if not batch_id:
            return None
        path = self._path(batch_id)
        if not path.exists():
            return None
        try:
            return BatchState.model_validate(json.loads(path.read_text(encoding="utf-8")))
        except ValueError:
            return None

    def list(self, limit: int = 50) -> list[BatchState]:
        states: list[BatchState] = []
        for path in self.root.glob("*.json"):
            if path.name == "index.json":
                continue
            try:
                states.append(
                    BatchState.model_validate(json.loads(path.read_text(encoding="utf-8")))
                )
            except ValueError:
                continue
        states.sort(key=lambda item: item.created_at, reverse=True)
        return states[: max(0, limit)]

    def refresh(self, batch_id: str, jobs: JobStore) -> BatchState:
        state = self.get(batch_id)
        if state is None:
            raise KeyError(f"batch not found: {batch_id}")
        statuses: list[str] = []
        for item in state.items:
            job = jobs.get(item.job_id)
            statuses.append(job.status if job else "missing")
        counts: dict[str, int] = {}
        for status in statuses:
            counts[status] = counts.get(status, 0) + 1
        state.summary = counts
        state.status = aggregate_status(statuses)
        self.save(state)
        return state


def aggregate_status(statuses: list[str]) -> str:
    if not statuses:
        return "queued"
    if "failed" in statuses or "missing" in statuses:
        return "failed" if all(s in {"failed", "missing"} for s in statuses) else "partial"
    if any(status in {"queued", "running"} for status in statuses):
        return "queued" if all(status == "queued" for status in statuses) else "running"
    if "review" in statuses:
        return "review" if all(status == "review" for status in statuses) else "partial"
    return "succeeded"
