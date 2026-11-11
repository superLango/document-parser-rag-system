"""Parent-side helpers for isolated execution.

The worker never imports and runs the parsing pipeline in its own process.
Instead it spawns :mod:`metal_doc_agent.sandbox_run`, which loads the current
source tree. This is what makes a self-heal patch effective for the next job
without a container restart, and it keeps one bad job from killing the worker.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from .settings import Settings

SKIP_ENV_PREFIXES = ("SELFHEAL_", "HANSON_SECRET")
SKIP_ENV_KEYS = {"HANSON_DATABASE_URL"}
# Import root of this package; independent of the config project_root, which
# may point at an overlay copy that has no Python code.
CODE_ROOT = Path(__file__).resolve().parents[1]


def sandbox_enabled(settings: Settings) -> bool:
    return bool(getattr(settings, "sandbox", True))


def child_env() -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in SKIP_ENV_KEYS
        and not any(key.startswith(prefix) for prefix in SKIP_ENV_PREFIXES)
    }
    env["PYTHONUNBUFFERED"] = "1"
    env["METAL_DOC_SANDBOX_CHILD"] = "1"
    return env


def _settings_payload(settings: Settings) -> dict[str, Any]:
    return {
        "project_root": str(settings.project_root),
        "data_dir": str(settings.data_dir),
        "ocr_backend": settings.ocr_backend,
        "extractor_backend": settings.extractor_backend,
        "business_dictionary_path": settings.business_dictionary_path,
        "business_dictionary_override_path": settings.business_dictionary_override_path,
        "dictionary_category_mode": settings.dictionary_category_mode,
        "business_alignment": settings.business_alignment,
        "recipe_routing": settings.recipe_routing,
        "orchestrate": settings.orchestrate,
    }


def _spawn(payload: dict[str, Any], settings: Settings) -> subprocess.CompletedProcess:
    timeout = getattr(settings, "sandbox_timeout", 0.0) or None
    env = child_env()
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        f"{CODE_ROOT}{os.pathsep}{existing}" if existing else str(CODE_ROOT)
    )
    return subprocess.run(
        [sys.executable, "-m", "metal_doc_agent.sandbox_run"],
        input=json.dumps(payload, ensure_ascii=False),
        text=True,
        capture_output=True,
        cwd=str(CODE_ROOT),
        env=env,
        timeout=timeout,
        check=False,
    )


def run_pipeline_sandbox(
    settings: Settings,
    source: str | Path,
    out_dir: str | Path,
    *,
    coverage_template: str = "product_full",
) -> tuple[bool, str]:
    """Run one pipeline in a fresh interpreter; returns ``(ok, detail)``."""

    payload = {
        "kind": "pipeline",
        "source": str(source),
        "out_dir": str(out_dir),
        "coverage_template": coverage_template,
        "settings": _settings_payload(settings),
    }
    try:
        completed = _spawn(payload, settings)
    except subprocess.TimeoutExpired:
        return False, f"沙箱执行超时（{settings.sandbox_timeout:.0f}s）"
    if completed.returncode == 0:
        return True, "sandbox ok"
    detail = (completed.stderr or completed.stdout or "").strip()
    return False, detail[-800:] or f"沙箱子进程退出码 {completed.returncode}"


def run_job_sandbox(
    settings: Settings,
    store_root: str | Path,
    job_id: str,
    *,
    stale_seconds: float = 300.0,
) -> tuple[bool, str]:
    payload = {
        "kind": "job",
        "job_id": job_id,
        "store_root": str(store_root),
        "stale_seconds": stale_seconds,
        "settings": _settings_payload(settings),
    }
    try:
        completed = _spawn(payload, settings)
    except subprocess.TimeoutExpired:
        return False, f"沙箱执行超时（{settings.sandbox_timeout:.0f}s）"
    if completed.returncode == 0:
        return True, "sandbox ok"
    detail = (completed.stderr or completed.stdout or "").strip()
    return False, detail[-800:] or f"沙箱子进程退出码 {completed.returncode}"
