"""未解决队列审计：按文档/类别/原因聚合，输出可读报告。"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def audit_verification_files(files: list[Path]) -> dict[str, Any]:
    reason_counts: Counter = Counter()
    category_counts: Counter = Counter()
    doc_counts: Counter = Counter()
    reason_examples: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for path in files:
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        queue = payload.get("queue") or []
        doc = path.parents[2].name if len(path.parents) > 2 else path.parent.name
        if queue:
            doc_counts[doc] += len(queue)
        for item in queue:
            category_counts[str(item.get("category") or "")] += 1
            for reason in item.get("reasons") or []:
                code = str(reason.get("code") or "")
                reason_counts[code] += 1
                if len(reason_examples[code]) < 3:
                    reason_examples[code].append({
                        "doc": doc,
                        "record_id": item.get("record_id"),
                        "category": item.get("category"),
                        "item": item.get("item"),
                        "requirement": item.get("requirement"),
                        "message": reason.get("message"),
                    })
    return {
        "documents": len(files),
        "queue_total": sum(doc_counts.values()),
        "by_reason": dict(reason_counts.most_common()),
        "by_category": dict(category_counts.most_common()),
        "top_documents": dict(doc_counts.most_common(10)),
        "examples": dict(reason_examples),
    }


def render_markdown(audit: dict[str, Any], title: str = "未解决队列审计") -> str:
    lines = [f"# {title}", "",
             f"- 文档数：{audit.get('documents')}",
             f"- 队列记录：{audit.get('queue_total')}", "",
             "## 按原因", ""]
    for code, count in (audit.get("by_reason") or {}).items():
        lines.append(f"- {code}: {count}")
    lines += ["", "## 按类别", ""]
    for category, count in (audit.get("by_category") or {}).items():
        lines.append(f"- {category}: {count}")
    lines += ["", "## 队列最多的文档", ""]
    for doc, count in (audit.get("top_documents") or {}).items():
        lines.append(f"- {doc}: {count}")
    return "\n".join(lines) + "\n"
