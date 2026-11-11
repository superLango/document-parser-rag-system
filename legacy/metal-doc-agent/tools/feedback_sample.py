"""Feedback sampling and correction accuracy (C7).

Samples review events deterministically, enriches them with risk level/evidence
from replayed runs, and computes correction accuracy once domain annotations
exist.

Annotation interface (one JSON object per line):
    {"event_id": "rev-...", "verdict": "correct" | "incorrect" | "unsure",
     "reason": "..."}

Usage:
    python -m tools.feedback_sample --feedback data/feedback \
      --runs runs/m2_baseline --rate 0.2 \
      --samples eval/feedback-samples.jsonl \
      --annotations data/feedback/annotations.jsonl \
      --out eval/feedback.json --md eval/feedback.md
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from metal_doc_agent.contracts import DocumentResult, Evidence
from metal_doc_agent.review import FeedbackStore, ReviewEvent, field_risks

ROOT = Path(__file__).resolve().parents[1]
VERDICTS = {"correct", "incorrect", "unsure"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feedback", default=str(ROOT / "data" / "feedback"))
    parser.add_argument("--runs", default=str(ROOT / "runs" / "m2_baseline"))
    parser.add_argument("--annotations", default=None)
    parser.add_argument("--rate", type=float, default=0.2)
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--seed", default="m4")
    parser.add_argument("--samples", default=str(ROOT / "eval" / "feedback-samples.jsonl"))
    parser.add_argument("--out", default=str(ROOT / "eval" / "feedback.json"))
    parser.add_argument("--md", default=str(ROOT / "eval" / "feedback.md"))
    args = parser.parse_args(argv)

    events = FeedbackStore(args.feedback).list() if Path(args.feedback).exists() else []
    risks = _load_risks(Path(args.runs))
    sampled = sample_events(events, rate=args.rate, limit=args.limit, seed=args.seed)
    rows = [_sample_row(event, risks) for event in sampled]

    samples_path = Path(args.samples)
    samples_path.parent.mkdir(parents=True, exist_ok=True)
    samples_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )

    annotations = _load_annotations(Path(args.annotations)) if args.annotations else {}
    metrics = _accuracy(rows, annotations)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "feedback": str(Path(args.feedback)),
        "runs": str(Path(args.runs)),
        "events": len(events),
        "event_actions": dict(Counter(event.action for event in events)),
        "sampled": len(rows),
        "rate": args.rate,
        "annotations": len(annotations),
        **metrics,
        "samples": str(samples_path),
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    Path(args.md).write_text(render_markdown(report, rows), encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("events", "sampled", "annotations", "accuracy")}, ensure_ascii=False))
    print(f"out={out}")
    return 0


def sample_events(
    events: list[ReviewEvent], *, rate: float, limit: int, seed: str
) -> list[ReviewEvent]:
    """Deterministic hash sampling so reruns annotate the same rows."""
    ordered = sorted(
        events,
        key=lambda event: hashlib.sha256(
            f"{seed}:{event.event_id}".encode("utf-8")
        ).hexdigest(),
    )
    if rate <= 0:
        return []
    count = max(1, min(limit, int(round(len(ordered) * min(rate, 1.0)))))
    return ordered[:count]


def _load_risks(runs: Path) -> dict[tuple[str, str], dict]:
    risks: dict[tuple[str, str], dict] = {}
    for result_path in sorted(runs.glob("*/result.json")):
        try:
            result = DocumentResult.model_validate_json(
                result_path.read_text(encoding="utf-8")
            )
        except ValueError:
            continue
        evidence = _load_evidence(result_path.parent / "evidence.jsonl")
        for item in field_risks(result, evidence):
            risks[(result.document.doc_id, item.field_path)] = {
                "level": item.level,
                "evidence_id": item.evidence_id,
                "page_no": item.page_no,
            }
    return risks


def _load_evidence(path: Path) -> list[Evidence]:
    if not path.exists():
        return []
    return [
        Evidence.model_validate(json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _sample_row(event: ReviewEvent, risks: dict[tuple[str, str], dict]) -> dict:
    risk = risks.get((event.doc_id, event.field_path)) or {}
    return {
        "event_id": event.event_id,
        "doc_id": event.doc_id,
        "field_path": event.field_path,
        "action": event.action,
        "old_value": event.old_value,
        "new_value": event.new_value,
        "reason": event.reason,
        "reviewer": event.reviewer,
        "risk_level": risk.get("level") or "unknown",
        "evidence_id": risk.get("evidence_id"),
        "page_no": risk.get("page_no"),
    }


def _load_annotations(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    annotations: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        event_id = str(payload.get("event_id") or "")
        verdict = str(payload.get("verdict") or "").lower()
        if event_id and verdict in VERDICTS:
            annotations[event_id] = verdict
    return annotations


def _accuracy(rows: list[dict], annotations: dict[str, str]) -> dict:
    judged = [annotations[row["event_id"]] for row in rows if row["event_id"] in annotations]
    decided = [verdict for verdict in judged if verdict in {"correct", "incorrect"}]
    by_action: dict[str, Counter] = defaultdict(Counter)
    by_risk: dict[str, Counter] = defaultdict(Counter)
    for row in rows:
        verdict = annotations.get(row["event_id"])
        if verdict not in {"correct", "incorrect"}:
            continue
        by_action[row["action"]][verdict] += 1
        by_risk[row["risk_level"]][verdict] += 1
    return {
        "annotated": len(judged),
        "judged": len(decided),
        "correct": sum(1 for verdict in decided if verdict == "correct"),
        "incorrect": sum(1 for verdict in decided if verdict == "incorrect"),
        "unsure": sum(1 for verdict in judged if verdict == "unsure"),
        "accuracy": round(
            sum(1 for verdict in decided if verdict == "correct") / len(decided), 4
        )
        if decided
        else None,
        "by_action": {key: dict(value) for key, value in by_action.items()},
        "by_risk": {key: dict(value) for key, value in by_risk.items()},
    }


def render_markdown(report: dict, rows: list[dict]) -> str:
    accuracy = report["accuracy"]
    lines = [
        "# 反馈抽检与修正正确率",
        "",
        f"- 反馈事件：{report['events']}（{report['event_actions']}）",
        f"- 抽样：{report['sampled']}（rate={report['rate']}）",
        f"- 已标注：{report['annotated']}，有效判定：{report['judged']}",
        f"- 修正正确率：{accuracy if accuracy is not None else '未标注'}",
        "",
        "| 指标 | 值 |",
        "|---|---|",
        f"| correct / incorrect / unsure | {report['correct']} / {report['incorrect']} / {report['unsure']} |",
        f"| 按动作 | {report['by_action']} |",
        f"| 按风险 | {report['by_risk']} |",
        "",
        "## 抽样明细",
        "",
        "| event | 文档 | 字段 | 动作 | 风险 | 人工值 |",
        "|---|---|---|---|---|---|",
    ]
    for row in rows[:20]:
        lines.append(
            f"| {row['event_id']} | {row['doc_id']} | {row['field_path']} | "
            f"{row['action']} | {row['risk_level']} | {json.dumps(row['new_value'], ensure_ascii=False)[:40]} |"
        )
    lines.extend(
        [
            "",
            "## 标注接口",
            "",
            "`data/feedback/annotations.jsonl`，每行 `{event_id, verdict, reason}`；",
            "verdict 取 `correct` / `incorrect` / `unsure`，由领域专家回填后重跑本工具。",
            "",
        ]
    )
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
