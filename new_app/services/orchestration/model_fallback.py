"""Model fallback for prose-only items the deterministic layer could not map.

The sandbox never calls a model.  Orchestration may call the agent service after
the sandbox stage when document understanding coverage is low, then merge only
proposals that carry a verbatim quote from the OCR text.  The module here keeps
the trigger/validation/merge logic pure so it can be tested without an agent.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

SCHEMA_VERSION = "document-model-fallback/1"
QUALITATIVE_FEATURES = (
    "晶粒度",
    "低倍",
    "高倍组织",
    "非金属夹杂",
    "超声波检测",
    "铁素体",
    "外观",
    "尺寸",
)
QUALITATIVE_SET = set(QUALITATIVE_FEATURES)
MATRIX_CODES = {"NO_RECORDS", "ROW_KEY_NOT_FOUND", "MEASURE_COLUMN_MISSING"}
MAX_TEXT_CHARS = 20000

OUTPUT_SCHEMA = {
    "type": "object",
    "required": ["items"],
    "properties": {
        "items": {
            "type": "array",
            "maxItems": 5,
            "items": {
                "type": "object",
                "required": ["feature", "requirement", "quote"],
                "properties": {
                    "feature": {"type": "string", "enum": list(QUALITATIVE_FEATURES)},
                    "requirement": {"type": "string"},
                    "quote": {"type": "string"},
                    "method": {"type": "string"},
                    "sampling": {"type": "string"},
                },
            },
        },
        "notes": {"type": "array", "items": {"type": "string"}},
    },
}


def _clean(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    return re.sub(r"\s+", " ", text).strip()


def _compact(value: Any) -> str:
    return re.sub(r"\s+", "", _clean(value))


def should_trigger(
    intelligence: dict[str, Any],
    diagnostics: list[dict[str, Any]],
) -> list[str]:
    """Return the trigger reasons (empty means the fallback is not needed)."""
    stats = (intelligence or {}).get("stats") or {}
    reasons: list[str] = []
    coverage = stats.get("coverage") or {}
    record_features = coverage.get("record_features") or []
    ratio = coverage.get("aligned_ratio")
    if record_features and isinstance(ratio, (int, float)) and ratio < 0.8:
        reasons.append("inventory_coverage_low")
    if int(stats.get("qualitative_items") or 0) > int(
        stats.get("qualitative_records") or 0
    ):
        reasons.append("qualitative_missing")
    hits = sum(
        1
        for item in diagnostics or []
        if isinstance(item, dict) and item.get("code") in MATRIX_CODES
    )
    if hits >= 3:
        reasons.append("matrix_diagnostics_high")
    return reasons


def document_text(ocr: dict[str, Any]) -> str:
    text = str(ocr.get("markdown") or "")
    if not text:
        text = "\n".join(
            str(page.get("markdown") or "") for page in ocr.get("pages") or []
        )
    return _clean(text)[:MAX_TEXT_CHARS]


def existing_features(
    records: list[dict[str, Any]], intelligence: dict[str, Any]
) -> set[str]:
    features: set[str] = set()
    for record in records:
        for measure in (record.get("properties") or {}):
            features.add(str(measure))
    for entry in (intelligence or {}).get("qualitative_items") or []:
        if isinstance(entry, dict) and entry.get("feature"):
            features.add(str(entry["feature"]))
    for entry in ((intelligence or {}).get("stats") or {}).get("coverage", {}).get(
        "inventory_features", []
    ) or []:
        features.add(str(entry))
    return features


def build_task(
    run_id: str,
    trace_id: str,
    text: str,
    intelligence: dict[str, Any],
    records: list[dict[str, Any]],
    *,
    max_items: int = 5,
    token_budget: int = 32000,
) -> dict[str, Any]:
    """Build the AgentTask payload (dict, so contracts stay in one place)."""
    stats = (intelligence or {}).get("stats") or {}
    inventory = [
        {
            "feature": item.get("feature"),
            "item": item.get("item"),
            "status": item.get("status"),
            "requirement": item.get("requirement"),
        }
        for item in (intelligence or {}).get("qualitative_items") or []
        if isinstance(item, dict)
    ]
    return {
        "task_id": f"fallback-{run_id}",
        "trace_id": trace_id or run_id,
        "role": "review",
        "objective": (
            "Find prose-only inspection requirements that are missing from the "
            "structured records. Return only items whose requirement has a "
            "verbatim quote in the supplied document text."
        ),
        "inputs": {
            "document_text": text,
            "existing_features": sorted(existing_features(records, intelligence)),
            "allowed_features": list(QUALITATIVE_FEATURES),
            "known_qualitative_items": inventory,
            "coverage": stats.get("coverage") or {},
        },
        "output_schema": {
            **OUTPUT_SCHEMA,
            "properties": {
                **OUTPUT_SCHEMA["properties"],
                "items": {
                    **OUTPUT_SCHEMA["properties"]["items"],
                    "maxItems": max_items,
                },
            },
        },
        "tools": [],
        "budget": {
            "max_steps": 1,
            "max_tool_calls": 0,
            "max_tokens": token_budget,
            "wall_time_seconds": 120,
        },
        "metadata": {"source": "document_model_fallback"},
    }


def validate_proposals(
    proposals: Any,
    text: str,
    existing: set[str],
    *,
    max_items: int = 5,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Accept only items with an allowed feature and a verbatim quote."""
    accepted: list[dict[str, str]] = []
    rejected: list[dict[str, str]] = []
    if not isinstance(proposals, list):
        return accepted, [{"reason": "items_not_a_list"}]
    needle_text = _compact(text)
    seen = set(existing)
    for raw in proposals:
        if not isinstance(raw, dict):
            rejected.append({"reason": "item_not_an_object"})
            continue
        feature = _clean(raw.get("feature"))
        requirement = _clean(raw.get("requirement"))
        quote = _clean(raw.get("quote"))
        reason = ""
        if feature not in QUALITATIVE_SET:
            reason = "feature_not_allowed"
        elif feature in seen:
            reason = "feature_already_present"
        elif len(requirement) < 4 or len(requirement) > 500:
            reason = "requirement_length"
        elif len(quote) < 8 or len(quote) > 500:
            reason = "quote_length"
        elif _compact(quote) not in needle_text:
            reason = "quote_not_found"
        elif len(accepted) >= max_items:
            reason = "max_items"
        if reason:
            rejected.append(
                {
                    "feature": feature,
                    "reason": reason,
                    "quote": quote[:120],
                }
            )
            continue
        seen.add(feature)
        accepted.append(
            {
                "feature": feature,
                "requirement": requirement,
                "quote": quote,
                "method": _clean(raw.get("method")),
                "sampling": _clean(raw.get("sampling")),
            }
        )
    return accepted, rejected


def merge_proposals(
    records: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    accepted: list[dict[str, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Append accepted proposals as qualitative records plus evidence rows."""
    new_records: list[dict[str, Any]] = []
    new_evidence: list[dict[str, Any]] = []
    for index, item in enumerate(accepted, start=1):
        record_id = f"MF-{index}"
        evidence_id = f"ev-mf-{index}"
        meta: dict[str, str] = {}
        if item.get("method"):
            meta["试验方法"] = item["method"]
        if item.get("sampling"):
            meta["取样说明"] = item["sampling"]
        new_records.append(
            {
                "record_id": record_id,
                "table_id": "model_fallback",
                "page_no": 0,
                "row_index": index - 1,
                "recipe_id": "",
                "recipe_version": "",
                "profile": "qualitative",
                "grade": "",
                "conditions": {},
                "condition_key": "",
                "properties": {
                    item["feature"]: {
                        "raw": item["requirement"],
                        "value": None,
                        "unit": "",
                        "comparator": "text",
                        "column": "模型兜底",
                        "meta": meta,
                        "profile": "qualitative",
                        "source": {"model": True, "quote": item["quote"]},
                    }
                },
                "evidence_refs": [evidence_id],
                "source": {"table_id": "model_fallback", "model": True},
            }
        )
        new_evidence.append(
            {
                "evidence_id": evidence_id,
                "table_id": "model_fallback",
                "page_no": 0,
                "row_index": index - 1,
                "raw_row": [],
                "cells": {},
                "quote": item["quote"][:400],
                "source": "model_fallback",
            }
        )
    return (
        [*records, *new_records],
        [*evidence, *new_evidence],
        new_records,
    )
