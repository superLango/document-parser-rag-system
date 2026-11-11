"""M4 review audit: risk distribution, silent errors and human-review load.

Usage:
    python -m tools.review_audit --runs runs/m2_baseline \
      --out eval/m4.json --md eval/m4.md
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from metal_doc_agent.contracts import DocumentResult, Evidence
from metal_doc_agent.review import (
    FeedbackStore,
    audit_document,
    field_risks,
    document_risk_level,
    review_metrics,
    summarize_audits,
)

ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", default=str(ROOT / "runs" / "m2_baseline"))
    parser.add_argument("--feedback", default=str(ROOT / "data" / "feedback"))
    parser.add_argument("--out", default=str(ROOT / "eval" / "m4.json"))
    parser.add_argument("--md", default=str(ROOT / "eval" / "m4.md"))
    args = parser.parse_args(argv)

    docs: list[dict] = []
    audits = []
    all_risks = []
    for result_path in sorted(Path(args.runs).glob("*/result.json")):
        result = DocumentResult.model_validate_json(result_path.read_text(encoding="utf-8"))
        evidence = _load_evidence(result_path.parent / "evidence.jsonl")
        risks = field_risks(result, evidence)
        all_risks.extend(risks)
        audit = audit_document(result, evidence)
        audits.append(audit)
        docs.append(
            {
                "doc_id": result.document.doc_id,
                "records": len(result.records),
                "fields": len(risks),
                "risk_level": document_risk_level(risks),
                "risk_counts": {
                    level: sum(1 for item in risks if item.level == level)
                    for level in ("high", "medium", "low")
                },
                "high_risk_fields": [
                    item.field_path for item in risks if item.level == "high"
                ][:20],
                "silent_errors": [item.to_dict() for item in audit.findings],
            }
        )

    silent = summarize_audits(audits)
    risk_docs = Counter(doc["risk_level"] for doc in docs)
    risk_fields = Counter()
    for doc in docs:
        for level, count in doc["risk_counts"].items():
            risk_fields[level] += count

    events = FeedbackStore(args.feedback).list() if Path(args.feedback).exists() else []
    changed_docs = {
        event.doc_id for event in events if event.action in {"edit", "reject"}
    }
    queue = sorted(
        (
            {
                "doc_id": doc["doc_id"],
                "risk_level": doc["risk_level"],
                "high": doc["risk_counts"]["high"],
                "medium": doc["risk_counts"]["medium"],
                "score": doc["risk_counts"]["high"] * 3 + doc["risk_counts"]["medium"],
            }
            for doc in docs
        ),
        key=lambda item: (-item["score"], item["doc_id"]),
    )
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "runs": str(Path(args.runs)),
        "documents": len(docs),
        "records": sum(doc["records"] for doc in docs),
        "fields": sum(doc["fields"] for doc in docs),
        "risk_documents": dict(risk_docs),
        "risk_fields": dict(risk_fields),
        "silent": silent,
        "review_queue": queue[:10],
        "review": review_metrics(
            events,
            documents_confirmed=len(docs),
            documents_with_changes=len(changed_docs),
            risks=all_risks,
        ),
        "details": docs,
        "targets": {
            "silent_error": "0/50 documents",
            "high_risk_interception": 1.0,
            "documents_audited": len(docs),
        },
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    Path(args.md).write_text(render_markdown(report), encoding="utf-8")
    print(
        json.dumps(
            {
                "documents": report["documents"],
                "silent_errors": silent["silent_errors"],
                "silent_docs": silent["documents_with_errors"],
                "risk_documents": report["risk_documents"],
                "risk_fields": report["risk_fields"],
            },
            ensure_ascii=False,
        )
    )
    print(f"out={out}")
    return 0


def _load_evidence(path: Path) -> list[Evidence]:
    if not path.exists():
        return []
    return [
        Evidence.model_validate(json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def render_markdown(report: dict) -> str:
    silent = report["silent"]
    lines = [
        "# M4 复核审计报告",
        "",
        f"- 文档：{report['documents']}（目标抽样 50）",
        f"- 记录 / 字段：{report['records']} / {report['fields']}",
        "",
        "| 指标 | 值 | 目标 |",
        "|---|---|---|",
        f"| silent error | {silent['silent_errors']}（{silent['documents_with_errors']} 份文档） | 0/50 |",
        f"| 高风险字段拦截 | {report['risk_fields'].get('high', 0)} 个待人工 | 100% |",
        f"| 文档风险分布 | {report['risk_documents']} | - |",
        f"| 字段风险分布 | {report['risk_fields']} | - |",
        f"| 反馈事件 | {report['review']['events']} | 可回流 |",
        f"| 一次通过率 | {report['review']['first_pass_rate']}（代理值） | ≥0.80 |",
        "",
        "## 错误分布",
        "",
        "| 代码 | 数量 |",
        "|---|---|",
    ]
    for code, count in sorted(silent["by_code"].items(), key=lambda item: -item[1]):
        lines.append(f"| {code} | {count} |")
    lines.extend(
        [
            "",
            "## 复核队列（按风险分排序，前 10）",
            "",
            "| 文档 | 风险 | high | medium | 分数 |",
            "|---|---|---|---|---|",
        ]
    )
    for item in report["review_queue"]:
        lines.append(
            f"| {item['doc_id']} | {item['risk_level']} | {item['high']} | "
            f"{item['medium']} | {item['score']} |"
        )
    lines.extend(
        [
            "",
            "## 分文档",
            "",
            "| 文档 | 记录 | 字段 | 风险级别 | high/medium/low | silent |",
            "|---|---|---|---|---|---|",
        ]
    )
    for doc in report["details"]:
        counts = doc["risk_counts"]
        lines.append(
            f"| {doc['doc_id']} | {doc['records']} | {doc['fields']} | {doc['risk_level']} | "
            f"{counts['high']}/{counts['medium']}/{counts['low']} | {len(doc['silent_errors'])} |"
        )
    lines.extend(
        [
            "",
            "## 说明",
            "",
            "- silent error 规则：无证据、证据不可解析、证据缺行列、数值与引文不符、机械量缺单位。",
            "- 一次通过率为代理值：以无 edit/reject 的确认文档占比计算，尚无真实人工事件时为 1.0。",
            "- 高风险字段 = 缺证据/证据不可解析/数值或区间边界缺失（触发确认闸门）。",
            "- medium = 关键力学属性（Rm/Rp0.2/A/Z/KV2/硬度/CEV/Pcm）开放区间或缺单位；化学元素常规上限为 low，可批量接受。",
            "",
        ]
    )
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
