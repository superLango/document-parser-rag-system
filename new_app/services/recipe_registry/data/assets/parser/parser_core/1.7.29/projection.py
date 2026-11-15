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
    from . import translate as translate_module
except ImportError:  # flat runtime image (/engine)
    import builtin as builtin_module  # type: ignore[no-redef]
    import clauses as clauses_module  # type: ignore[no-redef]
    import dictionary as dictionary_module  # type: ignore[no-redef]
    import inventory as inventory_module  # type: ignore[no-redef]
    import references as references_module  # type: ignore[no-redef]
    import translate as translate_module  # type: ignore[no-redef]

SCHEMA_VERSION = "document-intelligence/1"
PROSE_TABLE_ID = "prose"
REQUIREMENT_MIN_LEN = 4


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", builtin_module._normalize_doc_text(value)).strip()


def _sanitize(value: Any) -> Any:
    """Recursively remove table markup that OCR may leak into a field."""
    if isinstance(value, dict):
        return {key: _sanitize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, str):
        return builtin_module._strip_html(value)
    return value


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


def _grade_key(value: str) -> str:
    """Comparable grade text; OCR often drops the leading 0 (0Cr13 → Cr13)."""
    text = re.sub(r"[^0-9A-Za-z]", "", str(value or "")).lower()
    return text.lstrip("0")


def _document_grades(records: list[dict[str, Any]], ocr: dict[str, Any]) -> list[str]:
    grades: list[str] = []
    for record in records:
        grade = str(record.get("grade") or "").strip()
        if not grade or grade in {"~", "全部牌号"}:
            continue
        if len(_grade_key(grade)) < 3:
            continue
        if grade not in grades:
            grades.append(grade)
    if not grades:
        hint = builtin_module._document_grade_hint(str(ocr.get("markdown") or ""))
        if hint:
            grades.append(hint)
    # 表格列错位时会把“45”“11”之类数值当牌号；同文档已有字母牌号时丢弃。
    if any(re.search(r"[A-Za-z]", grade) for grade in grades):
        grades = [grade for grade in grades if re.search(r"[A-Za-z]", grade)]
    return grades


def _grade_for_requirement(text: str, grades: list[str]) -> str:
    if not grades:
        return ""
    key_text = _grade_key(text)
    matched = [
        grade
        for grade in grades
        if len(_grade_key(grade)) >= 4 and _grade_key(grade) in key_text
    ]
    if matched:
        return "、".join(dict.fromkeys(matched))
    if len(grades) == 1:
        return grades[0]
    return "全部牌号"


def _inherit_grades(records: list[dict[str, Any]], ocr: dict[str, Any]) -> int:
    """Fill document-level grades for prose records and heat schedules."""
    grades = _document_grades(records, ocr)
    if not grades:
        return 0
    filled = 0
    for record in records:
        if str(record.get("grade") or "").strip():
            continue
        profile = str(record.get("profile") or "")
        if profile == "qualitative":
            text = " ".join(
                str(prop.get("raw") or "")
                for prop in (record.get("properties") or {}).values()
                if isinstance(prop, dict)
            )
            grade = _grade_for_requirement(text, grades)
        elif profile == "heat_treatment":
            grade = grades[0] if len(grades) == 1 else "全部牌号"
        else:
            continue
        if grade:
            record["grade"] = grade
            filled += 1
    return filled


def _meta(entry: dict[str, Any]) -> dict[str, str]:
    meta: dict[str, str] = {}
    method = _clean(entry.get("method"))
    if method:
        meta["试验方法"] = method
        original = _clean(entry.get("method_raw"))
        if original and original != method:
            meta["试验方法原文"] = original
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


def _normalize_condition_method(conditions: dict[str, Any]) -> bool:
    method = str(conditions.get("试验方法") or "").strip()
    if not method:
        return False
    normalized = dictionary_module.normalize_method(method)
    if not normalized.get("text") or normalized["text"] == method:
        return False
    conditions["试验方法原文"] = method
    conditions["试验方法"] = normalized["text"]
    return True


def _align_dictionary(
    records: list[dict[str, Any]], inventory_payload: dict[str, Any]
) -> dict[str, Any]:
    """Align features/items/methods with the business dictionary.

    * ``feature`` must be a dictionary category; unmatched ones are flagged
      with ``feature_in_dictionary=false`` so the UI can grey them out;
    * item names switch to the dictionary name when matched;
    * method cells switch to the newest dictionary edition; unmatched text
      keeps the original wording without the edition year.
    """
    checked = matched = ambiguous = 0
    method_checked = method_matched = method_normalized = 0
    feature_checked = feature_matched = 0
    unmatched_features: set[str] = set()
    for record in records:
        conditions = record.get("conditions")
        if isinstance(conditions, dict) and _normalize_condition_method(conditions):
            method_normalized += 1
        is_special = str(record.get("profile") or "") in {
            "heat_treatment",
            "qualitative",
        }
        for measure, prop in (record.get("properties") or {}).items():
            if not isinstance(prop, dict):
                continue
            feature = builtin_module._feature_for_measure(record, str(measure))
            if feature:
                feature_aligned = dictionary_module.align_feature(feature)
                feature_checked += 1
                if feature_aligned["matched"]:
                    feature_matched += 1
                else:
                    unmatched_features.add(feature)
                prop["feature"] = feature
                prop["business_category"] = feature_aligned["category"] or feature
                prop["feature_in_dictionary"] = bool(feature_aligned["matched"])
            if not is_special:
                aligned = dictionary_module.align_item(measure, feature)
                checked += 1
                if aligned["status"] in HIT_STATUSES:
                    matched += 1
                elif aligned["status"] == "ambiguous":
                    ambiguous += 1
                prop["business_item"] = aligned.get("item") or ""
                prop["dictionary_status"] = aligned["status"]
            meta = prop.get("meta") if isinstance(prop.get("meta"), dict) else {}
            method = str(meta.get("试验方法") or "").strip()
            if method:
                method_checked += 1
                normalized = dictionary_module.normalize_method(method)
                if normalized.get("matched"):
                    method_matched += 1
                if normalized.get("text") and normalized["text"] != method:
                    method_normalized += 1
                    meta["试验方法原文"] = method
                    meta["试验方法"] = normalized["text"]
                display_name = str(normalized.get("name") or "")
                if display_name and display_name != normalized.get("text"):
                    meta["方法名称"] = display_name
                prop["meta"] = meta
    for entry in inventory_payload.get("items") or []:
        feature = str(entry.get("feature") or "")
        if feature:
            feature_aligned = dictionary_module.align_feature(feature)
            feature_checked += 1
            if feature_aligned["matched"]:
                feature_matched += 1
            else:
                unmatched_features.add(feature)
            entry["feature_in_dictionary"] = bool(feature_aligned["matched"])
            entry["business_category"] = feature_aligned["category"] or feature
        aligned = dictionary_module.align_item(
            entry.get("item") or entry.get("feature"), entry.get("feature")
        )
        checked += 1
        if aligned["status"] in HIT_STATUSES:
            matched += 1
        elif aligned["status"] == "ambiguous":
            ambiguous += 1
        entry["business_item"] = aligned.get("item") or ""
        entry["dictionary_status"] = aligned["status"]
        method = str(entry.get("method") or "").strip()
        if method:
            method_checked += 1
            normalized = dictionary_module.normalize_method(method)
            if normalized.get("matched"):
                method_matched += 1
            if normalized.get("text") and normalized["text"] != method:
                method_normalized += 1
                entry["method_raw"] = method
                entry["method"] = normalized["text"]
            if normalized.get("name"):
                entry["method_name"] = normalized["name"]
    return {
        "version": dictionary_module.version(),
        "features_checked": feature_checked,
        "features_matched": feature_matched,
        "features_unmatched": sorted(unmatched_features)[:50],
        "features_unmatched_count": len(unmatched_features),
        "items_checked": checked,
        "items_matched": matched,
        "items_ambiguous": ambiguous,
        "hit_rate": round(matched / checked, 4) if checked else 0.0,
        "methods_checked": method_checked,
        "methods_matched": method_matched,
        "methods_normalized": method_normalized,
        "method_hit_rate": round(method_matched / method_checked, 4)
        if method_checked
        else 0.0,
    }


def _qualitative_records(
    records: list[dict[str, Any]],
    inventory_payload: dict[str, Any],
    evidence: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build one qualitative record per prose requirement of an inspection item."""
    existing = _existing_features(records)
    known_evidence = {
        str(item.get("evidence_id") or "") for item in evidence if isinstance(item, dict)
    }
    created: list[dict[str, Any]] = []
    items: list[dict[str, Any]] = []
    used_ids: set[str] = set()
    for index, entry in enumerate(inventory_payload.get("items") or [], start=1):
        feature = str(entry.get("feature") or "")
        if feature not in inventory_module.QUALITATIVE_SET:
            continue
        if feature in existing:
            continue
        rows = list(entry.get("requirements") or [])
        if not rows:
            rows = [
                {
                    "text": entry.get("requirement") or "",
                    "clause_id": entry.get("clause_id") or "",
                    "page_no": entry.get("page_no") or 0,
                    "item": entry.get("item") or feature,
                    "method": entry.get("method") or "",
                    "sampling": entry.get("sampling") or {},
                }
            ]
        seen_texts: set[str] = set()
        for row in rows:
            requirement = _clean(row.get("text"))
            if len(requirement) < REQUIREMENT_MIN_LEN:
                continue
            if requirement in seen_texts:
                continue
            seen_texts.add(requirement)
            translated = translate_module.translate_requirement(requirement)
            displayed = translated or requirement
            clause_id = str(row.get("clause_id") or entry.get("clause_id") or "")
            page_no = int(row.get("page_no") or entry.get("page_no") or 0)
            record_id = _record_id(feature, clause_id, index)
            if record_id in used_ids:
                suffix = 2
                while f"{record_id}-{suffix}" in used_ids:
                    suffix += 1
                record_id = f"{record_id}-{suffix}"
            used_ids.add(record_id)
            evidence_id = f"ev-qualitative-{record_id}"
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
            meta = _meta(
                {
                    **entry,
                    "method": entry.get("method") or row.get("method") or "",
                    "sampling": row.get("sampling") or entry.get("sampling") or {},
                }
            )
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
                        "raw": displayed,
                        **(
                            {"raw_original": requirement}
                            if displayed != requirement
                            else {}
                        ),
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
                        **({"feature": feature} if feature else {}),
                        **(
                            {"feature_in_dictionary": entry["feature_in_dictionary"]}
                            if "feature_in_dictionary" in entry
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
            items.append(
                {
                    "feature": feature,
                    "requirement": requirement,
                    "clause_id": clause_id,
                    "clause_ids": list(entry.get("clause_ids") or []),
                    "page_no": page_no,
                    "method": _clean(entry.get("method") or row.get("method")),
                    "sampling": dict(
                        row.get("sampling") or entry.get("sampling") or {}
                    ),
                    "inventory_id": entry.get("inventory_id") or "",
                    "business_item": entry.get("business_item") or "",
                    "business_category": entry.get("business_category") or "",
                    "evidence": [evidence_id],
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
    records[:] = _sanitize(records)
    evidence[:] = _sanitize(evidence)
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
    grades_filled = _inherit_grades(records, ocr)

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
            "grades_filled": grades_filled,
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
