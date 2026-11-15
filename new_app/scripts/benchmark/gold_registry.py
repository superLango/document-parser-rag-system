#!/usr/bin/env python3
"""Build and verify the human gold-standard registry.

The gold corpus lives in ``gold_standard_30/`` at the repository root.  Each
gold document is keyed by its PDF basename; this script links it to the newest
available pipeline run found in the benchmark reports so downstream evaluation
does not need to guess which run belongs to which gold document.

Run from ``new_app``::

    python scripts/benchmark/gold_registry.py
    python scripts/benchmark/gold_registry.py --check
    python scripts/benchmark/gold_registry.py --refresh-api
"""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

NEW_APP_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = NEW_APP_DIR.parent
GOLD_DIR = REPO_ROOT / "gold_standard_30"
REPORT_DIR = NEW_APP_DIR / "docs" / "reports"
DEFAULT_OUT = REPORT_DIR / "gold-registry.json"

# Earlier entries win when the same PDF appears in multiple reports.
REPORT_PRIORITY = (
    "gold-rerun.json",
    "full-runs-p1.json",
    "p1-rerun-2.json",
    "full-runs50.json",
    "p1-regression.json",
    "hantang-full-runs.json",
    "closeout-standards-e2e.json",
)
TERMINAL_BAD = {"REVIEW_FAILED", "FAILED", "UNROUTED"}


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def pdf_key(path: str | None) -> str:
    name = os.path.basename(str(path or "").replace("\\", "/")).lower()
    return re.sub(r"\s+", "", name)


def load_gold_index() -> list[dict[str, Any]]:
    payload = json.loads((GOLD_DIR / "index.json").read_text(encoding="utf-8"))
    return payload["documents"]


def iter_report_documents() -> list[tuple[int, str, str, dict[str, Any]]]:
    """Yield ``(priority, report_name, generated_at, document)``."""
    rows: list[tuple[int, str, str, dict[str, Any]]] = []
    for priority, name in enumerate(REPORT_PRIORITY):
        path = REPORT_DIR / name
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        generated_at = str(payload.get("generated_at") or "")
        for document in payload.get("documents") or []:
            if isinstance(document, dict) and document.get("run_id"):
                rows.append((priority, name, generated_at, document))
    return rows


def pick_run(index_entry: dict[str, Any], report_rows: list[tuple[int, str, str, dict[str, Any]]]):
    wanted = pdf_key(index_entry.get("source_pdf"))
    candidates = [
        row for row in report_rows if pdf_key(row[3].get("path") or row[3].get("name")) == wanted
    ]
    if not candidates:
        return None
    # Prefer a successful run, then the newest report, then more records.
    candidates.sort(
        key=lambda row: (
            str(row[3].get("status") or "") in TERMINAL_BAD,
            row[0],
            -int(row[3].get("records") or 0),
        )
    )
    return candidates[0]


def build_registry() -> dict[str, Any]:
    reports = iter_report_documents()
    documents: list[dict[str, Any]] = []
    for entry in load_gold_index():
        chosen = pick_run(entry, reports)
        document = {
            "doc_id": entry["doc_id"],
            "standard_no": entry.get("standard_no") or "",
            "title": entry.get("title") or "",
            "pdf": entry.get("source_pdf") or "",
            "pdf_sha256": entry.get("pdf_sha256") or "",
            "page_count": entry.get("page_count"),
            "gold_file": f"documents/{entry['doc_id']}.json",
            "source_tables_file": f"source_tables/{entry['doc_id']}.json",
            "provenance_file": f"provenance/{entry['doc_id']}.json",
            "items": entry.get("items", 0),
            "heat_treatment": entry.get("heat_treatment", 0),
            "source_tables": entry.get("tables", 0),
            "source_records": entry.get("source_records", 0),
            "run_id": "",
            "run_status": "",
            "run_records": 0,
            "run_source": "",
            "run_generated_at": "",
        }
        if chosen:
            _, source, generated_at, run = chosen
            document.update(
                {
                    "run_id": run.get("run_id") or "",
                    "run_status": run.get("status") or "",
                    "run_records": int(run.get("records") or 0),
                    "run_source": source,
                    "run_generated_at": generated_at,
                }
            )
        documents.append(document)
    return {
        "generated_at": now_iso(),
        "schema": "product_standard/1",
        "source": str(GOLD_DIR),
        "summary": summarize(documents),
        "documents": documents,
    }


def summarize(documents: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "documents": len(documents),
        "with_run": sum(1 for item in documents if item["run_id"]),
        "without_run": sum(1 for item in documents if not item["run_id"]),
        "bad_status": sum(1 for item in documents if item["run_status"] in TERMINAL_BAD),
        "empty_runs": sum(1 for item in documents if item["run_id"] and not item["run_records"]),
        "items": sum(int(item["items"]) for item in documents),
        "heat_treatment": sum(int(item["heat_treatment"]) for item in documents),
        "source_tables": sum(int(item["source_tables"]) for item in documents),
        "source_records": sum(int(item["source_records"]) for item in documents),
    }


def refresh_api(registry: dict[str, Any], api: str) -> None:
    client = httpx.Client(timeout=60)
    # The stored run_id comes from older benchmark reports and may point at a
    # purged/empty run.  Prefer the newest run of the matching document.
    try:
        api_documents = client.get(f"{api}/v1/documents").json()
        api_runs = client.get(f"{api}/v1/runs").json()
    except Exception as exc:  # noqa: BLE001 - fall back to stored run ids
        registry["refresh_error"] = str(exc)[:200]
        api_documents = []
        api_runs = []
    by_name = {
        Path(str(item.get("filename") or "")).name.lower(): item
        for item in api_documents
        if item.get("filename")
    }
    latest: dict[str, dict[str, Any]] = {}
    for run in api_runs:
        key = str(run.get("document_id") or "")
        if not key:
            continue
        if key not in latest or str(run.get("created_at") or "") > str(
            latest[key].get("created_at") or ""
        ):
            latest[key] = run
    for document in registry["documents"]:
        name = Path(str(document.get("pdf") or "")).name.lower()
        api_document = by_name.get(name)
        run = latest.get(str(api_document.get("id"))) if api_document else None
        run_id = str(run.get("id")) if run else str(document.get("run_id") or "")
        if not run_id:
            continue
        try:
            current = client.get(f"{api}/v1/runs/{run_id}").json()
            records = client.get(f"{api}/v1/runs/{run_id}/records").json()
        except Exception as exc:  # noqa: BLE001 - report and continue
            document["run_error"] = str(exc)[:200]
            continue
        document["run_id"] = run_id
        document["run_status"] = current.get("status") or document.get("run_status") or ""
        document["run_records"] = len(records.get("records") or [])
        if run:
            document["run_source"] = "api-latest"
    registry["summary"] = summarize(registry["documents"])
    registry["refreshed_at"] = now_iso()


def verify(registry: dict[str, Any], *, require_pdfs: bool = False) -> list[str]:
    problems: list[str] = []
    documents = registry.get("documents") or []
    if len(documents) != 30:
        problems.append(f"gold documents {len(documents)} != 30")
    seen: set[str] = set()
    for document in documents:
        doc_id = document["doc_id"]
        if doc_id in seen:
            problems.append(f"duplicate doc_id {doc_id}")
        seen.add(doc_id)
        for field in ("gold_file", "source_tables_file", "provenance_file"):
            if not (GOLD_DIR / document[field]).exists():
                problems.append(f"{doc_id}: missing {field}")
        if require_pdfs and not Path(document["pdf"]).exists():
            problems.append(f"{doc_id}: missing pdf")
        if not document.get("run_id"):
            problems.append(f"{doc_id}: no run")
        if not document.get("pdf_sha256"):
            problems.append(f"{doc_id}: missing pdf_sha256")
        if not int(document.get("items") or 0) and not int(document.get("heat_treatment") or 0):
            problems.append(f"{doc_id}: empty gold")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--api", default="http://localhost:18000")
    parser.add_argument("--refresh-api", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--require-pdfs", action="store_true")
    args = parser.parse_args()

    if not GOLD_DIR.exists():
        print(f"gold corpus not present at {GOLD_DIR}, skipped")
        return 0

    registry = build_registry()
    if args.refresh_api:
        refresh_api(registry, args.api)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    problems = verify(registry, require_pdfs=args.require_pdfs)
    print(json.dumps(registry["summary"], ensure_ascii=False))
    print(f"problems {len(problems)}")
    for problem in problems[:30]:
        print(" -", problem)
    if args.check and problems:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
