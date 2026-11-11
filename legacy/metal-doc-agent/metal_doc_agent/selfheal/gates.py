"""Automatic gates for repair proposals (evidence, target, regression, limits)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .config import SelfHealSettings
from .contracts import (
    Finding,
    FindingSource,
    GateCheck,
    GateDecision,
    GateResult,
    RepairLevel,
    RepairProposal,
)

DETERMINISTIC_RULES = {
    "evidence_missing",
    "evidence_quote_mismatch",
    "unit_missing",
    "duplicate_record",
}


@dataclass
class GateContext:
    finding: Finding
    proposal: RepairProposal
    diff: dict[str, Any]
    iterations: int = 0
    regression_check: Callable[[], tuple[bool, str]] | None = None


def evaluate(
    context: GateContext, settings: SelfHealSettings
) -> GateResult:
    diff = context.diff or {}
    checks: list[GateCheck] = []

    grounded = bool(context.finding.evidence) or (
        context.finding.source == FindingSource.audit
        and context.finding.rule_code in DETERMINISTIC_RULES
    )
    checks.append(
        GateCheck(
            name="evidence_grounded",
            passed=grounded,
            detail=f"{len(context.finding.evidence)} evidence ref(s)",
        )
    )

    reproduced = bool(diff.get("reproduced", True))
    checks.append(
        GateCheck(
            name="reproduction",
            passed=reproduced,
            detail="目标在修复前可定位" if reproduced else "目标未能复现",
        )
    )

    target_ok = bool(diff.get("target_resolved", False))
    checks.append(
        GateCheck(
            name="target_metric",
            passed=target_ok,
            detail="目标字段已符合预期" if target_ok else "目标字段未改善",
        )
    )

    new_errors = int(diff.get("new_errors", 0) or 0)
    checks.append(
        GateCheck(
            name="no_new_errors",
            passed=new_errors == 0,
            detail=f"new_errors={new_errors}",
        )
    )

    limit_ok = context.iterations <= settings.max_iterations
    checks.append(
        GateCheck(
            name="iteration_limit",
            passed=limit_ok,
            detail=f"{context.iterations}/{settings.max_iterations}",
        )
    )

    if context.regression_check is not None:
        passed, detail = context.regression_check()
    else:
        passed, detail = True, "未配置回归集，跳过"
    checks.append(GateCheck(name="regression", passed=passed, detail=detail))

    if context.proposal.level == RepairLevel.L3:
        l3_checks = context.proposal.params.get("l3_checks") or {}
        checks.append(
            GateCheck(
                name="diff_policy",
                passed=bool(l3_checks.get("passed", False)),
                detail=str(l3_checks.get("detail", "L3 策略未通过")),
            )
        )

    all_passed = all(check.passed for check in checks)
    if not all_passed:
        decision = GateDecision.rollback
    elif context.proposal.level == RepairLevel.L3 and not settings.auto_merge:
        decision = GateDecision.propose_only
    else:
        decision = GateDecision.accept
    return GateResult(proposal_id=context.proposal.proposal_id, checks=checks, decision=decision)
