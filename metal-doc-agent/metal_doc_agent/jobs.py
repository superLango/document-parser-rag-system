"""Persistent job store backed by the filesystem artifact layout."""

from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .contracts import JobState
from .storage import ArtifactStore

JOB_ID_RE = re.compile(r"^[A-Za-z0-9_-]{4,64}$")
LANES = ("production", "explore", "human")
INDEX_NAME = "index.json"
CLAIM_NAME = ".runner.lock"
TERMINAL_STATUSES = {"succeeded", "failed", "review"}
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "queued": {"running"},
    "running": {"succeeded", "review", "failed"},
    "failed": {"queued"},
    "review": {"queued"},
    "succeeded": set(),
}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class JobStore:
    """Filesystem job store; enough for single-node M1, replaceable by Postgres."""

    def __init__(self, root: str | Path, *, stale_seconds: float = 300.0) -> None:
        self.root = Path(root).resolve()
        self.store = ArtifactStore(self.root)
        self.stale_seconds = stale_seconds
        self._lock = threading.RLock()

    @staticmethod
    def new_job_id() -> str:
        return uuid.uuid4().hex[:12]

    def _validate_id(self, job_id: str) -> str:
        if not JOB_ID_RE.match(job_id):
            raise ValueError(f"invalid job id: {job_id}")
        return job_id

    def _state_path(self, job_id: str) -> str:
        return f"{self._validate_id(job_id)}/state.json"

    def _load_index(self) -> dict[str, str]:
        if not (self.root / INDEX_NAME).exists():
            return self._rebuild_index()
        try:
            data = self.store.read_json(INDEX_NAME)
        except (ValueError, OSError):
            return self._rebuild_index()
        if not isinstance(data, dict):
            return self._rebuild_index()
        return {str(key): str(value) for key, value in data.items() if isinstance(value, str)}

    def _save_index(self, index: dict[str, str]) -> None:
        self.store.write_json(INDEX_NAME, index)

    def _rebuild_index(self) -> dict[str, str]:
        index: dict[str, str] = {}
        for path in sorted(self.root.glob("*/state.json")):
            try:
                state = JobState.model_validate(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
            if state.idempotency_key:
                index[state.idempotency_key] = state.job_id
        self._save_index(index)
        return index

    def find(self, idempotency_key: str) -> JobState | None:
        with self._lock:
            job_id = self._load_index().get(idempotency_key)
        return self.get(job_id) if job_id else None

    def reserve(
        self,
        *,
        job_id: str | None = None,
        idempotency_key: str,
        source_name: str,
        source_sha256: str,
        doc_path: str,
        options: dict[str, str],
        lane: str = "production",
    ) -> tuple[JobState, bool]:
        """Create a job or return the existing one for the same key."""
        if lane not in LANES:
            raise ValueError(f"invalid lane: {lane}")
        with self._lock:
            index = self._load_index()
            existing = index.get(idempotency_key)
            if existing:
                state = self.get(existing)
                if state is not None:
                    return state, False
                index.pop(idempotency_key, None)
            job_id = self._validate_id(job_id or self.new_job_id())
            out_dir = self.root / job_id
            now = _now()
            state = JobState(
                job_id=job_id,
                lane=lane,
                status="queued",
                stage="created",
                doc_path=str(doc_path),
                out_dir=str(out_dir),
                created_at=now,
                updated_at=now,
                idempotency_key=idempotency_key,
                source_name=source_name,
                source_sha256=source_sha256,
                options=dict(options),
            )
            self.save(state)
            index[idempotency_key] = job_id
            self._save_index(index)
            return state, True

    def save(self, state: JobState) -> JobState:
        with self._lock:
            now = _now()
            state.updated_at = now
            if state.status in TERMINAL_STATUSES and not state.finished_at:
                state.finished_at = now
            self.store.write_json(self._state_path(state.job_id), state)
            return state

    def get(self, job_id: str | None) -> JobState | None:
        if not job_id:
            return None
        try:
            data = self.store.read_json(self._state_path(job_id))
        except (FileNotFoundError, ValueError):
            return None
        try:
            return JobState.model_validate(data)
        except ValueError:
            return None

    def _claim_path(self, job_id: str) -> Path:
        return self.root / self._validate_id(job_id) / CLAIM_NAME

    def claim(self, job_id: str) -> JobState | None:
        """Atomically take ownership of a queued job.

        The marker is created with ``O_EXCL`` so multiple worker processes
        sharing the same store cannot run the same job twice.
        """

        with self._lock:
            path = self._claim_path(job_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            if not self._create_marker(path):
                if not self._marker_stale(path):
                    return None
                self._recover_stale_job(job_id)
                if not self._create_marker(path):
                    return None
            state = self.get(job_id)
            if state is None:
                self.release_claim(job_id)
                raise KeyError(f"job not found: {job_id}")
            if state.status != "queued":
                self.release_claim(job_id)
                return None
            try:
                return self.update(
                    job_id,
                    status="running",
                    stage="starting",
                    progress=1,
                    error=None,
                    finished_at=None,
                    attempts=state.attempts + 1,
                )
            except Exception:
                self.release_claim(job_id)
                raise

    def _create_marker(self, path: Path) -> bool:
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return False
        try:
            os.write(fd, str(os.getpid()).encode("ascii"))
        finally:
            os.close(fd)
        return True

    def _marker_stale(self, path: Path) -> bool:
        if not path.exists():
            return True
        try:
            return time.time() - path.stat().st_mtime > self.stale_seconds
        except OSError:
            return False

    def _recover_stale_job(self, job_id: str) -> None:
        try:
            self._claim_path(job_id).unlink()
        except FileNotFoundError:
            pass
        state = self.get(job_id)
        if state is None or state.status != "running":
            return
        data = state.model_dump()
        data.update(
            status="queued",
            stage="retry",
            progress=0,
            error="stale runner recovered",
            finished_at=None,
        )
        self.save(JobState.model_validate(data))

    def recover_stale_running(self) -> list[str]:
        recovered: list[str] = []
        with self._lock:
            for state in self.list(limit=1000):
                if state.status != "running":
                    continue
                path = self._claim_path(state.job_id)
                if not path.exists() or self._marker_stale(path):
                    self._recover_stale_job(state.job_id)
                    recovered.append(state.job_id)
        return recovered

    def touch_claim(self, job_id: str) -> None:
        path = self._claim_path(job_id)
        if path.exists():
            try:
                os.utime(path, None)
            except OSError:
                pass

    def release_claim(self, job_id: str) -> None:
        try:
            self._claim_path(job_id).unlink()
        except FileNotFoundError:
            pass

    def update(self, job_id: str, **changes: object) -> JobState:
        with self._lock:
            state = self.get(job_id)
            if state is None:
                raise KeyError(f"job not found: {job_id}")
            if "status" in changes:
                target = str(changes["status"])
                if target != state.status and target not in ALLOWED_TRANSITIONS.get(
                    state.status, set()
                ):
                    raise ValueError(
                        f"invalid job transition: {state.status} -> {target}"
                    )
            data = state.model_dump()
            data.update(changes)
            updated = JobState.model_validate(data)
            saved = self.save(updated)
            self.touch_claim(job_id)
            return saved

    def list(self, limit: int = 100, lane: str | None = None) -> list[JobState]:
        if lane is not None and lane not in LANES:
            raise ValueError(f"invalid lane: {lane}")
        states: list[JobState] = []
        for path in self.root.glob("*/state.json"):
            try:
                state = JobState.model_validate(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
            if lane is not None and state.lane != lane:
                continue
            states.append(state)
        states.sort(key=lambda item: item.created_at or "", reverse=True)
        return states[: max(0, limit)]

    def reset_for_retry(self, job_id: str) -> JobState:
        with self._lock:
            state = self.get(job_id)
            if state is None:
                raise KeyError(f"job not found: {job_id}")
            if state.status == "running":
                raise RuntimeError("job is running")
            if state.status not in {"failed", "review", "queued"}:
                raise RuntimeError(f"job status {state.status} cannot be retried")
            return self.update(
                job_id,
                status="queued",
                stage="retry",
                progress=0,
                error=None,
                failure_code=None,
                finished_at=None,
            )
