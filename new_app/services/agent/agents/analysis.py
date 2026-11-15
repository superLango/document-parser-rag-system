"""Optional model passes: intent rerank and multi-cause attribution."""

from __future__ import annotations

from typing import Any

INTENT_RERANK_SCHEMA = {
    "type": "object",
    "required": ["table_id", "reason", "confidence"],
    "properties": {
        "table_id": {"type": "string"},
        "reason": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
}

DIAGNOSIS_SCHEMA = {
    "type": "object",
    "required": ["root_cause", "action", "scope", "mechanism", "confidence"],
    "properties": {
        "root_cause": {"type": "string"},
        "action": {"type": "string"},
        "scope": {"type": "string"},
        "expected": {"type": ["string", "null"]},
        "mechanism": {"type": "string"},
        "first_divergence": {"type": "string"},
        "rule_change": {"type": "object"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "evidence": {"type": "array", "items": {"type": "object"}},
    },
}

ROOT_CAUSES = {
    "ocr_error",
    "table_structure",
    "recipe_binding",
    "value_parsing",
    "extraction_rule",
    "dictionary",
    "unknown",
}
ROOT_ALIASES = {
    "ocr": "ocr_error",
    "layout": "ocr_error",
    "header_mapping": "table_structure",
    "schema_dictionary": "dictionary",
    "model_extraction": "value_parsing",
    "source_absent": "unknown",
    "pipeline_code": "unknown",
    "template_schema": "unknown",
    "document_meta": "unknown",
}
ACTIONS = {"reparse", "table_repair", "rule_fix", "code_patch", "document_meta", "report_only"}
SCOPES = {"field", "table", "clause", "document"}
ACTION_BY_ROOT = {
    "ocr_error": "reparse",
    "table_structure": "table_repair",
    "recipe_binding": "rule_fix",
    "value_parsing": "rule_fix",
    "extraction_rule": "rule_fix",
    "dictionary": "rule_fix",
    "unknown": "report_only",
}


def parse_intent_rerank(
    value: Any, inputs: dict[str, Any]
) -> dict[str, Any]:
    """Keep a rerank answer only when it names one of the offered tables."""
    candidate_ids = {
        str(item.get("table_id") or "")
        for item in inputs.get("candidates") or []
        if isinstance(item, dict)
    }
    if not isinstance(value, dict):
        return {"model_used": False, "table_id": "", "reason": "model output unavailable"}
    table_id = str(value.get("table_id") or "")
    if table_id not in candidate_ids:
        return {
            "model_used": False,
            "table_id": "",
            "reason": "模型选择了候选之外的 table_id",
        }
    try:
        confidence = float(value.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    return {
        "model_used": True,
        "table_id": table_id,
        "reason": str(value.get("reason") or ""),
        "confidence": max(0.0, min(confidence, 1.0)),
    }


def parse_diagnosis(value: Any, inputs: dict[str, Any]) -> dict[str, Any]:
    """Validate the attribution answer against the rule diagnosis vocabulary."""
    rule = inputs.get("rule_diagnosis") or {}
    if not isinstance(value, dict):
        return {"model_used": False}
    root_cause = str(value.get("root_cause") or "").strip()
    root_cause = ROOT_ALIASES.get(root_cause, root_cause)
    if root_cause not in ROOT_CAUSES:
        return {"model_used": False}
    action = str(value.get("action") or "").strip()
    if action not in ACTIONS:
        action = ACTION_BY_ROOT.get(root_cause, "report_only")
    scope = str(value.get("scope") or "").strip()
    if scope not in SCOPES:
        scope = str(rule.get("scope") or "document")
        if scope not in SCOPES:
            scope = "document"
    try:
        confidence = float(value.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    expected = value.get("expected")
    rule_change = value.get("rule_change")
    evidence = [
        item
        for item in value.get("evidence") or []
        if isinstance(item, dict) and str(item.get("quote") or "").strip()
    ][:10]
    return {
        "model_used": True,
        "root_cause": root_cause,
        "action": action,
        "scope": scope,
        "expected": str(expected) if isinstance(expected, (str, int, float)) else None,
        "mechanism": str(value.get("mechanism") or ""),
        "first_divergence": str(value.get("first_divergence") or ""),
        "rule_change": rule_change if isinstance(rule_change, dict) else None,
        "confidence": max(0.0, min(confidence, 1.0)),
        "evidence": evidence,
    }
