"""Action tiers: decide auto-apply / review / human for a verified repair."""

from __future__ import annotations

from typing import Any

TIER_AUTO = "auto"
TIER_REVIEW = "review"
TIER_HUMAN = "human"

REVIEW_PATHS = ("/rules/strategy_chain", "/rules/nonrecord")
RISKY_BINDING_PREFIX = "/bindings/measures/"


def classify_action(
    *,
    level: str,
    operator: str = "",
    ops: list[dict[str, Any]] | None = None,
    advisory_count: int = 0,
) -> dict[str, Any]:
    """Return the action tier and the reasons behind it."""
    ops = ops or []
    reasons: list[str] = []
    tier = TIER_REVIEW

    if level == "L3":
        tier = TIER_HUMAN
        reasons.append("L3 代码补丁必须人工审批")
    elif level == "L1":
        tier = TIER_AUTO
        reasons.append("L1 单表修复只影响当前文档")
    else:
        reasons.append("L2 配方变更默认需要复审")

    risky = [
        op
        for op in ops
        if str(op.get("op") or "") == "remove"
        and str(op.get("path") or "").startswith(RISKY_BINDING_PREFIX)
    ]
    if risky:
        tier = TIER_REVIEW
        reasons.append("删除既有 measure 绑定需要复审")

    for op in ops:
        path = str(op.get("path") or "")
        if any(path.startswith(prefix) for prefix in REVIEW_PATHS):
            tier = TIER_REVIEW
            reasons.append(f"规则变更 {path} 需要复审")
            break

    if advisory_count:
        if tier == TIER_AUTO:
            tier = TIER_REVIEW
        reasons.append("包含路由/模板建议，需人工确认")

    if operator == "table_repair.add" and level == "L1":
        tier = TIER_AUTO

    return {
        "tier": tier,
        "reasons": reasons,
        "requires_confirmation": tier != TIER_AUTO,
    }
