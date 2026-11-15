"""Document-level metadata repair (方法/取样) from inventory evidence.

The parser attaches 试验方法/取样 to records from inspection tables and prose.
When a record misses those fields but the inventory already holds the evidence,
the feedback flow can override the missing metadata without changing parser
code or re-running OCR.
"""

from __future__ import annotations

import re
from typing import Any

METHOD_FIELD = "试验方法"
SAMPLING_FIELDS = ("取样说明", "位置", "取样数量")


def _compact(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or ""))


def _item_matches(item: dict[str, Any], subject: str) -> bool:
    if not subject:
        return False
    feature = _compact(item.get("feature"))
    name = _compact(item.get("item"))
    return subject in feature or subject in name


def find_method_evidence(
    inventory: dict[str, Any] | None,
    subject: str,
    field: str,
) -> dict[str, str]:
    """Return the documented 试验方法/取样 fields for a subject, if present."""
    items = list((inventory or {}).get("items") or [])
    if not items:
        return {}
    candidates = [item for item in items if isinstance(item, dict) and _item_matches(item, subject)]
    if not candidates:
        return {}
    # 精确 feature 优先，其次取第一条有证据的条目。
    candidates.sort(
        key=lambda item: (
            _compact(item.get("feature")) != _compact(subject),
            str(item.get("item") or ""),
        )
    )
    evidence: dict[str, str] = {}
    if field == METHOD_FIELD:
        method = str(candidates[0].get("method") or "").strip()
        if method:
            evidence[METHOD_FIELD] = method
        return evidence
    sampling = candidates[0].get("sampling") or {}
    if isinstance(sampling, dict):
        mapping = {
            "取样说明": "note",
            "位置": "location",
            "取样数量": "quantity",
        }
        for target, source in mapping.items():
            value = str(sampling.get(source) or "").strip()
            if value:
                evidence[target] = value
    return evidence


def build_metadata_override(
    table_id: str, profile: str, fields: dict[str, str]
) -> dict[str, Any]:
    return {
        "table_id": table_id,
        "profile": profile,
        "fields": {key: value for key, value in fields.items() if value},
    }


def apply_metadata_override(
    records: list[dict[str, Any]], override: dict[str, Any] | None
) -> int:
    """Fill only empty metadata fields; returns the number of values written."""
    override = override or {}
    fields = {
        str(key): str(value)
        for key, value in (override.get("fields") or {}).items()
        if value
    }
    if not fields:
        return 0
    table_id = str(override.get("table_id") or "")
    profile = str(override.get("profile") or "")
    filled = 0
    for record in records or []:
        if table_id and str(record.get("table_id") or "") != table_id:
            continue
        if profile and str(record.get("profile") or "") != profile:
            continue
        conditions = record.setdefault("conditions", {})
        for key, value in fields.items():
            if not str(conditions.get(key) or "").strip():
                conditions[key] = value
                filled += 1
        for prop in (record.get("properties") or {}).values():
            if not isinstance(prop, dict):
                continue
            meta = prop.get("meta")
            if not isinstance(meta, dict):
                meta = {}
                prop["meta"] = meta
            for key, value in fields.items():
                if not str(meta.get(key) or "").strip():
                    meta[key] = value
                    filled += 1
    return filled
