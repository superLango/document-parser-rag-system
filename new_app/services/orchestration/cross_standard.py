"""Cross-standard expansion.

The sandbox detects content references ("化学成分应符合 GB/T 3620.2 的规定")
and reports them as ``cross_standard_candidates``.  This module resolves the
referenced standard against the local library, expands it with deterministic
rules when the source has been parsed, and falls back to an agent task when the
source only has OCR text.  Merging is conservative:

* existing values are never overwritten;
* category imports are merged into the grade rows that already exist;
* every imported value carries the source standard/edition/table/page/quote.
"""

from __future__ import annotations

import copy
import hashlib
import re
import unicodedata
from typing import Any

from .library import latest_row, normalize_standard_no, to_dict

SCHEMA_VERSION = "cross-standard/1"
MAX_TASKS = 12
MAX_SOURCE_DOCUMENTS = 3
MAX_AGENT_TASKS = 6
MAX_IMPORT_RECORDS = 40
CHEMICAL_FEATURE = "化学成分"
MECHANICAL_FEATURES = {
    "力学性能",
    "室温拉伸",
    "高温拉伸",
    "冲击试验",
    "硬度试验",
    "弯曲",
    "弯曲试验",
    "平面应变断裂韧度",
    "持久试验",
}


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(value or ""))).strip()


def _compact(value: Any) -> str:
    return re.sub(r"\s+", "", _clean(value))


def _task_short(task_id: str) -> str:
    return hashlib.sha1(task_id.encode("utf-8")).hexdigest()[:6]


def _standard_variants(standard_no: str) -> list[str]:
    key = normalize_standard_no(standard_no)
    variants = [key]
    trimmed = re.sub(r"(?<=\d)[A-Z]$", "", key)
    if trimmed and trimmed not in variants:
        variants.append(trimmed)
    return variants


def resolve_tasks(
    candidates: list[dict[str, Any]],
    library_rows: list[Any],
    current_records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Attach source resolution and missing-data status to every candidate."""
    rows_by_key: dict[str, list[Any]] = {}
    for row in library_rows:
        key = normalize_standard_no(getattr(row, "standard_no", ""))
        if key:
            rows_by_key.setdefault(key, []).append(row)
    current_grades = sorted(
        {
            str(record.get("grade") or "").strip()
            for record in current_records or []
            if str(record.get("grade") or "").strip()
        }
    )
    tasks: list[dict[str, Any]] = []
    for candidate in candidates[:MAX_TASKS]:
        task = copy.deepcopy(candidate)
        standard_no = normalize_standard_no(task.get("standard_no"))
        matched: list[Any] = []
        for variant in _standard_variants(standard_no):
            matched.extend(rows_by_key.get(variant) or [])
        best = latest_row(matched)
        task["current_grades"] = current_grades
        task["supplement"] = bool(
            task.get("supplement")
            or re.search(r"其他|其余|除.{0,6}外", _clean(task.get("quote")))
        )
        if best is None:
            task["status"] = "needs_source"
            task["gap"] = f"标准库未收录 {standard_no}"
            task["resolution"] = {}
            tasks.append(task)
            continue
        row = to_dict(best)
        task["resolution"] = row
        if not row["latest_run_id"]:
            task["status"] = "needs_source"
            task["gap"] = f"{standard_no} 已上传，尚未解析"
        elif row["status"] not in {"parsed", "ocr_ready"}:
            task["status"] = "needs_source"
            task["gap"] = f"{standard_no} 解析状态：{row['status']}"
        else:
            task["status"] = "resolved"
            task["gap"] = ""
        task["edition_replaced"] = bool(
            task.get("edition")
            and row.get("edition")
            and str(task["edition"]) != str(row["edition"])
        )
        tasks.append(task)
    return tasks


def _source_label(task: dict[str, Any]) -> str:
    resolution = task.get("resolution") or {}
    standard_no = resolution.get("standard_no") or task.get("standard_no")
    edition = resolution.get("edition") or ""
    clause = task.get("clause_id") or ""
    label = f"{standard_no}{('-' + edition) if edition else ''}"
    if clause:
        label += f" {clause}"
    return label


def _feature_matches(record: dict[str, Any], feature: str) -> bool:
    profile = str(record.get("profile") or "")
    if feature == CHEMICAL_FEATURE:
        if profile == "chemical_composition":
            return True
    if feature in MECHANICAL_FEATURES and profile == "mechanical_properties":
        return True
    for prop in (record.get("properties") or {}).values():
        if not isinstance(prop, dict):
            continue
        if feature in {
            str(prop.get("business_category") or ""),
            str(prop.get("feature") or ""),
        }:
            return True
    return False


def _target_record(
    records: list[dict[str, Any]], feature: str, grade: str
) -> dict[str, Any] | None:
    for record in records:
        if str(record.get("grade") or "") != grade:
            continue
        if _feature_matches(record, feature):
            return record
    return None


def _has_value(prop: Any) -> bool:
    if not isinstance(prop, dict):
        return False
    return bool(str(prop.get("raw") or "").strip()) or prop.get("value") is not None


def _profile_for(feature: str) -> str:
    if feature == CHEMICAL_FEATURE:
        return "chemical_composition"
    if feature in MECHANICAL_FEATURES:
        return "mechanical_properties"
    return "qualitative"


def _provenance(task: dict[str, Any], extra: dict[str, Any] | None = None) -> dict[str, Any]:
    resolution = task.get("resolution") or {}
    payload = {
        "kind": "cross_standard",
        "standard_no": resolution.get("standard_no") or task.get("standard_no"),
        "edition": resolution.get("edition") or task.get("edition") or "",
        "document_id": resolution.get("document_id") or "",
        "clause_id": task.get("clause_id") or "",
        "page_no": int(task.get("page_no") or 0),
        "quote": task.get("quote") or "",
        "label": _source_label(task),
    }
    if extra:
        payload.update(extra)
    return payload


def expand_deterministic(
    task: dict[str, Any],
    records: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    source_records: list[dict[str, Any]],
    source_inventory: dict[str, Any],
    source_evidence: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Expand one resolved task from the source's parsed artifacts.

    Returns ``{status, proposals, records_added, conflicts, reason}``.  A
    proposal is either a new record or a patch to an existing record.
    """
    feature = str(task.get("feature") or "")
    parameter = str(task.get("parameter") or "")
    current_grades = set(task.get("current_grades") or [])
    if parameter:
        # 参数级（允许偏差/等级/半径）通常不在来源记录里，交给 Agent 读取原文。
        return {"status": "needs_agent", "reason": "parameter_requires_text"}
    candidates = [record for record in source_records if _feature_matches(record, feature)]
    if not candidates:
        items = [
            item
            for item in source_inventory.get("items") or []
            if isinstance(item, dict)
            and feature
            in {
                str(item.get("feature") or ""),
                str(item.get("business_category") or ""),
            }
        ]
        if items:
            return _expand_inventory(task, records, items)
        return {"status": "skipped", "reason": "source_category_not_found"}
    evidence_by_id = {
        str(item.get("evidence_id")): item
        for item in source_evidence or []
        if isinstance(item, dict)
    }
    proposals: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    added = 0
    for record in candidates:
        if added >= MAX_IMPORT_RECORDS:
            break
        grade = str(record.get("grade") or "").strip()
        if not grade:
            # 跨标准补入的记录也要有可读牌号，不能留下空牌号行。
            grade = next(iter(current_grades)) if len(current_grades) == 1 else "全部牌号"
        if current_grades and grade and grade not in current_grades and grade != "全部牌号":
            continue
        source_quote = ""
        source_page = int(record.get("page_no") or 0)
        for ref in record.get("evidence_refs") or []:
            item = evidence_by_id.get(str(ref))
            if item:
                source_quote = _clean(item.get("quote"))
                source_page = int(item.get("page_no") or source_page)
                break
        target = _target_record(records, feature, grade)
        if target is None:
            new_record = copy.deepcopy(record)
            new_record["record_id"] = f"XS-{_task_short(str(task.get('task_id')))}-{added + 1}"
            new_record["table_id"] = str(record.get("table_id") or "cross_standard")
            new_record["grade"] = grade
            new_record["source"] = _provenance(task)
            for prop in (new_record.get("properties") or {}).values():
                if not isinstance(prop, dict):
                    continue
                prop["source"] = _provenance(task)
                meta = prop.get("meta") if isinstance(prop.get("meta"), dict) else {}
                meta["跨标准来源"] = _source_label(task)
                prop["meta"] = meta
            proposals.append(
                {
                    "kind": "record",
                    "record": new_record,
                    "quote": source_quote,
                    "page_no": source_page,
                }
            )
            added += 1
            continue
        for measure, prop in (record.get("properties") or {}).items():
            if not isinstance(prop, dict):
                continue
            existing = (target.get("properties") or {}).get(measure)
            if _has_value(existing):
                if _compact(existing.get("raw")) != _compact(prop.get("raw")):
                    conflicts.append(
                        {
                            "record_id": target.get("record_id"),
                            "measure": measure,
                            "current": (existing or {}).get("raw"),
                            "imported": prop.get("raw"),
                        }
                    )
                continue
            copied = copy.deepcopy(prop)
            copied["source"] = _provenance(task)
            meta = copied.get("meta") if isinstance(copied.get("meta"), dict) else {}
            meta["跨标准来源"] = _source_label(task)
            copied["meta"] = meta
            proposals.append(
                {
                    "kind": "property",
                    "record_id": target.get("record_id"),
                    "measure": measure,
                    "property": copied,
                    "quote": source_quote,
                    "page_no": source_page,
                }
            )
    if not proposals and conflicts:
        return {"status": "conflict", "conflicts": conflicts, "reason": "values_conflict"}
    if not proposals:
        return {"status": "skipped", "reason": "nothing_missing"}
    return {
        "status": "expanded",
        "proposals": proposals,
        "records_added": added,
        "conflicts": conflicts,
    }


def _expand_inventory(
    task: dict[str, Any],
    records: list[dict[str, Any]],
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    feature = str(task.get("feature") or "")
    existing = {
        str(next(iter(record.get("properties") or {})))
        for record in records
        if record.get("profile") == "qualitative" and record.get("properties")
    }
    if feature in existing:
        return {"status": "skipped", "reason": "qualitative_already_present"}
    proposals: list[dict[str, Any]] = []
    current_grades = set(task.get("current_grades") or [])
    grade = next(iter(current_grades)) if len(current_grades) == 1 else "全部牌号"
    for index, item in enumerate(items[:1], start=1):
        requirement = _clean(item.get("requirement"))
        if len(requirement) < 4:
            continue
        record_id = f"XS-{_task_short(str(task.get('task_id')))}-Q{index}"
        meta = {"跨标准来源": _source_label(task)}
        method = _clean(item.get("method"))
        if method:
            meta["试验方法"] = method
        proposals.append(
            {
                "kind": "record",
                "record": {
                    "record_id": record_id,
                    "table_id": "cross_standard",
                    "page_no": int(task.get("page_no") or 0),
                    "row_index": index - 1,
                    "recipe_id": "",
                    "recipe_version": "",
                    "profile": "qualitative",
                    "grade": grade,
                    "conditions": {},
                    "condition_key": "",
                    "properties": {
                        feature: {
                            "raw": requirement,
                            "value": None,
                            "unit": "",
                            "comparator": "text",
                            "column": "跨标准引用",
                            "meta": meta,
                            "profile": "qualitative",
                            "business_item": item.get("business_item") or "",
                            "business_category": item.get("business_category") or feature,
                            "feature": feature,
                            "feature_in_dictionary": item.get("feature_in_dictionary", True),
                            "source": _provenance(task),
                        }
                    },
                    "evidence_refs": [],
                    "source": _provenance(task),
                },
            }
        )
    if not proposals:
        return {"status": "skipped", "reason": "requirement_too_short"}
    return {"status": "expanded", "proposals": proposals, "records_added": 1, "conflicts": []}


def apply_proposals(
    records: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    task: dict[str, Any],
    proposals: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """Apply record/property proposals in place; returns (records, evidence, ids)."""
    by_id = {str(record.get("record_id")): record for record in records}
    added_ids: list[str] = []
    provenance = _provenance(task)
    for index, proposal in enumerate(proposals, start=1):
        quote = _clean(proposal.get("quote")) or _clean(task.get("quote"))
        page_no = int(proposal.get("page_no") or task.get("page_no") or 0)
        if proposal["kind"] == "record":
            record = proposal["record"]
            records.append(record)
            added_ids.append(str(record.get("record_id")))
            evidence_id = f"ev-xstd-{_task_short(str(task.get('task_id')))}-{index}"
            record["evidence_refs"] = [evidence_id]
            evidence.append(
                {
                    "evidence_id": evidence_id,
                    "table_id": record.get("table_id") or "cross_standard",
                    "page_no": page_no or record.get("page_no") or 0,
                    "row_index": record.get("row_index") or 0,
                    "raw_row": [],
                    "cells": {},
                    "quote": quote[:400],
                    "source": "cross_standard",
                    "provenance": provenance,
                }
            )
            continue
        record = by_id.get(str(proposal.get("record_id")))
        if record is None:
            continue
        record.setdefault("properties", {})[proposal["measure"]] = proposal["property"]
        evidence_id = f"ev-xstd-{_task_short(str(task.get('task_id')))}-{index}"
        refs = list(record.get("evidence_refs") or [])
        if evidence_id not in refs:
            refs.append(evidence_id)
            record["evidence_refs"] = refs
        evidence.append(
            {
                "evidence_id": evidence_id,
                "table_id": record.get("table_id") or "",
                "page_no": page_no or record.get("page_no") or 0,
                "row_index": record.get("row_index") or 0,
                "raw_row": [],
                "cells": {},
                "quote": quote[:400],
                "source": "cross_standard",
                "provenance": provenance,
            }
        )
    return records, evidence, added_ids


def build_agent_task(
    tasks: list[dict[str, Any]],
    *,
    run_id: str,
    trace_id: str,
    max_items: int = 8,
) -> dict[str, Any] | None:
    """Build the AgentTask payload for textual/parameter expansion."""
    pending = [
        task
        for task in tasks
        if task.get("status") in {"needs_agent", "resolved"}
        and not task.get("_expanded")
    ][:MAX_AGENT_TASKS]
    if not pending:
        return None
    sources = []
    seen: set[str] = set()
    for task in pending:
        resolution = task.get("resolution") or {}
        document_id = str(resolution.get("document_id") or "")
        if not document_id or document_id in seen:
            continue
        seen.add(document_id)
        sources.append(
            {
                "standard_no": resolution.get("standard_no"),
                "edition": resolution.get("edition"),
                "document_id": document_id,
                "categories": resolution.get("categories") or [],
                "grades": resolution.get("grades") or [],
            }
        )
    return {
        "task_id": f"xstd-{run_id}",
        "trace_id": trace_id or run_id,
        "role": "cross_standard",
        "objective": (
            "从被引标准的正文/表格中找出当前文档缺失的验收要求。"
            "只返回能在来源原文中逐字找到引用的值，不得编造。"
        ),
        "inputs": {
            "tasks": [
                {
                    "task_id": task.get("task_id"),
                    "feature": task.get("feature"),
                    "parameter": task.get("parameter"),
                    "scope": task.get("scope"),
                    "quote": task.get("quote"),
                    "clause_id": task.get("clause_id"),
                    "page_no": task.get("page_no"),
                    "current_grades": task.get("current_grades") or [],
                }
                for task in pending
            ],
            "sources": sources[:MAX_SOURCE_DOCUMENTS],
            "allowed_fields": ["标准要求", "试验方法", "取样数量", "取样说明"],
        },
        "output_schema": {
            "type": "object",
            "required": ["items"],
            "properties": {
                "items": {
                    "type": "array",
                    "maxItems": max_items,
                    "items": {
                        "type": "object",
                        "required": ["task_id", "feature", "quote", "standard_no"],
                        "properties": {
                            "task_id": {"type": "string"},
                            "feature": {"type": "string"},
                            "parameter": {"type": "string"},
                            "grade": {"type": "string"},
                            "measure": {"type": "string"},
                            "requirement": {"type": "string"},
                            "value": {"type": "number"},
                            "unit": {"type": "string"},
                            "operator": {"type": "string"},
                            "quote": {"type": "string"},
                            "standard_no": {"type": "string"},
                            "clause_id": {"type": "string"},
                            "table_id": {"type": "string"},
                            "page_no": {"type": "integer"},
                        },
                    },
                },
                "notes": {"type": "array", "items": {"type": "string"}},
            },
        },
        "tools": [
            "library_search",
            "library_outline",
            "library_section",
            "library_table",
        ],
        "budget": {
            "max_steps": 8,
            "max_tool_calls": 12,
            "max_tokens": 48000,
            "wall_time_seconds": 90,
        },
        "metadata": {"source": "cross_standard", "tasks": len(pending)},
    }


def validate_agent_items(
    items: Any,
    tasks: list[dict[str, Any]],
    source_texts: dict[str, str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Accept only items whose quote exists in the resolved source text."""
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    if not isinstance(items, list):
        return accepted, [{"reason": "items_not_a_list"}]
    by_task = {str(task.get("task_id")): task for task in tasks}
    compact_sources = {key: _compact(text) for key, text in source_texts.items()}
    for raw in items:
        if not isinstance(raw, dict):
            rejected.append({"reason": "item_not_an_object"})
            continue
        task = by_task.get(str(raw.get("task_id") or ""))
        quote = _clean(raw.get("quote"))
        standard_no = normalize_standard_no(raw.get("standard_no"))
        reason = ""
        if task is None:
            reason = "unknown_task"
        elif not quote or len(quote) < 8:
            reason = "quote_too_short"
        elif standard_no and standard_no != normalize_standard_no(
            (task.get("resolution") or {}).get("standard_no") or task.get("standard_no")
        ):
            reason = "standard_mismatch"
        else:
            document_id = str((task.get("resolution") or {}).get("document_id") or "")
            text = compact_sources.get(document_id) or ""
            if text and _compact(quote) not in text:
                reason = "quote_not_found"
        if reason:
            rejected.append({"task_id": raw.get("task_id"), "reason": reason})
            continue
        accepted.append(
            {
                "task_id": str(raw.get("task_id")),
                "feature": _clean(raw.get("feature")) or str(task.get("feature") or ""),
                "parameter": _clean(raw.get("parameter")) or str(task.get("parameter") or ""),
                "grade": _clean(raw.get("grade")),
                "measure": _clean(raw.get("measure")),
                "requirement": _clean(raw.get("requirement")),
                "value": raw.get("value"),
                "unit": _clean(raw.get("unit")),
                "operator": _clean(raw.get("operator")),
                "quote": quote,
                "standard_no": standard_no,
                "clause_id": _clean(raw.get("clause_id")),
                "table_id": _clean(raw.get("table_id")),
                "page_no": int(raw.get("page_no") or 0),
            }
        )
    return accepted, rejected


def apply_agent_items(
    tasks: list[dict[str, Any]],
    records: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    items: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Merge accepted agent items; only fills empty values."""
    by_task = {str(task.get("task_id")): task for task in tasks}
    imported = 0
    conflicts = 0
    records_added: list[str] = []
    for index, item in enumerate(items, start=1):
        task = by_task.get(item["task_id"])
        if task is None:
            continue
        provenance = _provenance(
            task, extra={"page_no": item.get("page_no") or task.get("page_no")}
        )
        feature = item["feature"] or str(task.get("feature") or "")
        grade = item["grade"]
        if not grade:
            grades = set(task.get("current_grades") or [])
            grade = next(iter(grades)) if len(grades) == 1 else "全部牌号"
        target = _target_record(records, feature, grade) if grade else None
        if target is None and feature and item["measure"]:
            record_id = (
                f"XS-{_task_short(item['task_id'])}-A{index}"
            )
            meta = {"跨标准来源": _source_label(task)}
            if item.get("requirement"):
                meta["跨标准要求"] = item["requirement"]
            if item.get("table_id"):
                meta["来源表"] = item["table_id"]
            record = {
                "record_id": record_id,
                "table_id": item.get("table_id") or "cross_standard",
                "page_no": item.get("page_no") or 0,
                "row_index": index - 1,
                "recipe_id": "",
                "recipe_version": "",
                "profile": _profile_for(feature),
                "grade": grade,
                "conditions": {},
                "condition_key": "",
                "properties": {
                    item["measure"]: {
                        "raw": item.get("requirement") or (
                            f"{item.get('operator') or ''}{item.get('value')}"
                            if item.get("value") is not None
                            else ""
                        ),
                        "value": item.get("value"),
                        "unit": item.get("unit") or "",
                        "operator": item.get("operator") or None,
                        "column": "跨标准引用",
                        "meta": meta,
                        "business_item": item["measure"],
                        "business_category": feature,
                        "feature": feature,
                        "feature_in_dictionary": True,
                        "source": provenance,
                    }
                },
                "evidence_refs": [],
                "source": provenance,
            }
            records.append(record)
            records_added.append(record_id)
            target = record
            imported += 1
        elif target is not None and item["measure"]:
            existing = (target.get("properties") or {}).get(item["measure"])
            if _has_value(existing):
                conflicts += 1
                continue
            prop = {
                "raw": item.get("requirement") or (
                    f"{item.get('operator') or ''}{item.get('value')}"
                    if item.get("value") is not None
                    else ""
                ),
                "value": item.get("value"),
                "unit": item.get("unit") or "",
                "operator": item.get("operator") or None,
                "column": "跨标准引用",
                "meta": {"跨标准来源": _source_label(task)},
                "business_item": item["measure"],
                "business_category": feature,
                "feature": feature,
                "feature_in_dictionary": True,
                "source": provenance,
            }
            target.setdefault("properties", {})[item["measure"]] = prop
            imported += 1
        if target is None:
            continue
        evidence_id = f"ev-xstd-a-{_task_short(item['task_id'])}-{index}"
        refs = list(target.get("evidence_refs") or [])
        if evidence_id not in refs:
            refs.append(evidence_id)
            target["evidence_refs"] = refs
        evidence.append(
            {
                "evidence_id": evidence_id,
                "table_id": target.get("table_id") or "",
                "page_no": target.get("page_no") or 0,
                "row_index": target.get("row_index") or 0,
                "raw_row": [],
                "cells": {},
                "quote": item["quote"][:400],
                "source": "cross_standard",
                "provenance": provenance,
            }
        )
    return records, evidence, {
        "imported": imported,
        "conflicts": conflicts,
        "records_added": records_added,
    }


def summarize(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for task in tasks:
        status = str(task.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    return {
        "tasks": len(tasks),
        "needs_source": counts.get("needs_source", 0),
        "resolved": counts.get("resolved", 0),
        "expanded": counts.get("expanded", 0),
        "conflict": counts.get("conflict", 0),
        "skipped": counts.get("skipped", 0),
        "needs_agent": counts.get("needs_agent", 0),
        "rejected": counts.get("rejected", 0),
    }
