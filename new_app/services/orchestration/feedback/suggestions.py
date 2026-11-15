"""Structured human suggestions for needs_more_info / needs_human outcomes."""

from __future__ import annotations

from typing import Any

MAX_SUGGESTIONS = 5
MAX_COLUMNS = 8


def _target(repair_context: dict[str, Any], intent: dict[str, Any]) -> tuple[str, int]:
    problem = repair_context.get("problem") or {}
    target = problem.get("target") or {}
    table_id = str(target.get("table_id") or "")
    page_no = int(target.get("page_no") or 0)
    if not table_id:
        candidates = intent.get("candidate_targets") or []
        if candidates:
            table_id = str(candidates[0].get("table_id") or "")
            page_no = int(candidates[0].get("page_no") or page_no)
    return table_id, page_no


def _columns(repair_context: dict[str, Any]) -> list[str]:
    recipe = repair_context.get("recipe") or {}
    constraints = repair_context.get("constraints") or {}
    admissible = (
        (constraints.get("admissible") or {}).get("columns")
        or (constraints.get("admissible") or {}).get("measures")
        or []
    )
    values = list(recipe.get("unbound_columns") or []) or list(admissible)
    return [str(item) for item in values if item][:MAX_COLUMNS]


def build_suggestions(
    *,
    intent: dict[str, Any] | None = None,
    diagnosis: dict[str, Any] | None = None,
    repairability: dict[str, Any] | None = None,
    repair_context: dict[str, Any] | None = None,
    proposal: Any = None,
) -> list[dict[str, Any]]:
    """Turn the decision context into a short, actionable human worklist."""
    intent = intent or {}
    diagnosis = diagnosis or {}
    repairability = repairability or {}
    repair_context = repair_context or {}
    table_id, page_no = _target(repair_context, intent)
    decision = str(repairability.get("decision") or "")
    confidence = float(
        diagnosis.get("confidence") or intent.get("confidence") or 0.0
    )
    suggestions: list[dict[str, Any]] = []

    clarification = intent.get("clarification") or {}
    if clarification.get("options"):
        suggestions.append(
            {
                "action": "confirm_table",
                "table_id": table_id,
                "page_no": page_no,
                "columns": [],
                "reason": clarification.get("question") or "需要确认目标表",
                "confidence": confidence,
                "source": "clarification",
                "options": clarification.get("options") or [],
            }
        )

    if decision == "engine":
        suggestions.append(
            {
                "action": "reparse_or_fix_ocr",
                "table_id": table_id,
                "page_no": page_no,
                "columns": [],
                "reason": repairability.get("reason") or "OCR/版面层问题",
                "confidence": confidence,
                "source": "rule",
            }
        )
    elif decision == "document_rule":
        suggestions.append(
            {
                "action": "fix_method_binding",
                "table_id": table_id,
                "page_no": page_no,
                "columns": [],
                "reason": repairability.get("reason")
                or "文档级试验方法/取样绑定缺失",
                "confidence": confidence,
                "source": "rule",
            }
        )
    elif decision == "data":
        suggestions.append(
            {
                "action": "repair_table_structure",
                "table_id": table_id,
                "page_no": page_no,
                "columns": _columns(repair_context),
                "reason": diagnosis.get("mechanism")
                or repairability.get("reason")
                or "表头/行键识别失败",
                "confidence": confidence,
                "source": "rule",
            }
        )
    elif decision == "recipe_binding":
        suggestions.append(
            {
                "action": "bind_measures",
                "table_id": table_id,
                "page_no": page_no,
                "columns": _columns(repair_context),
                "reason": diagnosis.get("mechanism")
                or repairability.get("reason")
                or "列存在但配方未绑定",
                "confidence": confidence,
                "source": "rule",
            }
        )
    elif decision == "needs_more_info":
        suggestions.append(
            {
                "action": "manual_review",
                "table_id": table_id,
                "page_no": page_no,
                "columns": _columns(repair_context),
                "reason": repairability.get("reason")
                or diagnosis.get("mechanism")
                or "规则无法归因",
                "confidence": confidence,
                "source": "rule",
            }
        )

    summary = str(getattr(proposal, "summary", "") or "")
    if getattr(proposal, "needs_human", False) and summary:
        suggestions.append(
            {
                "action": "manual_review",
                "table_id": table_id,
                "page_no": page_no,
                "columns": _columns(repair_context),
                "reason": summary,
                "confidence": float(getattr(proposal, "confidence", 0.0) or 0.0),
                "source": "proposal",
            }
        )

    if not suggestions:
        suggestions.append(
            {
                "action": "manual_triage",
                "table_id": table_id,
                "page_no": page_no,
                "columns": _columns(repair_context),
                "reason": diagnosis.get("mechanism")
                or "未定位到可自动修复的表或字段",
                "confidence": confidence,
                "source": "rule",
            }
        )

    deduped: list[dict[str, Any]] = []
    index: dict[tuple[str, str], int] = {}
    for item in suggestions:
        key = (str(item.get("action") or ""), str(item.get("table_id") or ""))
        if key in index:
            current = deduped[index[key]]
            if (
                current.get("source") == "rule"
                and item.get("source") == "proposal"
            ):
                deduped[index[key]] = item
            continue
        index[key] = len(deduped)
        deduped.append(item)
    return deduped[:MAX_SUGGESTIONS]
