"""JSON log formatter with a request/job context id."""

from __future__ import annotations

import contextvars
import json
import logging
from datetime import datetime, timezone
from typing import Any

_current_job_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "job_id", default=None
)


def bind_job(job_id: str) -> contextvars.Token[str | None]:
    return _current_job_id.set(job_id)


def reset_job(token: contextvars.Token[str | None]) -> None:
    _current_job_id.reset(token)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        job_id = _current_job_id.get()
        if job_id:
            payload["job_id"] = job_id
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
