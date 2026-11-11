"""Job artifact location helpers (read-only)."""

from __future__ import annotations

import json
from pathlib import Path

from ..contracts import DocumentResult
from .config import SelfHealSettings


def jobs_root(settings: SelfHealSettings) -> Path:
    return settings.data_dir / "jobs"


def locate_job_dir(settings: SelfHealSettings, job_id: str) -> Path | None:
    base = jobs_root(settings) / job_id
    if (base / "result.json").exists():
        return base
    state_path = base / "state.json"
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except ValueError:
            state = {}
        out_dir = state.get("out_dir") or state.get("out")
        if out_dir and (Path(out_dir) / "result.json").exists():
            return Path(out_dir)
    return None


def load_result(job_dir: str | Path) -> DocumentResult | None:
    path = Path(job_dir) / "result.json"
    if not path.exists():
        return None
    try:
        return DocumentResult.model_validate(
            json.loads(path.read_text(encoding="utf-8"))
        )
    except ValueError:
        return None


def load_trace(job_dir: str | Path) -> dict:
    path = Path(job_dir) / "trace.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return {}
