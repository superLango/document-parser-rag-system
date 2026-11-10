"""Prometheus metrics and readiness checks (M5.1-03).

Text exposition only: no third-party client is required, so the same helper
works in the engine API, the platform API and offline tools. Every metric
family emits one HELP/TYPE block; the pipeline latency histogram is rebuilt
from per-job ``metrics.json`` sidecars written by the runner.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .jobs import JobStore
from .queues import QueueStore

HELP = {
    "engine_jobs": ("Number of engine jobs by status", "gauge"),
    "engine_queue_items": ("Queued documents by lane", "gauge"),
    "engine_feedback_events": ("Feedback events available for training", "gauge"),
    "engine_pipeline_seconds": ("End-to-end pipeline duration in seconds", "histogram"),
    "platform_documents": ("Platform documents by review status", "gauge"),
    "platform_field_review_events": ("Field review events by action", "gauge"),
    "platform_errors_total": ("Platform error responses by status and route", "counter"),
}

HISTOGRAM_BUCKETS = (60, 120, 300, 600)


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _labels(labels: dict[str, str] | None) -> str:
    if not labels:
        return ""
    pairs = ",".join(f'{key}="{_escape(str(val))}"' for key, val in sorted(labels.items()))
    return f"{{{pairs}}}"


def render_family(name: str, samples: list[tuple[dict[str, str] | None, float]]) -> list[str]:
    text, kind = HELP.get(name, ("", "gauge"))
    lines = [f"# HELP {name} {text}", f"# TYPE {name} {kind}"]
    for labels, value in samples:
        lines.append(f"{name}{_labels(labels)} {value:g}")
    return lines


def render_metric(name: str, labels: dict[str, str] | None = None, value: float = 0.0) -> list[str]:
    """Single-sample helper (kept for tools/tests); prefer ``render_family``."""
    return render_family(name, [(labels, value)])


def render_histogram(name: str, values: list[float]) -> list[str]:
    text, kind = HELP.get(name, ("", "histogram"))
    lines = [f"# HELP {name} {text}", f"# TYPE {name} {kind}"]
    total = len(values)
    for bucket in HISTOGRAM_BUCKETS:
        count = sum(1 for value in values if value <= bucket)
        lines.append(f'{name}_bucket{{le="{bucket}"}} {count}')
    lines.append(f'{name}_bucket{{le="+Inf"}} {total}')
    lines.append(f"{name}_sum {round(sum(values), 4):g}")
    lines.append(f"{name}_count {total}")
    return lines


def engine_metrics(
    store: JobStore,
    queue_dir: str | Path | None = None,
    *,
    feedback_path: str | Path | None = None,
) -> str:
    lines: list[str] = []
    states = store.list(limit=100000)
    counts: dict[str, int] = {}
    durations: list[float] = []
    for state in states:
        counts[state.status] = counts.get(state.status, 0) + 1
        duration = _job_duration(state.out_dir)
        if duration is not None:
            durations.append(duration)
    lines.extend(
        render_family(
            "engine_jobs",
            [
                ({"status": status}, counts.get(status, 0))
                for status in ("queued", "running", "succeeded", "review", "failed")
            ],
        )
    )
    if queue_dir is not None:
        queue_path = Path(queue_dir)
        stats = QueueStore(queue_path).stats() if queue_path.exists() else {}
        lines.extend(
            render_family(
                "engine_queue_items",
                [
                    ({"lane": lane}, stats.get(lane, 0))
                    for lane in ("production", "explore", "human")
                ],
            )
        )
    if feedback_path is not None and Path(feedback_path).exists():
        count = sum(
            1
            for line in Path(feedback_path).read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
        lines.extend(render_metric("engine_feedback_events", None, count))
    if durations:
        lines.extend(render_histogram("engine_pipeline_seconds", durations))
    return "\n".join(lines) + "\n"


def readiness(project_root: str | Path, data_dir: str | Path) -> dict:
    root = Path(project_root)
    data = Path(data_dir)
    checks = {
        "recipes_dir": (root / "configs" / "recipes").exists(),
        "coverage_templates": (root / "configs" / "coverage_templates.json").exists(),
        "data_dir_writable": _writable(data),
    }
    return {
        "status": "ok" if all(checks.values()) else "degraded",
        "checks": checks,
    }


def _job_duration(out_dir: str | None) -> float | None:
    if not out_dir:
        return None
    path = Path(out_dir) / "metrics.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    value = payload.get("pipeline_seconds")
    return float(value) if isinstance(value, (int, float)) else None


def _writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        handle, name = tempfile.mkstemp(prefix=".ready-", dir=str(path))
        os.close(handle)
        os.unlink(name)
        return True
    except OSError:
        return False
