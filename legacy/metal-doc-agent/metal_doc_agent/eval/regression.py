"""Evaluation regression baselines.

M1-S7 freezes a baseline so later model/prompt/recipe changes can be compared
against the same goldset and metric definitions.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CORE_METRICS = (
    "record_f1",
    "field_f1",
    "value_accuracy",
    "inspection_accuracy",
    "classification_accuracy",
    "clause_accuracy",
    "evidence_rate",
    "coverage_rate",
)
DEFAULT_TOLERANCE = 0.01


def build_regression(
    payload: dict[str, Any],
    label: str = "m1",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    summary = payload.get("summary", {})
    documents = payload.get("documents", [])
    return {
        "regression_version": 1,
        "label": label,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "schema_version": payload.get("schema_version"),
        "goldset_version": payload.get("goldset_version"),
        "metadata": metadata or {},
        "summary": {name: summary.get(name, 0.0) for name in CORE_METRICS},
        "documents": {
            doc["doc_id"]: {name: doc.get(name, 0.0) for name in CORE_METRICS}
            for doc in documents
        },
    }


def write_regression(baseline: dict[str, Any], path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(baseline, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def load_regression(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def compare_regression(
    payload: dict[str, Any],
    baseline: dict[str, Any],
    tolerance: float = DEFAULT_TOLERANCE,
) -> dict[str, Any]:
    current = payload.get("summary", {})
    base_summary = baseline.get("summary", {})
    deltas: dict[str, float] = {}
    items: dict[str, dict[str, float]] = {}
    regressions: list[dict[str, Any]] = []
    improvements: list[dict[str, Any]] = []
    for name in CORE_METRICS:
        before = round(float(base_summary.get(name, 0.0)), 4)
        after = round(float(current.get(name, 0.0)), 4)
        delta = round(after - before, 4)
        deltas[name] = delta
        items[name] = {"baseline": before, "current": after, "delta": delta}
        item = {"metric": name, "baseline": before, "current": after, "delta": delta}
        if delta < -tolerance:
            regressions.append(item)
        elif delta > tolerance:
            improvements.append(item)

    current_docs = {doc["doc_id"]: doc for doc in payload.get("documents", [])}
    doc_regressions: list[dict[str, Any]] = []
    for doc_id, base_doc in baseline.get("documents", {}).items():
        doc = current_docs.get(doc_id)
        if not doc:
            continue
        for name in CORE_METRICS:
            before = round(float(base_doc.get(name, 0.0)), 4)
            after = round(float(doc.get(name, 0.0)), 4)
            delta = round(after - before, 4)
            if delta < -tolerance:
                doc_regressions.append(
                    {
                        "doc_id": doc_id,
                        "metric": name,
                        "baseline": before,
                        "current": after,
                        "delta": delta,
                    }
                )

    return {
        "baseline_label": baseline.get("label"),
        "tolerance": tolerance,
        "deltas": deltas,
        "items": items,
        "regressions": regressions,
        "improvements": improvements,
        "doc_regressions": doc_regressions,
        "passed": not regressions,
    }


def render_regression_markdown(comparison: dict[str, Any]) -> str:
    lines = [
        "# 回归对比",
        "",
        f"- 基线：{comparison.get('baseline_label') or 'unknown'}",
        f"- 容差：{comparison['tolerance']}",
        f"- 结论：{'通过' if comparison['passed'] else '存在回退'}",
    ]
    if comparison["regressions"]:
        lines.extend(["", "## 回退", "", "| 指标 | 基线 | 当前 | 变化 |", "|---|---|---|---|"])
        for item in comparison["regressions"]:
            lines.append(
                f"| {item['metric']} | {item['baseline']} | {item['current']} | {item['delta']} |"
            )
    if comparison["improvements"]:
        lines.extend(["", "## 提升", "", "| 指标 | 基线 | 当前 | 变化 |", "|---|---|---|---|"])
        for item in comparison["improvements"]:
            lines.append(
                f"| {item['metric']} | {item['baseline']} | {item['current']} | {item['delta']} |"
            )
    if comparison["doc_regressions"]:
        lines.extend(["", "## 文档级回退", "", "| 文档 | 指标 | 基线 | 当前 | 变化 |", "|---|---|---|---|---|"])
        for item in comparison["doc_regressions"][:50]:
            lines.append(
                f"| {item['doc_id']} | {item['metric']} | {item['baseline']} | "
                f"{item['current']} | {item['delta']} |"
            )
    return "\n".join(lines)
