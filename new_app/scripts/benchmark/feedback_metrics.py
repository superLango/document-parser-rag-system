#!/usr/bin/env python3
"""Aggregate feedback-loop metrics from the orchestration feedback API.

Examples::

    python scripts/benchmark/feedback_metrics.py \
        --api http://localhost:18001 \
        --json-out docs/reports/feedback-metrics.json \
        --md-out docs/reports/feedback-metrics.md

Optional gold labels (for intent top-1/top-3)::

    {"labels": {"<feedback_id>": {"table_id": "T12", "concept_id": "tensile_room"}}}
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import httpx

NEW_APP = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(NEW_APP))

from services.orchestration.feedback.metrics import (  # noqa: E402
    render_markdown,
    summarize_feedbacks,
)


def load_gold(path: str) -> dict[str, dict[str, Any]]:
    if not path:
        return {}
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    labels = payload.get("labels") if isinstance(payload, dict) else payload
    return {
        str(key): value
        for key, value in (labels or {}).items()
        if isinstance(value, dict)
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://localhost:18001")
    parser.add_argument("--gold", default="")
    parser.add_argument("--json-out", default="")
    parser.add_argument("--md-out", default="")
    parser.add_argument("--title", default="Feedback 闭环度量")
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args()

    with httpx.Client(timeout=args.timeout) as client:
        response = client.get(f"{args.api.rstrip('/')}/internal/feedback")
        response.raise_for_status()
        items = response.json()

    summary = summarize_feedbacks(items, gold=load_gold(args.gold))
    if args.json_out:
        path = Path(args.json_out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    if args.md_out:
        path = Path(args.md_out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_markdown(summary, title=args.title), encoding="utf-8")

    print(
        f"total={summary['total']} processed={summary['processed']} "
        f"verified={summary['verified']} "
        f"verified_rate={summary['verified_rate']:.1%} "
        f"l1={summary['l1_attempts']}/{summary['l1_rollbacks']} "
        f"p50={summary['latency']['p50']}s p95={summary['latency']['p95']}s"
    )
    print(
        f"intent: rerank={summary['intent']['rerank_rate']:.1%} "
        f"clarify={summary['intent']['clarifying_rate']:.1%} "
        f"top1={summary['intent']['top1_accuracy']:.1%} "
        f"(labeled={summary['intent']['labeled']})"
    )
    print(
        f"diagnosis: needs_model={summary['diagnosis']['needs_model_rate']:.1%} "
        f"model_used={summary['diagnosis']['model_used_rate']:.1%} "
        f"expected={summary['diagnosis']['expected_present_rate']:.1%} "
        f"evidence={summary['diagnosis']['evidence_present_rate']:.1%}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
