"""Repairability gate: decide whether automatic repair is even possible."""

from __future__ import annotations

from typing import Any

ENGINE_ROOT_CAUSES = {"ocr_error"}
DATA_ROOT_CAUSES = {"table_structure", "value_parsing"}
RECIPE_ROOT_CAUSES = {"recipe_binding", "extraction_rule", "dictionary"}
# 文档级字段：试验方法/取样来自检验表、条款与引用图，不是单元格取值问题。
DOCUMENT_FIELDS = {"试验方法", "取样", "取样数量", "取样位置", "取样说明"}


def evaluate_repairability(context: dict[str, Any]) -> dict[str, Any]:
    """Map diagnosis + task constraints to engine/data/recipe_binding/human."""
    diagnosis = context.get("diagnosis") or {}
    intent = context.get("intent") or {}
    field = str(intent.get("field") or "")
    repair_context = context.get("repair_context") or {}
    root_cause = str(diagnosis.get("root_cause") or "unknown")
    action = str(diagnosis.get("action") or "")
    constraints = repair_context.get("constraints") or {}
    allowed_levels = list(constraints.get("allowed_levels") or [])
    allowed_operators = list(constraints.get("allowed_operators") or [])
    admissible = list(
        ((constraints.get("admissible") or {}).get("columns")) or []
    )

    if "engine" in allowed_levels or root_cause in ENGINE_ROOT_CAUSES:
        return {
            "decision": "engine",
            "reason": "OCR/版面层问题，配方补丁无法修复",
            "allowed_levels": ["engine"],
            "allowed_operators": [],
        }

    if field in DOCUMENT_FIELDS:
        return {
            "decision": "document_rule",
            "reason": "试验方法/取样属于文档级字段，需要条款与引用图规则修复",
            "allowed_levels": ["engine"],
            "allowed_operators": [],
        }

    if root_cause in RECIPE_ROOT_CAUSES:
        if root_cause == "recipe_binding" and not admissible and not allowed_operators:
            return {
                "decision": "needs_more_info",
                "reason": "没有可采纳的列或算子，需要人工确认绑定关系",
                "allowed_levels": allowed_levels,
                "allowed_operators": [],
            }
        return {
            "decision": "recipe_binding",
            "reason": "列或规则可修正，允许生成配方补丁",
            "allowed_levels": allowed_levels or ["L2"],
            "allowed_operators": allowed_operators,
        }

    if root_cause in DATA_ROOT_CAUSES or action == "table_repair":
        if not diagnosis.get("expected") and root_cause == "value_parsing":
            return {
                "decision": "needs_more_info",
                "reason": "未定位到记录与原文的差异，无法确定修复目标",
                "allowed_levels": allowed_levels,
                "allowed_operators": [],
            }
        return {
            "decision": "data",
            "reason": "表结构/取值问题需要 L1 表级修复（沙箱重解析）",
            "allowed_levels": ["L1"],
            "allowed_operators": ["table_repair.add"],
        }

    return {
        "decision": "needs_more_info",
        "reason": "规则无法归因，需要人工或模型进一步判断",
        "allowed_levels": allowed_levels,
        "allowed_operators": [],
    }
