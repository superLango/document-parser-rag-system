"""Repair gates: evidence, reproduction, target metric, errors, limits, regression."""

from __future__ import annotations

from typing import Any

MAX_ITERATIONS = 3


def evaluate_gates(
    *,
    target_fixed: bool,
    new_errors: int,
    removed: bool,
    evidence_grounded: bool,
    reproduced: bool,
    required_no_loss: bool = True,
    iterations: int = 1,
    acceptance: dict[str, Any] | None = None,
    regression: tuple[bool, str] | None = None,
    level: str = "L2",
    l3_policy_passed: bool | None = None,
    max_iterations: int = MAX_ITERATIONS,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def add(name: str, passed: bool, detail: str) -> None:
        checks.append({"name": name, "passed": passed, "detail": detail})

    add(
        "evidence_grounded",
        evidence_grounded,
        "证据可落到原文/单元格" if evidence_grounded else "缺少证据",
    )
    add("reproduction", reproduced, "问题已复现" if reproduced else "问题未能复现")
    metric = str((acceptance or {}).get("metric") or "")
    add(
        "target_metric",
        target_fixed,
        f"{metric or '目标指标'} 已改善" if target_fixed else f"{metric or '目标指标'} 未改善",
    )
    add("no_new_errors", new_errors == 0, f"new_errors={new_errors}")
    add(
        "required_no_loss",
        required_no_loss,
        "必填字段未丢失" if required_no_loss else "丢失了已有必填字段",
    )
    add("no_removed_records", not removed, "未删除既有记录" if not removed else "删除了既有记录")
    add(
        "iteration_limit",
        iterations <= max_iterations,
        f"{iterations}/{max_iterations}",
    )
    if regression is None:
        add("regression", True, "未配置回归集，跳过")
    else:
        passed, detail = regression
        add("regression", passed, detail)
    if level == "L3":
        add(
            "diff_policy",
            bool(l3_policy_passed),
            "L3 补丁策略通过" if l3_policy_passed else "L3 补丁策略未通过",
        )

    failing = [
        check
        for check in checks
        if not check["passed"] and check["name"] != "diff_policy"
    ]
    if failing:
        decision = "rollback"
    elif level == "L3" and not l3_policy_passed:
        decision = "propose_only"
    else:
        decision = "accept"
    return {"checks": checks, "decision": decision, "passed": decision == "accept"}
