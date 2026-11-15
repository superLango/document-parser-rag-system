#!/usr/bin/env python3
"""Release gate: 50-document legacy regression with governance thresholds.

Reuses the M8 comparison harness (same reconstructed tables, same field keys)
and fails with a non-zero exit code when the governance targets regress:

    Field F1 >= 0.60, silent error rate <= 3%, coverage >= 90%, 0 failed runs.

The human gold standard (30 documents) is reported separately from
``gold-eval.json``.  Pass ``--require-gold`` to also gate on the Phase 3 gold
thresholds (Field F1 >= 0.80, silent <= 2%, coverage >= 90%).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx
from m8_effect_compare import (
    DEFAULT_API,
    DEFAULT_OLD_RUNS,
    aggregate,
    compare_doc,
    load_candidates,
    new_parse,
    render_markdown,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_GOLD_EVAL = REPO_ROOT / "new_app" / "docs" / "reports" / "gold-eval.json"
DEFAULT_OUT_JSON = REPO_ROOT / "new_app" / "docs" / "reports" / "scale-gate.json"
DEFAULT_OUT_MD = REPO_ROOT / "new_app" / "docs" / "reports" / "scale-gate.md"
GATE = {
    "field_f1": 0.60,
    "silent_error_rate": 0.03,
    "coverage": 0.90,
}
GOLD_GATE = {
    "field_f1": 0.80,
    "silent_error_rate": 0.02,
    "coverage": 0.90,
}


def load_gold_summary(path: Path) -> dict:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload.get("summary") or {}


def gold_failures(summary: dict) -> list[str]:
    if not summary:
        return ["gold-eval.json 不存在或没有 summary"]
    failures = []
    if summary.get("f1", 0) < GOLD_GATE["field_f1"]:
        failures.append(
            f"gold Field F1 {summary.get('f1', 0):.4f} < {GOLD_GATE['field_f1']:.2f}"
        )
    if summary.get("silent_rate", 1) > GOLD_GATE["silent_error_rate"]:
        failures.append(
            f"gold silent {summary.get('silent_rate', 1):.4f} > "
            f"{GOLD_GATE['silent_error_rate']:.2f}"
        )
    if summary.get("coverage", 0) < GOLD_GATE["coverage"]:
        failures.append(
            f"gold coverage {summary.get('coverage', 0):.4f} < {GOLD_GATE['coverage']:.2f}"
        )
    return failures


def evaluate(metrics: dict) -> list[str]:
    failures = []
    if metrics["field_f1"] < GATE["field_f1"]:
        failures.append(
            f"field_f1 {metrics['field_f1']:.4f} < {GATE['field_f1']:.2f}"
        )
    if metrics["silent_error_rate"] > GATE["silent_error_rate"]:
        failures.append(
            f"silent_error_rate {metrics['silent_error_rate']:.4f} > "
            f"{GATE['silent_error_rate']:.2f}"
        )
    if metrics["coverage"] < GATE["coverage"]:
        failures.append(f"coverage {metrics['coverage']:.4f} < {GATE['coverage']:.2f}")
    if metrics["failed_runs"]:
        failures.append(f"failed_runs {metrics['failed_runs']} != 0")
    return failures


def write_report(path: Path, metrics: dict, gold: dict, failures: list[str]) -> None:
    lines = [
        "# 规模化回归门禁",
        "",
        f"> 样本：{metrics['documents']} 份",
        f"> 结论：**{'通过' if not failures else '未通过'}**",
        "",
        "| 指标 | 结果 | 门槛 |",
        "|---|---|---|",
        f"| Field F1 | {metrics['field_f1']:.4f} | ≥ {GATE['field_f1']:.2f} |",
        f"| 静默错误率 | {metrics['silent_error_rate']:.4f} | ≤ {GATE['silent_error_rate']:.2f} |",  # noqa: E501
        f"| 覆盖率 | {metrics['coverage']:.4f} | ≥ {GATE['coverage']:.2f} |",
        f"| 失败运行 | {metrics['failed_runs']} | 0 |",
        f"| 共同字段 | {metrics['common_fields']} | 参考 |",
        f"| p95 延迟 | {metrics['p95_seconds']:.2f}s | 参考 |",
        "",
        f"- 金标：{gold.get('documents', 0)} 份 / {gold.get('gold', 0)} 条可评测 items，"
        f"Field F1 {gold.get('f1', 0):.4f}，静默 {gold.get('silent_rate', 0):.4f}，"
        f"覆盖率 {gold.get('coverage', 0):.4f}",
    ]
    if failures:
        lines.extend(["", "## 未通过项", ""])
        lines.extend(f"- {item}" for item in failures)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old-runs", type=Path, default=DEFAULT_OLD_RUNS)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--api", default=DEFAULT_API)
    parser.add_argument("--gold-eval", type=Path, default=DEFAULT_GOLD_EVAL)
    parser.add_argument("--require-gold", action="store_true")
    parser.add_argument("--out-json", type=Path, default=DEFAULT_OUT_JSON)
    parser.add_argument("--out-md", type=Path, default=DEFAULT_OUT_MD)
    args = parser.parse_args()

    candidates = load_candidates(args.old_runs, args.limit)
    if not candidates:
        print("no comparable documents found")
        return 1

    def process(item: dict) -> dict:
        markdown = render_markdown(item["result"])
        name = f"scale-gate-{item['doc_id'][:12]}.md"
        try:
            with httpx.Client(timeout=180) as client:
                new = new_parse(client, args.api.rstrip("/"), markdown, name)
        except Exception as exc:  # noqa: BLE001 - recorded in the report
            new = {
                "run_id": "",
                "status": "ERROR",
                "error_code": str(exc)[:200],
                "elapsed_seconds": 0.0,
                "records": [],
                "result": {},
            }
        return compare_doc(item, new)

    docs = [process(item) for item in candidates]
    metrics = aggregate(docs)
    gold_summary = load_gold_summary(args.gold_eval)
    failures = evaluate(metrics)
    if args.require_gold:
        failures.extend(gold_failures(gold_summary))

    payload = {
        "generated_at": metrics.get("generated_at", ""),
        "gate": GATE,
        "gold_gate": GOLD_GATE,
        "metrics": metrics,
        "gold": gold_summary,
        "failures": failures,
    }
    args.out_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    write_report(args.out_md, metrics, gold_summary, failures)
    print(json.dumps({"metrics": metrics, "gold": gold_summary, "failures": failures},
                     ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
