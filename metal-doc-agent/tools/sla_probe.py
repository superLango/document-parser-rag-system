"""SLA evidence from the job store (E1).

Computes availability, failure rate and p95 duration from persisted jobs. Until
a pilot produces enough traffic the report is explicitly ``insufficient_data``;
the tool exists so the measurement is mechanical, not a manual estimate.

Usage:
    python -m tools.sla_probe --jobs data/jobs --min-jobs 200 \
      --out eval/sla.json --md eval/sla.md
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from metal_doc_agent.jobs import JobStore

ROOT = Path(__file__).resolve().parents[1]
FINISHED = {"succeeded", "review", "failed"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", default=str(ROOT / "data" / "jobs"))
    parser.add_argument("--min-jobs", type=int, default=200)
    parser.add_argument("--target", type=float, default=0.995)
    parser.add_argument("--failure-target", type=float, default=0.02)
    parser.add_argument("--p95-target-ms", type=float, default=300_000.0)
    parser.add_argument("--out", default=str(ROOT / "eval" / "sla.json"))
    parser.add_argument("--md", default=str(ROOT / "eval" / "sla.md"))
    args = parser.parse_args(argv)

    store = JobStore(args.jobs)
    states = store.list(limit=10_000)
    finished = [state for state in states if state.status in FINISHED]
    statuses = Counter(state.status for state in finished)
    durations = [
        value for value in (_duration_ms(state) for state in finished) if value is not None
    ]
    samples = len(finished)
    failed = statuses.get("failed", 0)
    availability = round(1 - failed / samples, 6) if samples else None
    failure_rate = round(failed / samples, 6) if samples else None
    p95 = round(_percentile(durations, 0.95), 2) if durations else None
    enough = samples >= args.min_jobs
    checks = {
        "samples": samples,
        "samples_ok": enough,
        "availability_ok": availability is not None and availability >= args.target,
        "failure_rate_ok": failure_rate is not None
        and failure_rate < args.failure_target,
        "p95_ok": p95 is not None and p95 <= args.p95_target_ms,
    }
    if not enough:
        status = "insufficient_data"
    elif all(checks[key] for key in checks if key != "samples"):
        status = "pass"
    else:
        status = "fail"
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "jobs_dir": str(Path(args.jobs)),
        "status": status,
        "window": {"sampled_jobs": samples, "min_jobs": args.min_jobs},
        "statuses": dict(statuses),
        "availability": availability,
        "failure_rate": failure_rate,
        "p95_ms": p95,
        "targets": {
            "availability": args.target,
            "failure_rate": args.failure_target,
            "p95_ms": args.p95_target_ms,
        },
        "error_budget_used": round((1 - availability) / (1 - args.target), 4)
        if availability is not None
        else None,
        "checks": checks,
        "inputs_needed": [
            "pilot/production traffic window (>=200 finished jobs)",
            "SLA terms confirmed by the business owner (penalty window/scope)",
        ],
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    Path(args.md).write_text(render_markdown(report), encoding="utf-8")
    print(
        json.dumps(
            {"status": status, "samples": samples, "availability": availability, "p95_ms": p95},
            ensure_ascii=False,
        )
    )
    print(f"out={out}")
    return 0


def _duration_ms(state) -> float | None:
    metrics = Path(state.out_dir) / "metrics.json"
    if metrics.exists():
        try:
            payload = json.loads(metrics.read_text(encoding="utf-8"))
            seconds = payload.get("pipeline_seconds")
            if isinstance(seconds, (int, float)):
                return float(seconds) * 1000
        except ValueError:
            pass
    if not state.created_at or not state.finished_at:
        return None
    try:
        started = datetime.fromisoformat(state.created_at)
        ended = datetime.fromisoformat(state.finished_at)
    except ValueError:
        return None
    return max(0.0, (ended - started).total_seconds() * 1000)


def _percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(len(ordered) * ratio)) - 1))
    return ordered[index]


def render_markdown(report: dict) -> str:
    window = report["window"]
    lines = [
        "# SLA 证据（自动测量）",
        "",
        f"- 状态：**{report['status']}**",
        f"- 样本：{window['sampled_jobs']}（目标 ≥{window['min_jobs']}）",
        f"- 可用性：{report['availability']}（目标 {report['targets']['availability']}）",
        f"- 失败率：{report['failure_rate']}（目标 <{report['targets']['failure_rate']}）",
        f"- p95：{report['p95_ms']} ms（目标 ≤{report['targets']['p95_ms']}）",
        f"- 错误预算消耗：{report['error_budget_used']}",
        "",
        "## 状态分布",
        "",
        f"`{report['statuses']}`",
        "",
        "## 待外部输入",
        "",
        *[f"- {item}" for item in report["inputs_needed"]],
        "",
        "> 未取得生产/试点流量前，本报告只证明测量链路可用，不构成 SLA 达标证据。",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
