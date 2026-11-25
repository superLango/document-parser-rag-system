"""未解决队列：错误/低置信记录进入队列，不静默入库。"""
from __future__ import annotations

from typing import Any


def build_queue(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    queue: list[dict[str, Any]] = []
    for record in records:
        verification = record.get("verification") or {}
        if not verification:
            continue
        diagnostics = verification.get("diagnostics") or []
        if verification.get("status") not in {"warn", "unresolved"} and not diagnostics:
            continue
        reasons = [diagnostic for diagnostic in diagnostics if diagnostic.get("severity") in {"warn", "error"}]
        if not reasons and verification.get("status") != "unresolved":
            continue
        queue.append({
            "record_id": record.get("record_id"),
            "category": record.get("category"),
            "item": record.get("item"),
            "grade": record.get("grade"),
            "requirement": record.get("requirement"),
            "status": verification.get("status"),
            "reasons": reasons,
            "evidence": record.get("evidence"),
            "suggestion": _suggestion(reasons),
        })
    return queue


def _suggestion(reasons: list[dict[str, Any]]) -> str:
    codes = {reason.get("code") for reason in reasons}
    if "value_not_in_source" in codes:
        return "核对绑定列/行，重新抽取或人工确认取值"
    if "missing_temperature" in codes or "temperature_category_conflict" in codes:
        return "补全/纠正试验温度条件"
    if "stale_table_reference" in codes or "row_out_of_range" in codes:
        return "检查 OCR 表编号/行号引用是否失效"
    if "grade_rejected" in codes:
        return "从牌号列或文档级牌号修复"
    if "value_conflict" in codes:
        return "确认同一键的不同要求值是否为表格不同条件/版本"
    return "人工复核"
