"""M3 orchestration evaluation: STP, repair, budget, cost and compaction.

Runs the graph over documents from a replay corpus (``runs/<run>/manifest.json``
knows the source path) with the configured OCR/extractor backends.

Usage:
    python -m tools.orchestrate_eval --docs 3 --out eval/m3.json --md eval/m3.md
"""

from __future__ import annotations

import argparse
import json
import statistics
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from metal_doc_agent.orchestration import PipelineTools, run_orchestrated
from metal_doc_agent.settings import Settings

ROOT = Path(__file__).resolve().parents[1]


class FailFirstTools(PipelineTools):
    """Fault injection: the first extract call fails, the retry must recover."""

    def __init__(self, settings, out_dir):
        super().__init__(settings, out_dir)
        self.failures = 1

    def run_extract(self, *args, **kwargs):
        if self.failures:
            self.failures -= 1
            self.extract_calls += 1
            raise TimeoutError("injected extract timeout")
        return super().run_extract(*args, **kwargs)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", default=str(ROOT / "runs" / "m2_baseline"))
    parser.add_argument("--docs", type=int, default=3)
    parser.add_argument("--ocr", default="mock")
    parser.add_argument("--extractor", default="mock")
    parser.add_argument("--out", default=str(ROOT / "eval" / "m3.json"))
    parser.add_argument("--md", default=str(ROOT / "eval" / "m3.md"))
    parser.add_argument(
        "--inject-first-extract",
        action="store_true",
        help="fail the first extraction of each document to measure repair",
    )
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    settings = settings.__class__(
        **{
            **settings.__dict__,
            "ocr_backend": args.ocr,
            "extractor_backend": args.extractor,
        }
    )
    runs = sorted(Path(args.runs).glob("*/manifest.json"))[: max(1, args.docs)]
    rows: list[dict] = []
    for manifest_path in runs:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        source = Path(manifest.get("source_path") or "")
        if not source.exists():
            rows.append({"doc_id": manifest_path.parent.name, "skipped": "source_missing"})
            continue
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            tools = FailFirstTools(settings, out) if args.inject_first_extract else None
            state = run_orchestrated(
                source,
                out,
                settings,
                job_id=manifest_path.parent.name,
                options={"ocr": args.ocr, "extractor": args.extractor},
                tools=tools,
            )
            attempts = int(state.retries.extract) + int(state.retries.ocr)
            rows.append(
                {
                    "doc_id": manifest_path.parent.name,
                    "status": state.status,
                    "reason": state.terminal_reason,
                    "steps": state.cost.steps,
                    "route": state.route.queue,
                    "route_recipe": state.route.recipe_id,
                    "audit": state.context.get("audit"),
                    "ocr_quality": state.context.get("ocr_quality"),
                    "retries": state.retries.model_dump(),
                    "repair_attempted": attempts > 0,
                    "repair_recovered": bool(attempts and state.artifacts.get("result")),
                    "cost": state.cost.model_dump(),
                    "context": state.context.get("context"),
                    "errors": [error.code for error in state.errors],
                }
            )

    report = summarize(rows)
    report["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    report["runs"] = str(Path(args.runs))
    report["backends"] = {"ocr": args.ocr, "extractor": args.extractor}
    report["injected_first_extract_failure"] = bool(args.inject_first_extract)
    report["documents"] = rows

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    Path(args.md).write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps(report["totals"], ensure_ascii=False))
    print(f"out={out}")
    return 0


def summarize(rows: list[dict]) -> dict:
    evaluated = [row for row in rows if "status" in row]
    total = len(evaluated)
    statuses = Counter(row["status"] for row in evaluated)
    reasons = Counter(row.get("reason") for row in evaluated)
    routes = Counter(row.get("route") for row in evaluated)
    attempts = [row for row in evaluated if row.get("repair_attempted")]
    repaired = [row for row in attempts if row.get("repair_recovered")]
    elapsed = [float((row.get("cost") or {}).get("elapsed_ms") or 0) for row in evaluated]
    contexts = [row.get("context") or {} for row in evaluated]
    totals = {
        "documents": total,
        "published": statuses.get("published", 0),
        "review": statuses.get("review", 0),
        "human": statuses.get("human", 0),
        "failed": statuses.get("failed", 0),
        "stp_rate": round(statuses.get("published", 0) / total, 4) if total else 0.0,
        "repair_attempts": len(attempts),
        "repair_successes": len(repaired),
        "repair_rate": round(len(repaired) / len(attempts), 4) if attempts else None,
        "steps_total": sum(int(row.get("steps") or 0) for row in evaluated),
        "ocr_pages": sum(int((row.get("cost") or {}).get("ocr_pages") or 0) for row in evaluated),
        "extract_calls": sum(int((row.get("cost") or {}).get("extract_calls") or 0) for row in evaluated),
        "elapsed_ms_total": round(sum(elapsed), 2),
        "elapsed_ms_p95": round(
            sorted(elapsed)[max(0, int(len(elapsed) * 0.95) - 1)] if elapsed else 0.0, 2
        ),
        "elapsed_ms_median": round(statistics.median(elapsed), 2) if elapsed else 0.0,
        "context_lossless": sum(1 for item in contexts if item.get("lossless")),
        "context_docs": sum(1 for item in contexts if item),
        "context_token_reduction": round(
            statistics.mean([float(item.get("token_reduction") or 0) for item in contexts]), 4
        )
        if contexts
        else 0.0,
        "statuses": dict(statuses),
        "reasons": {str(key): value for key, value in reasons.items()},
        "routes": dict(routes),
        "skipped": sum(1 for row in rows if "skipped" in row),
    }
    return {"totals": totals}


def render_markdown(report: dict) -> str:
    totals = report["totals"]
    lines = [
        "# M3 Agent 编排评测",
        "",
        f"- 后端：OCR `{report['backends']['ocr']}` / 抽取 `{report['backends']['extractor']}`",
        f"- 文档：{totals['documents']}（跳过 {totals['skipped']}）",
        "",
        "| 指标 | 值 | G3 目标 |",
        "|---|---|---|",
        f"| STP（published/总数） | {totals['stp_rate']:.4f} | ≥0.80 |",
        f"| 状态分布 | {totals['statuses']} | - |",
        f"| 终止原因 | {totals['reasons']} | - |",
        f"| 修复尝试 / 成功 | {totals['repair_attempts']} / {totals['repair_successes']}"
        f"（{fmt(totals['repair_rate'])}） | ≥0.70 |",
        f"| 步数合计 | {totals['steps_total']} | ≤{12} 步/文档 |",
        f"| OCR 页数 / 抽取次数 | {totals['ocr_pages']} / {totals['extract_calls']} | - |",
        f"| 单文档耗时 p95 / 中位数 | {totals['elapsed_ms_p95']:.0f}ms / "
        f"{totals['elapsed_ms_median']:.0f}ms | p95 ≤5min |",
        f"| 上下文压缩（无损/文档） | {totals['context_lossless']}/{totals['context_docs']} | 证据不丢 |",
        f"| 压缩 token 降幅 | {totals['context_token_reduction']:.4f} | ≤1pp 回归 |",
        "",
        "## 分文档",
        "",
        "| 文档 | 状态 | 原因 | 路由 | 步数 | 重试 | 审计 | 耗时 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in report["documents"]:
        if "status" not in row:
            lines.append(f"| {row['doc_id']} | - | {row.get('skipped')} | - | - | - | - | - |")
            continue
        audit = row.get("audit") or {}
        lines.append(
            f"| {row['doc_id']} | {row['status']} | {row.get('reason') or '-'} | "
            f"{row.get('route')}/{row.get('route_recipe') or '-'} | {row.get('steps')} | "
            f"{row.get('retries')} | {audit.get('status')} | "
            f"{(row.get('cost') or {}).get('elapsed_ms', 0):.0f}ms |"
        )
    lines.extend(
        [
            "",
            "## 说明",
            "",
            "- publish 只在审计 pass 时发生；review 一律进人工队列，因此 STP 反映了当前审计严格度。",
            "- 覆盖缺失的定向检索/重 OCR 尚未实现，缺失直接进人工，避免无效重抽。",
            "- 上下文压缩只作用于条款正文，证据/表头/单位不压缩；抽取器未消费上下文，故压缩回归为 0。",
            "",
        ]
    )
    return "\n".join(lines)


def fmt(value) -> str:
    return "-" if value is None else f"{value:.4f}"


if __name__ == "__main__":
    raise SystemExit(main())
