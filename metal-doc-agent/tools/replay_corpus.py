"""Replay a selected corpus through the engine and record per-document timing.

Reads a selection JSON (``select_corpus`` output or a gold-manifest export),
runs ``metal_doc_agent.cli run`` for each document, and appends one JSON line per
document to ``<out-root>/timings.jsonl`` (wall time + trace stage timings).

Usage:
    python -m tools.replay_corpus --selection runs/corpus_v2/selection.json \
      --out-root runs/corpus_v2 --ocr mock --extractor mock
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARKDOWN = ROOT.parent / "markdown"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", required=True)
    parser.add_argument("--out-root", required=True)
    parser.add_argument("--source-root", default=str(MARKDOWN))
    parser.add_argument("--ocr", default="mock", choices=["mock", "glm"])
    parser.add_argument("--extractor", default="mock", choices=["mock", "qwen"])
    parser.add_argument("--template", default="product_full")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--qwen-base", default=os.environ.get("QWEN_BASE_URL", ""))
    parser.add_argument("--timeout", type=int, default=1800)
    args = parser.parse_args(argv)

    items = json.loads(Path(args.selection).read_text(encoding="utf-8"))
    if args.limit:
        items = items[: args.limit]
    out_root = Path(args.out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    timings_path = out_root / "timings.jsonl"

    env = dict(os.environ)
    if args.qwen_base:
        env["QWEN_BASE_URL"] = args.qwen_base

    failures = 0
    timings = []
    for index, item in enumerate(items, start=1):
        doc_id = str(item.get("doc_id") or item.get("slug"))
        out_dir = out_root / doc_id
        if args.resume and (out_dir / "result.json").exists():
            print(f"[{index}/{len(items)}] skip {doc_id}", flush=True)
            continue
        source = _source(item, Path(args.source_root))
        if not source.exists():
            failures += 1
            print(f"[{index}/{len(items)}] missing {source}", flush=True)
            continue
        command = [
            sys.executable,
            "-m",
            "metal_doc_agent.cli",
            "run",
            str(source),
            "--out",
            str(out_dir),
            "--ocr",
            args.ocr,
            "--extractor",
            args.extractor,
            "--template",
            args.template,
        ]
        started = time.perf_counter()
        try:
            proc = subprocess.run(
                command,
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=args.timeout,
            )
        except subprocess.TimeoutExpired:
            proc = None
        elapsed = round(time.perf_counter() - started, 2)
        if proc is None or proc.returncode != 0:
            failures += 1
            detail = "timeout" if proc is None else (proc.stderr or "")[-300:]
            print(f"[{index}/{len(items)}] FAIL {doc_id} {elapsed}s: {detail}", flush=True)
            continue
        record = _record(doc_id, item, source, elapsed, out_dir, args)
        timings.append(record)
        with timings_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(
            f"[{index}/{len(items)}] {doc_id} {elapsed}s pages={record['pages']} "
            f"tables={record['tables']} records={record['records']}",
            flush=True,
        )

    summary = {
        "documents": len(timings),
        "failures": failures,
        "seconds": round(sum(item["seconds"] for item in timings), 2),
        "ocr": args.ocr,
        "extractor": args.extractor,
        "timings": str(timings_path),
    }
    (out_root / "timings-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False))
    return 1 if failures else 0


def _source(item: dict, root: Path) -> Path:
    if item.get("path"):
        return Path(item["path"])
    if item.get("source_path"):
        return Path(item["source_path"])
    return root / str(item["file"])


def _record(doc_id: str, item: dict, source: Path, elapsed: float, out_dir: Path, args) -> dict:
    result_path = out_dir / "result.json"
    result = {}
    if result_path.exists():
        result = json.loads(result_path.read_text(encoding="utf-8"))
    trace = {}
    trace_path = out_dir / "trace.json"
    if trace_path.exists():
        trace = json.loads(trace_path.read_text(encoding="utf-8"))
    stages = {step.get("name"): step.get("ms") for step in trace.get("steps") or []}
    document = result.get("document") or {}
    return {
        "doc_id": doc_id,
        "title": item.get("title") or document.get("title"),
        "doc_type": item.get("doc_type"),
        "source": str(source),
        "seconds": elapsed,
        "elapsed_ms": trace.get("elapsed_ms"),
        "pages": document.get("page_count") or item.get("pages"),
        "tables": len(result.get("tables") or []),
        "records": len(result.get("records") or []),
        "status": result.get("status"),
        "stages_ms": stages,
        "ocr": args.ocr,
        "extractor": args.extractor,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


if __name__ == "__main__":
    raise SystemExit(main())
