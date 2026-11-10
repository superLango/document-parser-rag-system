"""Task context assembly and compaction (M3.3-01/02).

Rules: evidence, headers, units and conditions are never compressed; only
clause prose and previous-error prose may be replaced by ids/summaries. The
assembled context is capped at 24K approximate tokens (CJK ≈ 3 chars/token).
"""

from __future__ import annotations

import math
from typing import Any

from ..contracts import TableGrid
from ..tablegrid.normalize import canonical_element, canonical_property

DEFAULT_MAX_TOKENS = 24000
MAX_SAMPLE_ROWS = 5


def estimate_tokens(text: str) -> int:
    return int(math.ceil(len(text or "") / 3))


def _table_slice(table: TableGrid | None) -> dict[str, Any]:
    if table is None:
        return {}
    return {
        "table_id": table.table_id,
        "page_no": table.page_no,
        "caption": table.caption,
        "profile": table.profile,
        "orientation": table.orientation,
        "n_rows": table.n_rows,
        "n_cols": table.n_cols,
        "header_paths": [list(path) for path in table.header_paths],
        "units": list(table.units),
        "sample_rows": [list(row) for row in table.rows[:MAX_SAMPLE_ROWS]],
    }


def assemble_context(
    profile: dict[str, Any] | None = None,
    *,
    table: TableGrid | None = None,
    clauses: list[dict[str, Any]] | None = None,
    reference_constraints: list[dict[str, Any]] | None = None,
    schema_fields: list[str] | None = None,
    previous_errors: list[dict[str, Any]] | None = None,
    evidence_ids: list[str] | None = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> dict[str, Any]:
    context: dict[str, Any] = {
        "document_profile": dict(profile or {}),
        "table": _table_slice(table),
        "schema_fields": list(schema_fields or []),
        "previous_errors": [
            {"code": item.get("code"), "stage": item.get("stage")}
            for item in (previous_errors or [])
        ],
        "evidence_ids": list(evidence_ids or []),
        "clauses": [],
        "reference_constraints": list(reference_constraints or []),
        "compacted": False,
    }
    budget = max_tokens - _fixed_tokens(context)
    for clause in clauses or []:
        candidate = {
            "clause_id": clause.get("clause_id"),
            "title": clause.get("title"),
            "text": clause.get("text") or "",
        }
        cost = estimate_tokens(str(candidate["text"])) + estimate_tokens(
            str(candidate["title"])
        )
        if cost > budget:
            break
        context["clauses"].append(candidate)
        budget -= cost
    context["tokens"] = _fixed_tokens(context) + sum(
        estimate_tokens(str(item["text"])) + estimate_tokens(str(item["title"]))
        for item in context["clauses"]
    )
    context["max_tokens"] = max_tokens
    return context


def compact_context(context: dict[str, Any]) -> dict[str, Any]:
    """Drop clause prose only; keep clause ids, evidence ids, headers and units."""
    compacted = {
        "document_profile": context.get("document_profile") or {},
        "table": context.get("table") or {},
        "schema_fields": list(context.get("schema_fields") or []),
        "previous_errors": list(context.get("previous_errors") or [])[:20],
        "evidence_ids": list(context.get("evidence_ids") or []),
        "clauses": [
            {
                "clause_id": item.get("clause_id"),
                "title": item.get("title"),
                "text": "",
                "text_dropped": True,
            }
            for item in context.get("clauses") or []
        ],
        "reference_constraints": list(context.get("reference_constraints") or []),
        "compacted": True,
        "max_tokens": context.get("max_tokens", DEFAULT_MAX_TOKENS),
    }
    compacted["tokens"] = _fixed_tokens(compacted)
    return compacted


def context_regression(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Invariants that must survive compaction (evidence/headers are lossless)."""
    before_ids = set(before.get("evidence_ids") or [])
    after_ids = set(after.get("evidence_ids") or [])
    before_headers = (before.get("table") or {}).get("header_paths") or []
    after_headers = (after.get("table") or {}).get("header_paths") or []
    before_units = (before.get("table") or {}).get("units") or []
    after_units = (after.get("table") or {}).get("units") or []
    before_clauses = {item.get("clause_id") for item in before.get("clauses") or []}
    after_clauses = {item.get("clause_id") for item in after.get("clauses") or []}
    before_fields = _extractable_fields(before.get("table") or {})
    after_fields = _extractable_fields(after.get("table") or {})
    return {
        "lost_evidence": sorted(before_ids - after_ids),
        "headers_preserved": before_headers == after_headers,
        "units_preserved": before_units == after_units,
        "clause_ids_preserved": before_clauses == after_clauses,
        "fields_before": sorted(before_fields),
        "fields_after": sorted(after_fields),
        "lost_fields": sorted(before_fields - after_fields),
        "field_loss_rate": round(
            len(before_fields - after_fields) / len(before_fields), 4
        )
        if before_fields
        else 0.0,
        "lossless": not (before_ids - after_ids)
        and before_headers == after_headers
        and before_units == after_units
        and before_clauses == after_clauses
        and not (before_fields - after_fields),
        "token_reduction": round(
            1 - (after.get("tokens", 0) / before.get("tokens", 1)), 4
        )
        if before.get("tokens")
        else 0.0,
    }


def _extractable_fields(table_slice: dict[str, Any]) -> set[str]:
    """Property keys the extractor can bind from the context table slice."""
    fields: set[str] = set()
    for path in table_slice.get("header_paths") or []:
        text = " ".join(str(cell) for cell in path)
        prop = canonical_property(text) or canonical_element(text)
        if prop:
            fields.add(prop)
    return fields


def _fixed_tokens(context: dict[str, Any]) -> int:
    import json

    payload = {
        "document_profile": context.get("document_profile"),
        "table": context.get("table"),
        "schema_fields": context.get("schema_fields"),
        "previous_errors": context.get("previous_errors"),
        "evidence_ids": context.get("evidence_ids"),
        "reference_constraints": context.get("reference_constraints"),
    }
    return estimate_tokens(json.dumps(payload, ensure_ascii=False))
