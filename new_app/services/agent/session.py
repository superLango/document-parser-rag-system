"""SQLite-backed agent session store with checkpoint/resume support."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path

from hanson_contracts import AgentSession, AgentTask

SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_sessions (
    session_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    trace_id TEXT NOT NULL,
    role TEXT NOT NULL,
    status TEXT NOT NULL,
    task_json TEXT NOT NULL,
    state_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_agent_sessions_task ON agent_sessions(task_id);
CREATE INDEX IF NOT EXISTS idx_agent_sessions_status ON agent_sessions(status);
"""


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class SessionStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def create(self, task: AgentTask, prompt_id: str, prompt_hash: str) -> AgentSession:
        timestamp = now_iso()
        session = AgentSession(
            session_id=str(uuid.uuid4()),
            task_id=task.task_id,
            trace_id=task.trace_id,
            role=task.role,
            status="running",
            objective=task.objective,
            prompt_id=prompt_id,
            prompt_hash=prompt_hash,
            created_at=timestamp,
            updated_at=timestamp,
        )
        self.save(session, task)
        return session

    def save(self, session: AgentSession, task: AgentTask | None = None) -> None:
        timestamp = now_iso()
        session.updated_at = timestamp
        task_json = task.model_dump_json() if task is not None else None
        with self._lock:
            if task_json is None:
                row = self._conn.execute(
                    "SELECT task_json FROM agent_sessions WHERE session_id = ?",
                    (session.session_id,),
                ).fetchone()
                task_json = row[0] if row else "{}"
            self._conn.execute(
                """
                INSERT INTO agent_sessions
                    (session_id, task_id, trace_id, role, status, task_json,
                     state_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    status = excluded.status,
                    task_json = excluded.task_json,
                    state_json = excluded.state_json,
                    updated_at = excluded.updated_at
                """,
                (
                    session.session_id,
                    session.task_id,
                    session.trace_id,
                    session.role,
                    session.status,
                    task_json,
                    session.model_dump_json(),
                    session.created_at or timestamp,
                    timestamp,
                ),
            )
            self._conn.commit()

    def get(self, session_id: str) -> AgentSession | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT state_json FROM agent_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return AgentSession.model_validate_json(row[0])

    def get_task(self, session_id: str) -> AgentTask | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT task_json FROM agent_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None or not row[0]:
            return None
        try:
            return AgentTask.model_validate(json.loads(row[0]))
        except ValueError:
            return None

    def list_by_task(self, task_id: str) -> list[AgentSession]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT state_json FROM agent_sessions WHERE task_id = ? "
                "ORDER BY created_at",
                (task_id,),
            ).fetchall()
        return [AgentSession.model_validate_json(row[0]) for row in rows]
