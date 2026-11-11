"""Local concurrency/load test for M5 SLO evidence (mock backends).

Runs N real corpus documents through the orchestration graph with a thread
pool, then reports p50/p95/max latency and failure rate. Model backends are
mock here; the measurement validates the orchestration/data-plane envelope,
not GPU throughput.

Usage:
    python -m tools.loadtest --docs 8 --concurrency 4 \
      --out eval/loadtest.json --md eval/loadtest.md
"""

from __future__ import annotations

import argparse
import json
import shutil
import statistics
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from metal_doc_agent.orchestration import run_orchestrated
from metal_doc_agent.settings import Settings

ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", default=str(ROOT / "runs" / "m2_baseline"))
    parser.add_argument("--docs", type=int, default=8)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--out", default=str(ROOT / "eval" / "loadtest.json"))
    parser.add_argument("--md", default=str(ROOT / "eval" / "loadtest.md"))
    args = parser.parse_args(argv)

    manifests = sorted(Path(args.runs).glob("*/manifest.json"))[: max(1, args.docs)]
    tmp = Path(tempfile.mkdtemp(prefix="m5-loadtest-"))
    settings = Settings.from_env()
    settings = settings.__class__(
        **{
            **settings.__dict__,
            "ocr_backend": "mock",
            "extractor_backend": "mock",
            "data_dir": tmp / "data",
        }
    )
    started = time.perf_counter()
    rows: list[dict] = []
    try:
        with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as pool:
            futures = {}
            for index, manifest_path in enumerate(manifests):
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                source = Path(manifest.get("source_path") or "")
                if not source.exists():
                    continue
                out = tmp / f"doc-{index}"
                futures[
                    pool.submit(_run_one, source, out, settings, manifest_path.parent.name)
                ] = manifest_path.parent.name
            for future in as_completed(futures):
                rows.append(future.result())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    total_seconds = round(time.perf_counter() - started, 3)
    latencies = [row["elapsed_ms"] for row in rows if row.get("elapsed_ms")]
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "documents": len(rows),
        "concurrency": args.concurrency,
        "backends": {"ocr": "mock", "extractor": "mock"},
        "totals": {
            "success": sum(1 for row in rows if row["status"] in {"published", "review", "human"}),
            "failed": sum(1 for row in rows if row["status"] == "failed"),
            "failure_rate": round(
                sum(1 for row in rows if row["status"] == "failed") / len(rows), 4
            )
            if rows
            else 0.0,
            "wall_seconds": total_seconds,
            "throughput_docs_per_second": round(len(rows) / total_seconds, 3)
            if total_seconds
            else 0.0,
            "latency_ms_p50": round(statistics.median(latencies), 1) if latencies else None,
            "latency_ms_p95": round(
                sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)], 1
            )
            if latencies
            else None,
            "latency_ms_max": round(max(latencies), 1) if latencies else None,
            "statuses": {status: sum(1 for row in rows if row["status"] == status) for status in {row["status"] for row in rows}},
        },
        "targets": {"p95_ms": 300000, "failure_rate": 0.02},
        "documents_detail": rows,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    Path(args.md).write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps(report["totals"], ensure_ascii=False))
    print(f"out={out}")
    return 0


def _run_one(source: Path, out: Path, settings: Settings, doc_id: str) -> dict:
    started = time.perf_counter()
    try:
        state = run_orchestrated(
            source,
            out,
            settings,
            job_id=doc_id,
            options={"ocr": "mock", "extractor": "mock"},
        )
        elapsed = round((time.perf_counter() - started) * 1000, 1)
        return {
            "doc_id": doc_id,
            "status": state.status,
            "reason": state.terminal_reason,
            "route": state.route.queue,
            "steps": state.cost.steps,
            "elapsed_ms": elapsed,
        }
    except Exception as exc:  # noqa: BLE001 - load test records failures
        return {
            "doc_id": doc_id,
            "status": "failed",
            "reason": f"{type(exc).__name__}: {exc}"[:200],
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
        }


def render_markdown(report: dict) -> str:
    totals = report["totals"]
    lines = [
        "# M5 并发压测（mock 后端）",
        "",
        f"- 文档：{report['documents']}，并发：{report['concurrency']}",
        f"- 墙上时间：{totals['wall_seconds']}s，吞吐：{totals['throughput_docs_per_second']} docs/s",
        "",
        "| 指标 | 值 | 目标 |",
        "|---|---|---|",
        f"| p50 | {totals['latency_ms_p50']} ms | - |",
        f"| p95 | {totals['latency_ms_p95']} ms | ≤300000 ms |",
        f"| 最大 | {totals['latency_ms_max']} ms | - |",
        f"| 失败率 | {totals['failure_rate']} | <0.02 |",
        f"| 状态分布 | {totals['statuses']} | - |",
        "",
        "## 说明",
        "",
        "- mock OCR/抽取，仅验证编排与数据面的并发包络，不代表 GPU 吞吐。",
        "- 真实 SLA 需在生产流量或模型后端下重测。",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
