#!/usr/bin/env python3
"""W2 Tier2 PoC: compare structural table engines on the same PDF pages.

Tier 1 (native drawn tables + text-coordinate clustering) always runs.  The
structural candidates (Docling TableFormer, TATR, PP-Structure) are optional
third-party stacks; this harness probes availability, then measures table
counts and latency per page so one candidate can be selected for Tier 2
without wiring it into production.

Run from ``new_app``::

    python scripts/benchmark/table_engine_poc.py --docs ../../gold_standard_30/*.pdf
    python scripts/benchmark/table_engine_poc.py --registry --limit 10
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

import pymupdf

NEW_APP_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = NEW_APP_DIR.parent
DEFAULT_REGISTRY = NEW_APP_DIR / "docs" / "reports" / "gold-registry.json"

sys.path.insert(0, str(NEW_APP_DIR))
from services.ocr.algorithms.text_tables import build_table  # noqa: E402

STRUCTURAL_ENGINES = {
    "docling": ("docling.document_converter", "TableFormer（MIT，表格结构模型）"),
    "tatr": ("transformers", "Table Transformer（检测+结构两段模型）"),
    "ppstructure": ("paddleocr", "PP-Structure（PaddleOCR 表格识别）"),
}


def engine_available(name: str) -> bool:
    if name in {"native", "text"}:
        return True
    module = STRUCTURAL_ENGINES[name][0].split(".")[0]
    try:
        return bool(importlib.util.find_spec(module))
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def native_tables(page) -> list[str]:
    try:
        tables = page.find_tables()
    except Exception:
        return []
    found = []
    for table in tables.tables if tables else []:
        rows = table.extract()
        if rows:
            found.append(str(rows))
    return found


def text_tables(page) -> list[str]:
    recovered = build_table(page.get_text("words"))
    return [recovered.html] if recovered else []


def docling_tables(pdf: Path) -> dict[int, list[str]]:
    """Docling converts a whole document once; split tables by page number."""
    from docling.document_converter import DocumentConverter

    result = DocumentConverter().convert(str(pdf))
    tables: dict[int, list[str]] = {}
    for table in getattr(result.document, "tables", []):
        page_no = int(getattr(table, "page_no", 0) or 0)
        export = getattr(table, "export_to_html", None)
        html = export() if callable(export) else str(table)
        tables.setdefault(page_no, []).append(html)
    return tables


def run_document(pdf: Path, engines: list[str], max_pages: int) -> dict[str, Any]:
    report: dict[str, Any] = {"pdf": str(pdf), "pages": 0, "engines": {}}
    document = pymupdf.open(pdf)
    try:
        page_count = min(len(document), max_pages) if max_pages else len(document)
        report["pages"] = page_count
        docling: dict[int, list[str]] = {}
        if "docling" in engines and engine_available("docling"):
            started = time.perf_counter()
            docling = docling_tables(pdf)
            report["engines"]["docling_document_seconds"] = round(
                time.perf_counter() - started, 2
            )
        for name in engines:
            if not engine_available(name):
                report["engines"][name] = {"available": False}
                continue
            if name in {"tatr", "ppstructure"}:
                # 未提供 adapter：只登记可用性，避免把模型推理混进 CI。
                report["engines"][name] = {"available": True, "adapter": "missing"}
                continue
            latencies: list[float] = []
            counts: list[int] = []
            for index in range(page_count):
                page = document[index]
                started = time.perf_counter()
                if name == "native":
                    found = native_tables(page)
                elif name == "text":
                    found = text_tables(page)
                else:
                    found = docling.get(index + 1, [])
                latencies.append((time.perf_counter() - started) * 1000)
                counts.append(len(found))
            report["engines"][name] = {
                "available": True,
                "tables": sum(counts),
                "pages_with_tables": sum(1 for count in counts if count),
                "median_ms": round(statistics.median(latencies), 2) if latencies else 0.0,
                "counts": counts,
            }
    finally:
        document.close()
    return report


def load_docs(args: argparse.Namespace) -> list[Path]:
    if args.docs:
        return [Path(item) for item in args.docs]
    if args.registry:
        registry = json.loads(args.registry.read_text(encoding="utf-8"))
        docs = [Path(item["pdf"]) for item in registry.get("documents") or []]
        return docs[: args.limit] if args.limit else docs
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docs", nargs="*", help="PDF paths")
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--max-pages", type=int, default=0)
    parser.add_argument("--engines", nargs="*", default=list(("native", "text", "docling")))
    parser.add_argument("--out-json", type=Path)
    args = parser.parse_args()

    pdfs = [path for path in load_docs(args) if path.exists()]
    if not pdfs:
        raise SystemExit("no pdf found")

    availability = {name: engine_available(name) for name in STRUCTURAL_ENGINES}
    reports = [run_document(pdf, args.engines, args.max_pages) for pdf in pdfs]

    totals: dict[str, dict[str, Any]] = {}
    for report in reports:
        for name, metrics in report["engines"].items():
            if name.endswith("_seconds") or not metrics.get("available"):
                continue
            bucket = totals.setdefault(
                name, {"tables": 0, "pages_with_tables": 0, "median_ms": [], "docs": 0}
            )
            bucket["tables"] += metrics.get("tables", 0)
            bucket["pages_with_tables"] += metrics.get("pages_with_tables", 0)
            bucket["median_ms"].append(metrics.get("median_ms", 0.0))
            bucket["docs"] += 1

    payload = {
        "documents": len(reports),
        "availability": availability,
        "totals": {
            name: {
                "documents": value["docs"],
                "tables": value["tables"],
                "pages_with_tables": value["pages_with_tables"],
                "median_ms": round(statistics.median(value["median_ms"]), 2)
                if value["median_ms"]
                else 0.0,
            }
            for name, value in totals.items()
        },
        "reports": reports,
    }
    print("| engine | available | documents | tables | pages_with_tables | median_ms |")
    print("|---|---|---|---|---|---|")
    for name in ("native", "text", *STRUCTURAL_ENGINES):
        summary = payload["totals"].get(name)
        if summary:
            print(
                f"| {name} | yes | {summary['documents']} | {summary['tables']} | "
                f"{summary['pages_with_tables']} | {summary['median_ms']} |"
            )
        else:
            print(f"| {name} | {'yes' if availability.get(name) else 'no'} | - | - | - | - |")
    if args.out_json:
        args.out_json.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
