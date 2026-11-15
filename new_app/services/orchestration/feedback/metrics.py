"""Feedback-loop metrics: intent, diagnosis, repair and regression quality."""

from __future__ import annotations

from collections import Counter
from typing import Any


def _pct(numerator: int | float, denominator: int | float) -> float:
    return round(float(numerator) / denominator, 4) if denominator else 0.0


def _percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(len(ordered) * ratio)) - 1))
    return round(ordered[index], 2)


def _seconds(start: str, end: str) -> float | None:
    from datetime import datetime

    try:
        left = datetime.fromisoformat(start)
        right = datetime.fromisoformat(end)
    except (TypeError, ValueError):
        return None
    return max(0.0, (right - left).total_seconds())


def _processing_seconds(item: dict[str, Any]) -> float | None:
    """Prefer message timestamps: created_at→updated_at can span reruns."""
    from datetime import datetime

    times = []
    for message in item.get("messages") or []:
        if not isinstance(message, dict):
            continue
        value = message.get("at")
        if not value:
            continue
        try:
            times.append(datetime.fromisoformat(str(value)))
        except ValueError:
            continue
    if len(times) >= 2:
        return max(0.0, (max(times) - min(times)).total_seconds())
    return _seconds(
        str(item.get("created_at") or ""), str(item.get("updated_at") or "")
    )


def _intent(item: dict[str, Any]) -> dict[str, Any]:
    root = item.get("root_cause") or {}
    return root.get("intent") or {} if isinstance(root, dict) else {}


def _diagnosis(item: dict[str, Any]) -> dict[str, Any]:
    root = item.get("root_cause") or {}
    return root.get("diagnosis") or {} if isinstance(root, dict) else {}


def _repairability(item: dict[str, Any]) -> str:
    root = item.get("root_cause") or {}
    value = root.get("repairability") if isinstance(root, dict) else {}
    return str((value or {}).get("decision") or "")


def _verification(item: dict[str, Any]) -> dict[str, Any]:
    return item.get("verification") or {}


def _is_processed(item: dict[str, Any]) -> bool:
    if item.get("triage") or item.get("proposal"):
        return True
    root = item.get("root_cause") or {}
    if isinstance(root, dict) and (root.get("triage") or root.get("intent")):
        return True
    return bool(_verification(item))


def _is_l1(item: dict[str, Any]) -> bool:
    verification = _verification(item)
    for target in verification.get("affected_targets") or []:
        if str((target or {}).get("level") or "") == "L1":
            return True
    proposal = item.get("proposal") or {}
    return str(proposal.get("scope") or "") == "data"


def _ops_count(item: dict[str, Any]) -> int:
    proposal = item.get("proposal") or {}
    patch = proposal.get("patch") or {}
    ops = patch.get("ops") if isinstance(patch, dict) else None
    if isinstance(ops, list):
        return len(ops)
    if isinstance(patch, dict) and patch.get("table_repair"):
        return 1
    return 0


def summarize_feedbacks(
    items: list[dict[str, Any]],
    *,
    gold: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Aggregate one feedback-detail list into the plan's metric set."""
    gold = gold or {}
    total = len(items)
    processed = sum(1 for item in items if _is_processed(item))
    status = Counter(str(item.get("status") or "") for item in items)
    verified = status.get("verified", 0)
    taken_over = sum(
        1
        for item in items
        if str(item.get("status") or "") == "needs_more_info"
        and _is_processed(item)
    )

    l1_attempts = 0
    l1_rollbacks = 0
    tier_counts: Counter[str] = Counter()
    check_failures: Counter[str] = Counter()
    ops_total = 0
    empty_patches = 0
    latencies: list[float] = []

    intent_rerank = 0
    clarifying = 0
    with_assumption = 0
    diagnosis_needs_model = 0
    diagnosis_model_used = 0
    expected_present = 0
    rule_change_present = 0
    evidence_present = 0
    repairability: Counter[str] = Counter()
    root_causes: Counter[str] = Counter()
    concepts: dict[str, dict[str, Any]] = {}

    top1_hits = top3_hits = labeled = 0

    for item in items:
        proposal = item.get("proposal") or {}
        verification = _verification(item)
        ops = _ops_count(item)
        ops_total += ops
        if (
            str(proposal.get("scope") or "") in {"recipe", "data"}
            and not proposal.get("needs_human")
            and ops == 0
        ):
            empty_patches += 1

        tier = str(verification.get("action_tier") or "")
        if tier:
            tier_counts[tier] += 1
        for check in verification.get("checks") or []:
            if isinstance(check, dict) and not check.get("passed"):
                check_failures[str(check.get("name") or "")] += 1

        if _is_l1(item):
            l1_attempts += 1
            if str(verification.get("decision") or "") == "rollback":
                l1_rollbacks += 1

        latency = _processing_seconds(item)
        if (
            latency is not None
            and _is_processed(item)
            and str(item.get("status") or "") in {"verified", "needs_more_info", "discarded"}
        ):
            latencies.append(latency)

        intent = _intent(item)
        if intent:
            if (intent.get("rerank") or {}).get("applied"):
                intent_rerank += 1
            if intent.get("clarifying_question"):
                clarifying += 1
            if intent.get("assumption"):
                with_assumption += 1
            concept_id = str(intent.get("concept_id") or "unknown")
            bucket = concepts.setdefault(
                concept_id,
                {
                    "concept": intent.get("concept") or "",
                    "total": 0,
                    "verified": 0,
                    "rerank": 0,
                    "clarifying": 0,
                    "labeled": 0,
                    "top1_hits": 0,
                    "top3_hits": 0,
                },
            )
            bucket["total"] += 1
            if str(item.get("status") or "") == "verified":
                bucket["verified"] += 1
            if (intent.get("rerank") or {}).get("applied"):
                bucket["rerank"] += 1
            if intent.get("clarifying_question"):
                bucket["clarifying"] += 1

        diagnosis = _diagnosis(item)
        if diagnosis:
            repairability[_repairability(item) or "unknown"] += 1
            root_causes[str(diagnosis.get("root_cause") or "unknown")] += 1
            if diagnosis.get("needs_model"):
                diagnosis_needs_model += 1
            if (diagnosis.get("model_attribution") or {}).get("applied"):
                diagnosis_model_used += 1
            if diagnosis.get("expected"):
                expected_present += 1
            if diagnosis.get("rule_change"):
                rule_change_present += 1
            if int(diagnosis.get("evidence_count") or 0) > 0:
                evidence_present += 1

        label = gold.get(str(item.get("id") or ""))
        if label and intent and intent.get("candidate_targets"):
            labeled += 1
            candidates = intent.get("candidate_targets") or []
            ids = [str((candidate or {}).get("table_id") or "") for candidate in candidates]
            expected_table = str(label.get("table_id") or "")
            if ids and ids[0] == expected_table:
                top1_hits += 1
            if expected_table and expected_table in ids[:3]:
                top3_hits += 1
            bucket = concepts.get(str(intent.get("concept_id") or "unknown"))
            if bucket is not None:
                bucket["labeled"] += 1
                if ids and ids[0] == expected_table:
                    bucket["top1_hits"] += 1
                if expected_table in ids[:3]:
                    bucket["top3_hits"] += 1

    diagnosis_total = sum(root_causes.values())
    for bucket in concepts.values():
        bucket["verified_rate"] = _pct(bucket["verified"], bucket["total"])
        bucket["rerank_rate"] = _pct(bucket["rerank"], bucket["total"])
        bucket["clarifying_rate"] = _pct(bucket["clarifying"], bucket["total"])
        bucket["top1_accuracy"] = _pct(bucket["top1_hits"], bucket["labeled"])
        bucket["top3_accuracy"] = _pct(bucket["top3_hits"], bucket["labeled"])

    return {
        "total": total,
        "processed": processed,
        "status_dist": dict(status),
        "verified": verified,
        "verified_rate": _pct(verified, processed),
        "human_takeover_rate": _pct(taken_over, processed),
        "l1_attempts": l1_attempts,
        "l1_rollbacks": l1_rollbacks,
        "l1_success_rate": _pct(l1_attempts - l1_rollbacks, l1_attempts),
        "action_tiers": dict(tier_counts),
        "check_failures": dict(check_failures),
        "patch": {
            "avg_ops": round(ops_total / processed, 2) if processed else 0.0,
            "empty_patch_rate": _pct(empty_patches, processed),
            "verified_rate": _pct(verified, processed),
        },
        "intent": {
            "rerank_rate": _pct(intent_rerank, processed),
            "clarifying_rate": _pct(clarifying, processed),
            "assumption_rate": _pct(with_assumption, processed),
            "labeled": labeled,
            "top1_accuracy": _pct(top1_hits, labeled),
            "top3_accuracy": _pct(top3_hits, labeled),
            "concepts": dict(sorted(concepts.items())),
        },
        "diagnosis": {
            "total": diagnosis_total,
            "root_causes": dict(root_causes),
            "repairability": dict(repairability),
            "needs_model_rate": _pct(diagnosis_needs_model, processed),
            "model_used_rate": _pct(diagnosis_model_used, diagnosis_needs_model),
            "expected_present_rate": _pct(expected_present, diagnosis_total),
            "rule_change_present_rate": _pct(rule_change_present, diagnosis_total),
            "evidence_present_rate": _pct(evidence_present, diagnosis_total),
        },
        "latency": {
            "samples": len(latencies),
            "p50": _percentile(latencies, 0.5),
            "p95": _percentile(latencies, 0.95),
        },
    }


def render_markdown(summary: dict[str, Any], *, title: str = "Feedback 闭环度量") -> str:
    """Render the aggregate metrics as a compact Markdown report."""
    status = "，".join(
        f"{key}={value}" for key, value in sorted(summary["status_dist"].items())
    )
    lines = [
        f"# {title}",
        "",
        "## 总体",
        "",
        "| 指标 | 值 |",
        "|---|---|",
        f"| 反馈总数 | {summary['total']} |",
        f"| 已处理 | {summary['processed']} |",
        f"| 状态分布 | {status or '-'} |",
        f"| 验证通过率 | {summary['verified']} ({summary['verified_rate']:.1%}) |",
        f"| 人工接管率 | {summary['human_takeover_rate']:.1%} |",
        f"| L1 尝试 / 回滚 | {summary['l1_attempts']} / {summary['l1_rollbacks']} |",
        f"| L1 成功率 | {summary['l1_success_rate']:.1%} |",
        f"| 平均补丁 ops | {summary['patch']['avg_ops']} |",
        f"| 空补丁率 | {summary['patch']['empty_patch_rate']:.1%} |",
        f"| 时延 p50 / p95 | {summary['latency']['p50']}s / {summary['latency']['p95']}s |",
        "",
        "## 意图",
        "",
        "| 指标 | 值 |",
        "|---|---|",
        f"| 模型重排率 | {summary['intent']['rerank_rate']:.1%} |",
        f"| 澄清率 | {summary['intent']['clarifying_rate']:.1%} |",
        f"| 已标注样本 | {summary['intent']['labeled']} |",
        f"| top-1 准确率 | {summary['intent']['top1_accuracy']:.1%} |",
        f"| top-3 准确率 | {summary['intent']['top3_accuracy']:.1%} |",
        "",
        "| 概念 | 数量 | 验证通过率 | 重排率 | top-1 |",
        "|---|---|---|---|---|",
    ]
    for concept_id, bucket in summary["intent"]["concepts"].items():
        lines.append(
            f"| {concept_id} | {bucket['total']} | "
            f"{bucket['verified_rate']:.1%} | {bucket['rerank_rate']:.1%} | "
            f"{bucket['top1_accuracy']:.1%} |"
        )
    lines.extend(
        [
            "",
            "## 诊断",
            "",
            "| 指标 | 值 |",
            "|---|---|",
            f"| 诊断覆盖 | {summary['diagnosis']['total']} |",
            f"| needs_model 率 | {summary['diagnosis']['needs_model_rate']:.1%} |",
            f"| 模型归因使用率 | {summary['diagnosis']['model_used_rate']:.1%} |",
            f"| expected 命中率 | {summary['diagnosis']['expected_present_rate']:.1%} |",
            f"| rule_change 覆盖率 | {summary['diagnosis']['rule_change_present_rate']:.1%} |",
            f"| 证据覆盖率 | {summary['diagnosis']['evidence_present_rate']:.1%} |",
            "",
            "| root_cause | 数量 |",
            "|---|---|",
        ]
    )
    for name, count in sorted(summary["diagnosis"]["root_causes"].items()):
        lines.append(f"| {name} | {count} |")
    lines.extend(
        [
            "",
            "## 门禁失败",
            "",
            "| 检查项 | 失败次数 |",
            "|---|---|",
        ]
    )
    for name, count in sorted(summary["check_failures"].items()):
        lines.append(f"| {name} | {count} |")
    lines.append("")
    return "\n".join(lines)
