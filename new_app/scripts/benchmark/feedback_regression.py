#!/usr/bin/env python3
"""Run the fixed sample set through a recipe channel and build a regression snapshot.

Examples::

    # baseline on stable
    python scripts/benchmark/feedback_regression.py run \
        --manifest sample-50.json --channel stable --out data/feedback/regression-baseline.json

    # candidate batch, compared against the baseline
    python scripts/benchmark/feedback_regression.py run \
        --manifest sample-50.json --channel candidate \
        --out data/feedback/regression-current.json \
        --compare data/feedback/regression-baseline.json

The manifest is either a list of ``{"document_id": "...", "name": "..."}``
objects or a ``{"documents": [...]}`` wrapper.  Snapshot files are the same
format consumed by ``services.orchestration.feedback.regression.gate``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

NEW_APP = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(NEW_APP))

from services.orchestration.feedback.coverage import compute_coverage  # noqa: E402
from services.orchestration.feedback.regression import (  # noqa: E402
    compare_snapshots,
    load_snapshot,
    metrics_from_records,
    snapshot_from_documents,
)

DEFAULT_API = os.getenv("API_BASE", "http://localhost:18000")
TERMINAL = {
    "STRUCTURED_READY",
    "REVIEW_FAILED",
    "HUMAN_REJECTED",
    "UNROUTED",
    "FAILED",
    "CANCELLED",
}
WAITING = {"HUMAN_REVIEW"}


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def load_manifest(path: Path) -> list[dict[str, str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    items = payload.get("documents") if isinstance(payload, dict) else payload
    documents: list[dict[str, str]] = []
    for item in items or []:
        if isinstance(item, str):
            documents.append({"document_id": item, "name": item})
        elif isinstance(item, dict) and item.get("document_id"):
            documents.append(
                {
                    "document_id": str(item["document_id"]),
                    "name": str(item.get("name") or item["document_id"]),
                }
            )
    return documents


def _run_id(payload: dict[str, Any]) -> str:
    return str(payload.get("id") or payload.get("run_id") or "")


def run_document(
    client: httpx.Client,
    document: dict[str, str],
    channel: str,
    timeout_seconds: float,
    poll_seconds: float,
) -> dict[str, Any]:
    response = client.post(
        f"/documents/{document['document_id']}/runs",
        json={"recipe_channel": channel},
    )
    response.raise_for_status()
    run_id = _run_id(response.json())
    if not run_id:
        raise RuntimeError(f"run id missing for {document['name']}")
    status = ""
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        detail = client.get(f"/runs/{run_id}").json()
        status = str(detail.get("status") or "")
        if status in WAITING:
            accepted = client.post(
                f"/runs/{run_id}/accept",
                params={"actor": "regression", "note": "automated gate"},
            )
            if accepted.status_code == 200:
                status = str(
                    accepted.json().get("run_status") or "STRUCTURED_READY"
                )
            break
        if status in TERMINAL:
            break
        time.sleep(poll_seconds)
    records: list[dict[str, Any]] = []
    if status in {"STRUCTURED_READY", "REVIEW_FAILED"}:
        payload = client.get(f"/runs/{run_id}/records").json()
        records = [
            item for item in (payload.get("records") or []) if isinstance(item, dict)
        ]
    metrics = metrics_from_records(records)
    coverage = compute_coverage(records)
    return {
        "name": document["name"],
        "document_id": document["document_id"],
        "run_id": run_id,
        "status": status,
        **metrics,
        "complete_rows": coverage["complete_rows"],
        "required_present": coverage["required_present"],
    }


def run_manifest(args: argparse.Namespace) -> int:
    documents = load_manifest(Path(args.manifest))
    if not documents:
        print("manifest is empty", file=sys.stderr)
        return 2
    results: list[dict[str, Any]] = []
    with httpx.Client(base_url=args.api, timeout=args.timeout) as client:
        if args.jobs <= 1:
            for document in documents:
                results.append(
                    run_document(
                        client, document, args.channel, args.timeout, args.poll
                    )
                )
                print(f"[{len(results)}/{len(documents)}] {document['name']} ok")
        else:
            with ThreadPoolExecutor(max_workers=args.jobs) as pool:
                futures = {
                    pool.submit(
                        run_document,
                        client,
                        document,
                        args.channel,
                        args.timeout,
                        args.poll,
                    ): document
                    for document in documents
                }
                for future in as_completed(futures):
                    document = futures[future]
                    try:
                        results.append(future.result())
                        print(f"[{len(results)}/{len(documents)}] {document['name']} ok")
                    except Exception as exc:  # noqa: BLE001 - report and continue
                        print(f"{document['name']} failed: {exc}", file=sys.stderr)
                        results.append(
                            {
                                "name": document["name"],
                                "document_id": document["document_id"],
                                "status": "ERROR",
                                "records": 0,
                                "fields": 0,
                                "placeholders": 0,
                                "duplicates": 0,
                                "complete_rows": 0,
                                "required_present": 0,
                            }
                        )
    results.sort(key=lambda item: item["name"])
    snapshot = {
        "generated_at": _now(),
        "channel": args.channel,
        "documents": results,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"snapshot written: {out} ({len(results)} documents)")

    if args.compare:
        result = compare_snapshots(
            load_snapshot(args.compare),
            snapshot_from_documents(results),
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["passed"] else 1
    return 0


def compare_only(args: argparse.Namespace) -> int:
    result = compare_snapshots(
        load_snapshot(args.baseline),
        load_snapshot(args.current),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run a manifest and write a snapshot")
    run.add_argument("--manifest", required=True)
    run.add_argument("--channel", default="stable")
    run.add_argument("--out", required=True)
    run.add_argument("--api", default=DEFAULT_API)
    run.add_argument("--timeout", type=float, default=600.0)
    run.add_argument("--poll", type=float, default=5.0)
    run.add_argument("--jobs", type=int, default=1)
    run.add_argument("--compare", default="")
    run.set_defaults(func=run_manifest)

    compare = sub.add_parser("compare", help="compare two snapshots")
    compare.add_argument("--baseline", required=True)
    compare.add_argument("--current", required=True)
    compare.set_defaults(func=compare_only)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
