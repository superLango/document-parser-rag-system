"""File-backed three-lane queue (M2.5.2-03), an equivalent of Redis/Dramatiq.

Each lane is an append-only JSONL file; ``dequeue`` rewrites the file without the
first record. Single writer/reader process is assumed (the worker owns it).
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

LANES = ("production", "explore", "human")


class QueueStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _path(self, lane: str) -> Path:
        if lane not in LANES:
            raise ValueError(f"unknown lane: {lane}")
        return self.root / f"{lane}.jsonl"

    def enqueue(self, lane: str, item: dict) -> str:
        item_id = str(item.get("item_id") or uuid.uuid4().hex[:12])
        record = {
            **item,
            "item_id": item_id,
            "lane": lane,
            "queued_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        with self._lock:
            with self._path(lane).open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return item_id

    def peek(self, lane: str) -> dict | None:
        records = self.list(lane)
        return records[0] if records else None

    def dequeue(self, lane: str) -> dict | None:
        path = self._path(lane)
        with self._lock:
            records = self.list(lane)
            if not records:
                return None
            remaining = records[1:]
            with path.open("w", encoding="utf-8") as handle:
                for record in remaining:
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return records[0]

    def list(self, lane: str) -> list[dict]:
        path = self._path(lane)
        if not path.exists():
            return []
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def stats(self) -> dict[str, int]:
        return {lane: len(self.list(lane)) for lane in LANES}


def fallback_to_explore(store: QueueStore, item: dict, reason: str) -> str:
    """M2.5.2-04: a production failure must never block; requeue to explore."""
    return store.enqueue(
        "explore",
        {**item, "fallback_from": item.get("lane", "production"), "fallback_reason": reason},
    )
