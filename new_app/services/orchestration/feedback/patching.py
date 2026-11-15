"""Patch space alignment: only verifiable roots/operators may enter a candidate."""

from __future__ import annotations

import re
from typing import Any

# 只有这两类路径会真正进入沙箱重跑，因此只有它们算“有效补丁”。
ALLOWED_ROOTS = ("/bindings", "/rules")
# 这些字段影响路由/模板，不参与候选验证，只能作为建议。
ADVISORY_ROOTS = ("/signature", "/templates", "/compatibility")

OPERATORS: dict[str, tuple[str, ...]] = {
    "recipe.binding_override": ("recipe_id", "bindings"),
    "column_alias.add": ("alias", "property"),
    "table_repair.add": ("table_id", "spec"),
    "unit_normalize.add": ("pattern", "unit"),
    "condition_binding.add": ("conditions",),
    "row_key.add": ("tokens",),
}
EFFECTIVE_OPERATORS = {"recipe.binding_override", "column_alias.add", "table_repair.add"}
ADVISORY_OPERATORS = set(OPERATORS) - EFFECTIVE_OPERATORS
ALLOWED_OPS = {"add", "replace", "remove"}
MEASURE_PATH_RE = re.compile(r"^/bindings/measures/([^/]+)$")
# `add` to these list roots means append; JSON Patch requires the `/-` suffix.
APPEND_LIST_PATHS = {
    "/bindings/conditions",
    "/bindings/row_key",
    "/rules/strategy_chain",
}


def _root(path: str) -> str:
    return "/" + path.lstrip("/").split("/", 1)[0]


def _under(path: str, roots: tuple[str, ...]) -> bool:
    return any(path == root or path.startswith(root + "/") for root in roots)


def validate_operator(operator: str, params: dict[str, Any]) -> list[str]:
    if operator not in OPERATORS:
        return [f"未注册的算子：{operator}"]
    return [
        f"缺少参数 {name}"
        for name in OPERATORS[operator]
        if params.get(name) in (None, "", {}, [])
    ]


def sanitize_patch(
    patch: dict[str, Any] | None,
    *,
    allowed_operators: list[str] | None = None,
    admissible: dict[str, Any] | None = None,
    max_ops: int | None = None,
    allow_measure_removal: bool = False,
) -> dict[str, Any]:
    """Split a proposal patch into effective / advisory / rejected ops.

    Effective ops are the only ones allowed into a candidate; advisory ops are
    recorded as routing suggestions but never verified; rejected ops violate
    the patch-space policy and are dropped with a reason.

    ``admissible`` enforces hard admissibility: a newly added measure binding
    must appear in ``admissible.measures``/``admissible.columns``.  ``max_ops``
    caps how many effective ops enter verification.
    """
    patch = patch or {}
    ops = patch.get("ops")
    effective: list[dict[str, Any]] = []
    advisory: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    problems: list[str] = []

    if "operator" in patch:
        operator = str(patch.get("operator") or "")
        params = patch.get("params") or {}
        issues = validate_operator(operator, params)
        if issues:
            problems.extend(issues)
            return {
                "effective_ops": [],
                "advisory_ops": [],
                "rejected_ops": [],
                "problems": problems,
                "effective": False,
            }
        if operator not in EFFECTIVE_OPERATORS:
            return {
                "effective_ops": [],
                "advisory_ops": [patch],
                "rejected_ops": [],
                "problems": [f"算子 {operator} 只产生建议，不进入验证"],
                "effective": False,
            }
        if allowed_operators and operator not in allowed_operators:
            return {
                "effective_ops": [],
                "advisory_ops": [],
                "rejected_ops": [patch],
                "problems": [f"算子 {operator} 不在本任务允许列表中"],
                "effective": False,
            }
        problems.append(f"算子 {operator} 尚未实现到 JSON Patch 的转换")
        return {
            "effective_ops": [],
            "advisory_ops": [],
            "rejected_ops": [patch],
            "problems": problems,
            "effective": False,
        }

    if not isinstance(ops, list):
        return {
            "effective_ops": [],
            "advisory_ops": [],
            "rejected_ops": [],
            "problems": ["patch.ops 缺失或不是数组"],
            "effective": False,
        }

    for op in ops:
        if not isinstance(op, dict):
            rejected.append({"op": None, "reason": "op 不是对象"})
            continue
        path = str(op.get("path") or "")
        action = str(op.get("op") or "")
        if action == "add" and path in APPEND_LIST_PATHS:
            path = f"{path}/-"
            op = {**op, "path": path}
        if not path.startswith("/"):
            rejected.append({**op, "reason": "path 必须是 JSON Pointer"})
            continue
        root = _root(path)
        if _under(path, ADVISORY_ROOTS):
            advisory.append(op)
            continue
        if not _under(path, ALLOWED_ROOTS):
            rejected.append({**op, "reason": f"不允许的路径根 {root}"})
            continue
        if action not in ALLOWED_OPS:
            rejected.append({**op, "reason": f"不支持的 op {action}"})
            continue
        if (
            not allow_measure_removal
            and action in {"remove", "replace"}
            and (path in {"/bindings", "/bindings/measures"} or MEASURE_PATH_RE.match(path))
        ):
            # 单文档反馈不能做“减法”：删除 measure 绑定会影响其他文档。
            rejected.append(
                {**op, "reason": "默认禁止删除或替换 measure 绑定；减法补丁需人工批准"}
            )
            continue
        if action in {"add", "replace"} and "value" not in op:
            rejected.append({**op, "reason": "add/replace 缺少 value"})
            continue
        if action == "add" and admissible is not None:
            match = MEASURE_PATH_RE.match(path)
            if match:
                measure = match.group(1).replace("~1", "/").replace("~0", "~")
                allowed = {
                    str(item)
                    for item in list(admissible.get("measures") or [])
                    + list(admissible.get("columns") or [])
                }
                if measure not in allowed:
                    rejected.append(
                        {**op, "reason": f"measure {measure} 不在可采纳集合内"}
                    )
                    continue
        effective.append(op)

    if max_ops is not None and max_ops > 0 and len(effective) > max_ops:
        rejected.extend(
            {**op, "reason": f"超过 max_ops={max_ops}"} for op in effective[max_ops:]
        )
        effective = effective[:max_ops]

    return {
        "effective_ops": effective,
        "advisory_ops": advisory,
        "rejected_ops": rejected,
        "problems": problems,
        "effective": bool(effective),
    }
