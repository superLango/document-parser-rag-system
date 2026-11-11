"""Filesystem artifact store.

The production plan uses MinIO/S3; the local framework uses a directory with the
same logical layout. Artifacts are written atomically and are JSON serializable.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Iterable

from pydantic import BaseModel


class ArtifactStore:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, relative: str) -> Path:
        candidate = (self.root / relative).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise ValueError(f"artifact path escapes store: {relative}") from exc
        candidate.parent.mkdir(parents=True, exist_ok=True)
        return candidate

    @staticmethod
    def _jsonable(value: Any) -> Any:
        if isinstance(value, BaseModel):
            return value.model_dump(mode="json")
        if isinstance(value, dict):
            return {k: ArtifactStore._jsonable(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [ArtifactStore._jsonable(v) for v in value]
        return value

    def write_json(self, relative: str, value: Any) -> Path:
        path = self.path(relative)
        payload = json.dumps(self._jsonable(value), ensure_ascii=False, indent=2)
        self._atomic_write(path, payload)
        return path

    def write_jsonl(self, relative: str, rows: Iterable[Any]) -> Path:
        path = self.path(relative)
        lines = [json.dumps(self._jsonable(row), ensure_ascii=False) for row in rows]
        self._atomic_write(path, "\n".join(lines) + ("\n" if lines else ""))
        return path

    def write_text(self, relative: str, text: str) -> Path:
        path = self.path(relative)
        self._atomic_write(path, text)
        return path

    def read_json(self, relative: str) -> Any:
        return json.loads(self.path(relative).read_text(encoding="utf-8"))

    def read_text(self, relative: str) -> str:
        return self.path(relative).read_text(encoding="utf-8")

    @staticmethod
    def _atomic_write(path: Path, text: str) -> None:
        fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
            # Windows can refuse the replace while a reader holds the target;
            # retry briefly instead of failing the job.
            for attempt in range(10):
                try:
                    os.replace(tmp_name, path)
                    return
                except PermissionError:
                    if attempt == 9:
                        raise
                    time.sleep(0.01 * (attempt + 1))
        finally:
            if os.path.exists(tmp_name):
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
