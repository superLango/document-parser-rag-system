#!/usr/bin/env python3
"""Reparse the HT top-30 library with the current parser asset.

Every document keeps its OCR cache (``reuse_ocr=true``) and gets a fresh run on
the requested parser version.  Results are checkpointed after each document.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUT = REPO_ROOT / "new_app" / "docs" / "reports" / "ht-top30-runs.json"
TERMINAL = {
    "STRUCTURED_READY",
    "REVIEW_FAILED",
    "FAILED",
    "UNROUTED",
    "CANCELLED",
    "HUMAN_REJECTED",
}
TERMINAL_BAD = TERMINAL - {"STRUCTURED_READY"}
WAITING = {"HUMAN_REVIEW"}


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def wait_run(
    client: httpx.Client, api: str, run_id: str, timeout: float
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        response = client.get(f"{api}/v1/runs/{run_id}")
        if response.status_code == 200:
            last = response.json()
            status = str(last.get("status") or "")
            if status in WAITING:
                accepted = client.post(
                    f"{api}/v1/runs/{run_id}/accept",
                    params={"actor": "top30-audit", "note": "automated audit gate"},
                )
                if accepted.status_code == 200:
                    last = {
                        **last,
                        "status": accepted.json().get("run_status", "STRUCTURED_READY"),
                    }
                return last
            if status in TERMINAL:
                return last
        time.sleep(3)
    return last


def reparse_one(
    client: httpx.Client, api: str, document: dict[str, Any], parser_version: str
) -> dict[str, Any]:
    run_id = str(document.get("latest_run_id") or "")
    if not run_id:
        return {
            "document_id": document.get("id"),
            "filename": document.get("filename"),
            "status": "NO_RUN",
            "records": 0,
            "fields": 0,
        }
    started = time.monotonic()
    response = client.post(
        f"{api}/v1/runs/{run_id}/reparse",
        json={"parser_version": parser_version, "reuse_ocr": True},
    )
    if response.status_code not in {200, 201, 202}:
        return {
            "document_id": document.get("id"),
            "filename": document.get("filename"),
            "status": "REPARSE_ERROR",
            "error_code": f"HTTP {response.status_code}: {response.text[:160]}",
            "records": 0,
            "fields": 0,
        }
    new_run = response.json()
    new_id = str(new_run.get("id") or "")
    final = wait_run(client, api, new_id, timeout=2400)
    stats = {
        "document_id": document.get("id"),
        "filename": document.get("filename"),
        "run_id": new_id,
        "old_run_id": run_id,
        "status": final.get("status"),
        "error_code": final.get("error_code"),
        "parser_version": "",
        "records": 0,
        "fields": 0,
        "review_findings": 0,
        "elapsed_seconds": round(time.monotonic() - started, 1),
    }
    detail = client.get(f"{api}/v1/runs/{new_id}")
    if detail.status_code == 200:
        body = detail.json()
        stats["parser_version"] = body.get("parser_version") or ""
        stats["status"] = body.get("status") or stats["status"]
    records_response = client.get(f"{api}/v1/runs/{new_id}/records")
    if records_response.status_code == 200:
        records = records_response.json().get("records") or []
        stats["records"] = len(records)
        stats["fields"] = sum(
            len(item.get("properties") or {}) for item in records if isinstance(item, dict)
        )
    review = client.get(f"{api}/v1/runs/{new_id}/review")
    if review.status_code == 200:
        stats["review_findings"] = len(review.json().get("findings") or [])
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://localhost:18000")
    parser.add_argument("--parser-version", required=True)
    parser.add_argument("--out-json", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--only", default="", help="comma separated filename prefixes")
    parser.add_argument("--timeout", type=float, default=2400)
    args = parser.parse_args()
    api = args.api.rstrip("/")
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=120) as client:
        documents = client.get(f"{api}/v1/documents", params={"limit": 200}).json()
        runs = client.get(f"{api}/v1/runs", params={"limit": 500}).json()
        latest: dict[str, dict[str, Any]] = {}
        for run in runs:
            key = str(run.get("document_id") or "")
            if key not in latest or str(run.get("created_at") or "") > str(
                latest[key].get("created_at") or ""
            ):
                latest[key] = run
        for document in documents:
            run = latest.get(str(document.get("id") or ""))
            if run:
                document["latest_run_id"] = run.get("id")
        only = [item.strip() for item in args.only.split(",") if item.strip()]
        if only:
            documents = [
                item
                for item in documents
                if any(str(item.get("filename") or "").startswith(prefix) for prefix in only)
            ]
        documents.sort(key=lambda item: int(item.get("size") or 0))
        results: list[dict[str, Any]] = []
        for index, document in enumerate(documents, start=1):
            result = reparse_one(client, api, document, args.parser_version)
            results.append(result)
            payload = {
                "generated_at": now_iso(),
                "parser_version": args.parser_version,
                "documents": results,
            }
            args.out_json.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            print(
                f"[{index}/{len(documents)}] {str(result.get('filename'))[:52]} -> "
                f"{result.get('status')} records={result.get('records')} "
                f"fields={result.get('fields')} {result.get('elapsed_seconds')}s",
                flush=True,
            )
    failed = [item for item in results if item.get("status") in TERMINAL_BAD]
    print(f"done {len(results) - len(failed)}/{len(results)} ready", flush=True)
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
