"""Project records + clauses + inventory into the final document view.

This layer replaces the scattered document-metadata backfill with one explicit
projection step:

* numerical rows keep their existing 13-field schema;
* prose-only requirements (晶粒度, 低倍, ...) become ``profile="qualitative"``
  records whose raw text and evidence are preserved;
* ``document_intelligence.json`` reports coverage so review/eval can see what
  the document asked for, not only what the tables contained.

Standard library only.
"""

from __future__ import annotations

import re
from typing import Any

try:  # imported as a package (tests)
    from . import builtin as builtin_module
    from . import clauses as clauses_module
    from . import dictionary as dictionary_module
    from . import inventory as inventory_module
    from . import references as references_module
except ImportError:  # flat runtime image (/engine)
    import builtin as builtin_module  # type: ignore[no-redef]
    import clauses as clauses_module  # type: ignore[no-redef]
    import dictionary as dictionary_module  # type: ignore[no-redef]
    import inventory as inventory_module  # type: ignore[no-redef]
    import references as references_module  # type: ignore[no-redef]

SCHEMA_VERSION = "document-intelligence/1"
PROSE_TABLE_ID = "prose"
REQUIREMENT_MIN_LEN = 4


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", builtin_module._normalize_doc_text(value)).strip()


def _existing_features(records: list[dict[str, Any]]) -> set[str]:
    features: set[str] = set()
    for record in records:
        for measure in record.get("properties") or {}:
            feature = builtin_module._feature_for_measure(record, str(measure))
            if feature:
                features.add(feature)
            if str(measure) in inventory_module.QUALITATIVE_SET:
                features.add(str(measure))
    return features


def _record_id(feature: str, clause_id: str, index: int) -> str:
    token = clause_id or feature or f"item{index}"
    token = re.sub(r"[^0-9A-Za-z.\-]+", "-", token).strip("-")
    return f"CL-{token or index}"


def _meta(entry: dict[str, Any]) -> dict[str, str]:
    meta: dict[str, str] = {}
    method = _clean(entry.get("method"))
    if method:
        meta["试验方法"] = method
    sampling = entry.get("sampling") or {}
    location = _clean(sampling.get("location"))
    if location:
        meta["位置"] = location
    quantity = _clean(sampling.get("quantity"))
    if quantity:
        meta["取样数量"] = quantity
    note = _clean(sampling.get("note"))
    if note:
        meta["取样说明"] = note
    return meta


def _apply_method_bindings(
    records: list[dict[str, Any]], bindings: dict[str, dict[str, Any]]
) -> int:
    """Fill empty 试验方法 cells from the reference graph (never overwrite)."""
    if not bindings:
        return 0
    filled = 0
    for record in records:
        if str(record.get("profile") or "") in {"heat_treatment", "qualitative"}:
            continue
        conditions = record.setdefault("conditions", {})
        for measure, prop in (record.get("properties") or {}).items():
            if not isinstance(prop, dict):
                continue
            feature = builtin_module._feature_for_measure(record, str(measure))
            binding = bindings.get(feature)
            if not binding:
                continue
            meta = prop.get("meta") if isinstance(prop.get("meta"), dict) else {}
            if str(meta.get("试验方法") or "").strip():
                continue
            meta["试验方法"] = binding["method"]
            prop["meta"] = meta
            conditions.setdefault("试验方法", binding["method"])
            filled += 1
    return filled


def _fill_inventory_methods(
    inventory_payload: dict[str, Any], bindings: dict[str, dict[str, Any]]
) -> int:
    if not bindings:
        return 0
    filled = 0
    for entry in inventory_payload.get("items") or []:
        if str(entry.get("method") or "").strip():
            continue
        binding = bindings.get(str(entry.get("feature") or ""))
        if not binding:
            continue
        entry["method"] = binding["method"]
        entry["method_source"] = binding.get("source") or "reference"
        filled += 1
    return filled


HIT_STATUSES = {"exact", "alias", "category"}


def _align_dictionary(
    records: list[dict[str, Any]], inventory_payload: dict[str, Any]
) -> dict[str, Any]:
    """Attach business item/category names without changing the schema."""
    checked = matched = ambiguous = 0
    method_checked = method_matched = 0
    for record in records:
        if str(record.get("profile") or "") in {"heat_treatment", "qualitative"}:
            continue
        for measure, prop in (record.get("properties") or {}).items():
            if not isinstance(prop, dict):
                continue
            feature = builtin_module._feature_for_measure(record, str(measure))
            aligned = dictionary_module.align_item(measure, feature)
            checked += 1
            if aligned["status"] in HIT_STATUSES:
                matched += 1
            elif aligned["status"] == "ambiguous":
                ambiguous += 1
            if aligned.get("item"):
                prop["business_item"] = aligned["item"]
            if aligned.get("category"):
                prop["business_category"] = aligned["category"]
            meta = prop.get("meta") if isinstance(prop.get("meta"), dict) else {}
            method = str(meta.get("试验方法") or "").strip()
            if method:
                method_checked += 1
                method_aligned = dictionary_module.align_method(method)
                if method_aligned is not None:
                    method_matched += 1
                    meta["方法名称"] = method_aligned["name"]
                    prop["meta"] = meta
    for entry in inventory_payload.get("items") or []:
        aligned = dictionary_module.align_item(
            entry.get("item") or entry.get("feature"), entry.get("feature")
        )
        checked += 1
        if aligned["status"] in HIT_STATUSES:
            matched += 1
        elif aligned["status"] == "ambiguous":
            ambiguous += 1
        entry["business_item"] = aligned.get("item") or ""
        entry["business_category"] = aligned.get("category") or ""
        entry["dictionary_status"] = aligned["status"]
        method = str(entry.get("method") or "").strip()
        if method:
            method_checked += 1
            method_aligned = dictionary_module.align_method(method)
            if method_aligned is not None:
                method_matched += 1
                entry["method_name"] = method_aligned["name"]
    return {
        "version": dictionary_module.version(),
        "items_checked": checked,
        "items_matched": matched,
        "items_ambiguous": ambiguous,
        "hit_rate": round(matched / checked, 4) if checked else 0.0,
        "methods_checked": method_checked,
        "methods_matched": method_matched,
        "method_hit_rate": round(method_matched / method_checked, 4)
        if method_checked
        else 0.0,
    }


def _qualitative_records(
    records: list[dict[str, Any]],
    inventory_payload: dict[str, Any],
    evidence: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build one qualitative record per prose-only inspection item."""
    existing = _existing_features(records)
    known_evidence = {
        str(item.get("evidence_id") or "") for item in evidence if isinstance(item, dict)
    }
    created: list[dict[str, Any]] = []
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    used_ids: set[str] = set()
    for index, entry in enumerate(inventory_payload.get("items") or [], start=1):
        feature = str(entry.get("feature") or "")
        if feature not in inventory_module.QUALITATIVE_SET or feature in seen:
            continue
        if feature in existing:
            continue
        requirement = _clean(entry.get("requirement"))
        if len(requirement) < REQUIREMENT_MIN_LEN:
            continue
        clause_id = str(entry.get("clause_id") or "")
        page_no = int(entry.get("page_no") or 0)
        record_id = _record_id(feature, clause_id, index)
        if record_id in used_ids:
            suffix = 2
            while f"{record_id}-{suffix}" in used_ids:
                suffix += 1
            record_id = f"{record_id}-{suffix}"
        used_ids.add(record_id)
        evidence_id = next(
            (
                str(item)
                for item in entry.get("evidence") or []
                if str(item)
            ),
            f"ev-qualitative-{feature}",
        )
        if evidence_id not in known_evidence:
            known_evidence.add(evidence_id)
            evidence.append(
                {
                    "evidence_id": evidence_id,
                    "table_id": "",
                    "page_no": page_no,
                    "row_index": 0,
                    "raw_row": [],
                    "cells": {},
                    "quote": requirement[:400],
                    "source": "clause" if clause_id else "inventory",
                }
            )
        meta = _meta(entry)
        record = {
            "record_id": record_id,
            "table_id": PROSE_TABLE_ID,
            "page_no": page_no,
            "row_index": 0,
            "recipe_id": "",
            "recipe_version": "",
            "profile": "qualitative",
            "grade": "",
            "conditions": {},
            "condition_key": "",
            "properties": {
                feature: {
                    "raw": requirement,
                    "value": None,
                    "unit": "",
                    "comparator": "text",
                    "column": "正文",
                    "meta": meta,
                    "profile": "qualitative",
                    "source": {
                        "clause_id": clause_id,
                        "page_no": page_no,
                        "inventory_id": entry.get("inventory_id") or "",
                    },
                    **(
                        {"business_item": entry["business_item"]}
                        if entry.get("business_item")
                        else {}
                    ),
                    **(
                        {"business_category": entry["business_category"]}
                        if entry.get("business_category")
                        else {}
                    ),
                }
            },
            "evidence_refs": [evidence_id],
            "source": {
                "clause_id": clause_id,
                "page_no": page_no,
                "table_id": PROSE_TABLE_ID,
            },
        }
        created.append(record)
        seen.add(feature)
        items.append(
            {
                "feature": feature,
                "requirement": requirement,
                "clause_id": clause_id,
                "clause_ids": list(entry.get("clause_ids") or []),
                "page_no": page_no,
                "method": _clean(entry.get("method")),
                "sampling": dict(entry.get("sampling") or {}),
                "inventory_id": entry.get("inventory_id") or "",
                "business_item": entry.get("business_item") or "",
                "business_category": entry.get("business_category") or "",
                "evidence": list(entry.get("evidence") or []),
            }
        )
    return created, items


def apply_document_intelligence(
    records: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    ocr: dict[str, Any],
    diagnostics: list[dict[str, Any]],
) -> dict[str, Any]:
    """Run the document-understanding layer and return the new artifacts."""
    applied = builtin_module.apply_document_metadata(records, ocr, diagnostics)
    clauses_payload = clauses_module.extract_clauses(ocr)
    inspections = builtin_module._inspection_items(ocr)
    references_payload = references_module.extract_references(
        ocr, clauses_payload, inspections
    )
    bindings = references_payload.get("bindings") or {}
    methods_filled = _apply_method_bindings(records, bindings)
    inventory_payload = inventory_module.build_inventory(
        records, clauses_payload, inspections, ocr
    )
    methods_filled += _fill_inventory_methods(inventory_payload, bindings)
    dictionary_stats = _align_dictionary(records, inventory_payload)
    classifications = inventory_module.extract_classifications(ocr)
    qualitative, qualitative_items = _qualitative_records(
        records, inventory_payload, evidence
    )
    records.extend(qualitative)

    classification_counts: dict[str, int] = {}
    for item in classifications:
        kind = str(item.get("kind") or "other")
        classification_counts[kind] = classification_counts.get(kind, 0) + 1
    intelligence = {
        "schema_version": SCHEMA_VERSION,
        "stats": {
            "metadata_applied": applied,
            "clauses": clauses_payload["stats"]["clauses"],
            "clause_kinds": clauses_payload["stats"]["kinds"],
            "clause_fields": clauses_payload["stats"]["fields"],
            "inventory_items": len(inventory_payload["items"]),
            "inspection_items": len(inspections),
            "qualitative_items": len(qualitative_items),
            "qualitative_records": len(qualitative),
            "coverage": inventory_payload["coverage"],
            "references": references_payload["stats"],
            "method_bindings": len(bindings),
            "methods_filled": methods_filled,
            "classifications": len(classifications),
            "classification_kinds": classification_counts,
            "dictionary": dictionary_stats,
        },
        "qualitative_items": qualitative_items,
        "classifications": classifications[:500],
    }
    diagnostics.append(
        {
            "code": "DOCUMENT_INTELLIGENCE_APPLIED",
            "message": (
                f"{clauses_payload['stats']['clauses']} clause(s), "
                f"{len(inventory_payload['items'])} inventory item(s), "
                f"{len(qualitative)} qualitative record(s), "
                f"{references_payload['stats']['total']} reference(s)"
            ),
            "severity": "info",
            "detail": {
                "clauses": clauses_payload["stats"]["clauses"],
                "inventory_items": len(inventory_payload["items"]),
                "qualitative_records": len(qualitative),
                "coverage": inventory_payload["coverage"],
                "references": references_payload["stats"],
                "method_bindings": len(bindings),
                "methods_filled": methods_filled,
                "classifications": len(classifications),
            },
        }
    )
    return {
        "clauses": clauses_payload,
        "inventory": inventory_payload,
        "references": references_payload,
        "intelligence": intelligence,
    }
