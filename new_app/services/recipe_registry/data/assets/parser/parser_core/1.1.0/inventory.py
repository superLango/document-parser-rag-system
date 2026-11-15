"""Document item inventory: what the standard asks the laboratory to test.

The inventory merges three sources into one authoritative list:

* ``property_table``  - performance tables that already produced records;
* ``inspection_table`` - 检验项目表 rows (method / sampling / clause number);
* ``clause``          - prose requirements that never appear in a table.

Rows carry a stable status so the projection layer and the reviewer can tell a
confirmed numerical item from a prose-only item.  Standard library only.
"""

from __future__ import annotations

import re
from typing import Any

try:  # imported as a package (tests)
    from .builtin import _feature_for_measure, _normalize_doc_text
except ImportError:  # flat runtime image (/engine)
    from builtin import _feature_for_measure, _normalize_doc_text

SCHEMA_VERSION = "document-inventory/1"

# Features that can only be judged from prose/qualitative requirements.
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

# Order matters: 高温拉伸 before 拉伸, 布氏 before generic 硬度.
FEATURE_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("化学成分", ("化学成分", "化学分析", "成分分析")),
    ("高温拉伸", ("高温拉伸",)),
    ("室温拉伸", ("室温拉伸", "拉伸试验", "拉伸")),
    ("夏比冲击", ("夏比冲击", "冲击试验", "冲击")),
    ("布氏硬度", ("布氏硬度", "布氏")),
    ("洛氏硬度", ("洛氏硬度", "洛氏")),
    ("维氏硬度", ("维氏硬度", "维氏")),
    ("断裂韧度", ("断裂韧性", "断裂韧度", "断裂韧")),
    ("弯曲", ("弯曲试验", "弯曲")),
    ("晶粒度", ("晶粒度",)),
    ("低倍", ("低倍组织", "低倍")),
    ("高倍组织", ("高倍组织", "显微组织")),
    ("非金属夹杂", ("非金属夹杂", "夹杂物")),
    ("超声波检测", ("超声波检测", "超声波", "超声检测", "超声")),
    ("铁素体", ("铁素体",)),
    ("外观", ("外观质量", "外观")),
    ("尺寸", ("尺寸", "外形")),
)
FAMILY_BY_FEATURE = {
    "化学成分": "chemical",
    "室温拉伸": "mechanical",
    "高温拉伸": "mechanical",
    "夏比冲击": "mechanical",
    "布氏硬度": "mechanical",
    "洛氏硬度": "mechanical",
    "维氏硬度": "mechanical",
    "断裂韧度": "mechanical",
    "弯曲": "mechanical",
    "高温持久": "mechanical",
    "晶粒度": "metallographic",
    "低倍": "metallographic",
    "高倍组织": "metallographic",
    "非金属夹杂": "metallographic",
    "超声波检测": "nondestructive",
    "铁素体": "metallographic",
    "外观": "visual",
    "尺寸": "dimension",
}
SKIP_CLAUSE_KINDS = {"scope", "normative_reference", "terms"}
AGGREGATE_ITEMS = {"力学性能", "机械性能", "性能"}
# Rows that label a block or a note, never an inspection item.
SKIP_ITEMS = {
    "说明",
    "备注",
    "注",
    "目录",
    "序号",
    "引用文件",
    "规范性引用文件",
    "检验项目",
    "项目",
}


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", _normalize_doc_text(value)).strip(" ，,、;；")


def feature_from_text(text: Any) -> str:
    value = _clean(text)
    if not value:
        return ""
    for feature, keywords in FEATURE_KEYWORDS:
        if any(keyword in value for keyword in keywords):
            return feature
    return ""


def _entry(feature: str, item: str) -> dict[str, Any]:
    return {
        "inventory_id": "",
        "item": item or feature,
        "feature": feature,
        "family": FAMILY_BY_FEATURE.get(feature, ""),
        "source": "",
        "sources": [],
        "clause_id": "",
        "clause_ids": [],
        "table_ids": [],
        "requirement": "",
        "method": "",
        "sampling": {"quantity": "", "location": "", "note": ""},
        "status": "probable",
        "page_no": 0,
        "evidence": [],
        "conflicts": [],
    }


def _add_source(entry: dict[str, Any], source: str) -> None:
    if source and source not in entry["sources"]:
        entry["sources"].append(source)
    if not entry["source"]:
        entry["source"] = source


def _add_evidence(entry: dict[str, Any], evidence_id: str) -> None:
    if evidence_id and evidence_id not in entry["evidence"]:
        entry["evidence"].append(evidence_id)


def _merge_method(entry: dict[str, Any], method: str) -> None:
    value = _clean(method)
    if not value:
        return
    if not entry["method"]:
        entry["method"] = value
    elif value not in entry["method"] and entry["method"] not in value:
        entry["conflicts"].append(f"method:{entry['method']}!={value}")


def _record_entries(
    records: list[dict[str, Any]], entries: dict[str, dict[str, Any]]
) -> set[str]:
    features: set[str] = set()
    for record in records:
        if str(record.get("profile") or "") in {"heat_treatment", "qualitative"}:
            continue
        table_id = str(record.get("table_id") or "")
        page_no = int(record.get("page_no") or 0)
        for measure in record.get("properties") or {}:
            feature = _feature_for_measure(record, str(measure))
            if not feature:
                continue
            features.add(feature)
            entry = entries.setdefault(feature, _entry(feature, feature))
            _add_source(entry, "property_table")
            entry["status"] = "confirmed"
            if table_id and table_id not in entry["table_ids"]:
                entry["table_ids"].append(table_id)
            if not entry["page_no"]:
                entry["page_no"] = page_no
    return features


def _inspection_entries(
    inspections: list[dict[str, str]],
    entries: dict[str, dict[str, Any]],
    evidence_sink: list[dict[str, Any]],
) -> None:
    for index, item in enumerate(inspections, start=1):
        name = _clean(item.get("item"))
        if not name or name in SKIP_ITEMS or len(name) < 2:
            continue
        feature = feature_from_text(name)
        key = feature or f"item:{name}"
        entry = entries.setdefault(key, _entry(feature, name))
        _add_source(entry, "inspection_table")
        if feature and entry["status"] != "confirmed":
            entry["status"] = "probable"
        if name and name != entry["item"]:
            entry["item"] = name
        _merge_method(entry, str(item.get("method") or ""))
        sampling = entry["sampling"]
        if not sampling["quantity"]:
            sampling["quantity"] = _clean(item.get("quantity"))
        if not sampling["location"]:
            sampling["location"] = _clean(item.get("location"))
        note = _clean(item.get("note"))
        if note and note not in sampling["note"]:
            sampling["note"] = f"{sampling['note']}；{note}" if sampling["note"] else note
        evidence_id = f"ev-inspection-{index}"
        quote = "；".join(
            part
            for part in (
                name,
                _clean(item.get("quantity")),
                _clean(item.get("location")),
                _clean(item.get("method")),
                _clean(item.get("note")),
            )
            if part
        )
        _add_evidence(entry, evidence_id)
        evidence_sink.append(
            {
                "evidence_id": evidence_id,
                "table_id": "",
                "page_no": 0,
                "row_index": index - 1,
                "raw_row": [],
                "cells": {},
                "quote": quote[:400],
                "source": "inspection_table",
            }
        )


def _clause_entries(
    clauses: list[dict[str, Any]],
    entries: dict[str, dict[str, Any]],
    evidence_sink: list[dict[str, Any]],
) -> None:
    for clause in clauses:
        kind = str(clause.get("kind") or "")
        if kind in SKIP_CLAUSE_KINDS:
            continue
        fields = clause.get("fields") or {}
        requirement = _clean((fields.get("requirement") or {}).get("raw"))
        title = _clean(clause.get("title"))
        clause_id = str(clause.get("clause_id") or "")
        if not requirement and not title:
            continue
        feature = feature_from_text(title)
        if not feature:
            feature = feature_from_text(requirement)
        if not feature:
            continue
        entry = entries.setdefault(feature, _entry(feature, feature))
        _add_source(entry, "clause")
        if feature and entry["status"] != "confirmed":
            entry["status"] = "probable"
        if clause_id:
            entry["clause_id"] = entry["clause_id"] or clause_id
            if clause_id not in entry["clause_ids"]:
                entry["clause_ids"].append(clause_id)
        if not entry["page_no"]:
            entry["page_no"] = int(clause.get("page_no") or 0)
        if requirement and not entry["requirement"]:
            entry["requirement"] = requirement
        method = _clean((fields.get("method_standard") or {}).get("raw"))
        _merge_method(entry, method)
        sampling = entry["sampling"]
        if not sampling["quantity"]:
            sampling["quantity"] = _clean((fields.get("sample_quantity") or {}).get("raw"))
        if not sampling["location"]:
            sampling["location"] = _clean((fields.get("sample_location") or {}).get("raw"))
        for evidence in clause.get("evidence") or []:
            _add_evidence(entry, str(evidence.get("evidence_id") or ""))
        if requirement and not any(
            str(item.get("evidence_id") or "").startswith(f"ev-clause-{clause_id}")
            for item in evidence_sink
        ):
            evidence_sink.append(
                {
                    "evidence_id": f"ev-clause-{clause_id}",
                    "table_id": "",
                    "page_no": int(clause.get("page_no") or 0),
                    "row_index": 0,
                    "raw_row": [],
                    "cells": {},
                    "quote": requirement[:400],
                    "source": "clause",
                }
            )


def build_inventory(
    records: list[dict[str, Any]],
    clauses_payload: dict[str, Any],
    inspections: list[dict[str, str]],
) -> dict[str, Any]:
    """Merge records, inspection rows and clauses into the item inventory."""
    entries: dict[str, dict[str, Any]] = {}
    evidence_sink: list[dict[str, Any]] = []
    record_features = _record_entries(records, entries)
    _inspection_entries(inspections, entries, evidence_sink)
    _clause_entries(clauses_payload.get("clauses") or [], entries, evidence_sink)

    items: list[dict[str, Any]] = []
    for entry in entries.values():
        if entry["conflicts"] and entry["status"] != "confirmed":
            entry["status"] = "ambiguous"
        if not entry["sources"]:
            entry["status"] = "new"
        items.append(entry)
    items.sort(
        key=lambda item: (
            0 if item["status"] == "confirmed" else 1,
            str(item["feature"] or item["item"]),
        )
    )
    for index, entry in enumerate(items, start=1):
        entry["inventory_id"] = f"inv-{index:03d}"

    inventory_features = {
        str(entry["feature"]) for entry in items if entry.get("feature")
    }
    aligned = sorted(record_features & inventory_features)
    coverage = {
        "record_features": sorted(record_features),
        "inventory_features": sorted(inventory_features),
        "aligned": aligned,
        "aligned_ratio": round(
            len(aligned) / len(record_features), 4
        )
        if record_features
        else 0.0,
        "confirmed": sum(1 for entry in items if entry["status"] == "confirmed"),
        "probable": sum(1 for entry in items if entry["status"] == "probable"),
        "ambiguous": sum(1 for entry in items if entry["status"] == "ambiguous"),
        "clause_only": sum(
            1
            for entry in items
            if entry["status"] == "probable"
            and "clause" in entry["sources"]
            and "property_table" not in entry["sources"]
        ),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "items": items,
        "coverage": coverage,
        "evidence": evidence_sink,
    }
