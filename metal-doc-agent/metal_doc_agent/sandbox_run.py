"""Execute one extraction unit in a fresh interpreter.

Each job runs in its own child process, which imports the current on-disk rule
code. A self-heal patch therefore takes effect for the next job without
restarting any long-running service, and a crashed job cannot take the worker
down with it.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

from .jobs import JobStore
from .pipeline import run_pipeline
from .runner import run_job
from .settings import Settings

OVERRIDE_FIELDS = (
    "ocr_backend",
    "extractor_backend",
    "business_dictionary_path",
    "business_dictionary_override_path",
    "dictionary_category_mode",
    "business_alignment",
    "recipe_routing",
    "orchestrate",
)


def _settings(payload: dict) -> Settings:
    settings = Settings.from_env()
    changes: dict[str, object] = {}
    root = payload.get("project_root")
    if root:
        changes["project_root"] = Path(root)
    data = payload.get("data_dir")
    if data:
        changes["data_dir"] = Path(data)
    for key in OVERRIDE_FIELDS:
        if key in payload and payload[key] is not None:
            changes[key] = payload[key]
    return replace(settings, **changes) if changes else settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", help="JSON spec file; omit to read stdin")
    args = parser.parse_args(argv)
    raw = (
        Path(args.spec).read_text(encoding="utf-8")
        if args.spec
        else sys.stdin.read()
    )
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        print(f"invalid spec: {exc}", file=sys.stderr)
        return 2
    settings = _settings(payload.get("settings") or {})
    kind = payload.get("kind")
    if kind == "job":
        store = JobStore(
            Path(payload["store_root"]),
            stale_seconds=float(payload.get("stale_seconds") or 300.0),
        )
        run_job(store, payload["job_id"], settings)
        return 0
    if kind == "pipeline":
        run_pipeline(
            Path(payload["source"]),
            Path(payload["out_dir"]),
            settings=settings,
            coverage_template=payload.get("coverage_template") or "product_full",
        )
        return 0
    print(f"unknown kind: {kind}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
