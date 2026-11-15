"""Business dictionary alignment for parsed items and methods.

Standard library only.  The snapshot (``dictionary_data.json``) is published
with the parser bundle so its version moves together with the parsing rules.
Alignment is additive: it never replaces the internal feature taxonomy, it adds
``business_item`` / ``business_category`` / ``method_name`` for traceability.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "business-dictionary/1"
DICT_FILE = Path(__file__).with_name("dictionary_data.json")
_NORMALIZE_STRIP = re.compile(r"[\s\-—_/\\()（）\[\]【】·•.,，、;；:：]+")
_data_cache: dict[str, Any] | None = None
_index_cache: dict[str, Any] | None = None

# Internal feature names that do not literally appear in the business
# dictionary but belong to a known category.
FEATURE_CATEGORY_HINTS = {
    "夏比冲击": "冲击试验",
    "布氏硬度": "硬度试验",
    "洛氏硬度": "硬度试验",
    "维氏硬度": "硬度试验",
    "断裂韧度": "平面应变断裂韧度",
    "非金属夹杂": "高倍",
    "铁素体": "高倍",
    "外观": "外观质量",
}


def _normalize(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).lower()
    return _NORMALIZE_STRIP.sub("", text)


def _normalize_standard(value: Any) -> str:
    """Normalize a standard number while keeping ``/ . -`` separators."""
    text = unicodedata.normalize("NFKC", str(value or "")).lower()
    text = re.sub(r"\s+", "", text)
    for char in ("－", "—", "–", ":", "："):
        text = text.replace(char, "-")
    return re.sub(r"[^a-z0-9.\-/]", "", text)


def load_dictionary() -> dict[str, Any]:
    global _data_cache
    if _data_cache is not None:
        return _data_cache
    for path in (DICT_FILE,):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(payload, dict):
            _data_cache = payload
            return payload
    _data_cache = {}
    return _data_cache


def _indexes() -> dict[str, Any]:
    global _index_cache
    if _index_cache is not None:
        return _index_cache
    payload = load_dictionary()

    def build(kind: str) -> tuple[dict[str, dict], list[tuple[str, list[dict]]]]:
        exact: dict[str, dict] = {}
        aliases: dict[str, list[dict]] = {}
        for entry in payload.get(kind) or []:
            if not isinstance(entry, dict):
                continue
            name = _normalize(entry.get("name"))
            if name:
                exact.setdefault(name, entry)
            for alias in [entry.get("name"), *(entry.get("aliases") or [])]:
                key = _normalize(alias)
                if not key:
                    continue
                bucket = aliases.setdefault(key, [])
                if not any(item.get("name") == entry.get("name") for item in bucket):
                    bucket.append(entry)
        contained = sorted(
            ((key, entries) for key, entries in aliases.items() if len(key) >= 2),
            key=lambda item: -len(item[0]),
        )
        return exact, contained

    item_exact, item_aliases = build("items")
    category_exact, category_aliases = build("categories")
    method_exact, method_aliases = build("methods")
    method_numbers: dict[str, dict] = {}
    method_bases: dict[str, list[dict]] = {}
    for entry in payload.get("methods") or []:
        number = _normalize_standard(entry.get("standard_no"))
        if not number:
            continue
        method_numbers.setdefault(number, entry)
        base = re.sub(r"-\d{4}$", "", number)
        bucket = method_bases.setdefault(base, [])
        if not any(item.get("name") == entry.get("name") for item in bucket):
            bucket.append(entry)
    _index_cache = {
        "version": str(payload.get("version") or ""),
        "item_exact": item_exact,
        "item_aliases": item_aliases,
        "category_exact": category_exact,
        "category_aliases": category_aliases,
        "method_exact": method_exact,
        "method_aliases": method_aliases,
        "method_numbers": method_numbers,
        "method_bases": method_bases,
    }
    return _index_cache


def _match(
    text: Any,
    exact: dict[str, dict],
    aliases: list[tuple[str, list[dict]]],
    *,
    min_contained: int = 2,
) -> tuple[dict | None, str]:
    key = _normalize(text)
    if not key:
        return None, "miss"
    hit = exact.get(key)
    if hit is not None:
        return hit, "exact"
    for alias, entries in aliases:
        if len(alias) < min_contained:
            continue
        if alias not in key:
            continue
        names = {str(entry.get("name") or "") for entry in entries}
        if len(names) == 1:
            return entries[0], "alias"
        preferred = [
            entry
            for entry in entries
            if _normalize(entry.get("name")).endswith(alias)
        ]
        if len({str(entry.get("name") or "") for entry in preferred}) == 1:
            return preferred[0], "alias"
        return None, "ambiguous"
    return None, "miss"


def match_item(text: Any) -> tuple[dict | None, str]:
    indexes = _indexes()
    return _match(text, indexes["item_exact"], indexes["item_aliases"])


def match_category(text: Any) -> tuple[dict | None, str]:
    indexes = _indexes()
    return _match(text, indexes["category_exact"], indexes["category_aliases"])


def _category_for(feature: Any) -> tuple[dict | None, str]:
    entry, status = match_category(feature)
    if entry is not None:
        return entry, status
    hint = FEATURE_CATEGORY_HINTS.get(str(feature or ""))
    if hint:
        entry, status = match_category(hint)
        if entry is not None:
            return entry, status
    return None, "miss"


NUMBER_IN_TEXT = re.compile(
    r"(GB\s*/\s*T|GB|GJB|JB|YB|YS\s*/\s*T|HB|ASTM|ISO|AMS|EN|DIN)\s*"
    r"[A-Z]?\s*\d+(?:\.\d+)*(?:\s*-\s*\d{4})?",
    re.IGNORECASE,
)


def match_method(text: Any) -> tuple[dict | None, str]:
    indexes = _indexes()
    raw = unicodedata.normalize("NFKC", str(text or ""))
    for match in NUMBER_IN_TEXT.finditer(raw):
        key = _normalize_standard(match.group(0))
        entry = indexes["method_numbers"].get(key)
        if entry is not None:
            return entry, "standard_no"
        # Parsed methods usually omit the edition year; the dictionary may
        # carry it, so fall back to the base number.
        base = re.sub(r"-\d{4}$", "", key)
        entries = indexes["method_bases"].get(base) or []
        if entries:
            return entries[0], "standard_base"
    entry, status = _match(
        raw,
        indexes["method_exact"],
        indexes["method_aliases"],
        min_contained=4,
    )
    return entry, status


def align_item(name: Any, feature: Any = "") -> dict[str, str]:
    """Map a measured item/feature to the business dictionary.

    ``status`` is one of ``exact`` / ``alias`` / ``category`` / ``ambiguous`` /
    ``miss``.
    """
    entry, status = match_item(name)
    category_entry, _ = _category_for(feature)
    if entry is not None:
        # The internal feature category is authoritative when both exist; the
        # item name still gives the fine-grained business name.
        category = str((category_entry or {}).get("name") or entry.get("category") or "")
        family = str((category_entry or {}).get("family") or entry.get("family") or "")
        return {
            "item": str(entry.get("name") or ""),
            "category": category,
            "family": family,
            "status": status,
        }
    if category_entry is not None:
        return {
            "item": "",
            "category": str(category_entry.get("name") or ""),
            "family": str(category_entry.get("family") or ""),
            "status": "category",
        }
    return {"item": "", "category": "", "family": "", "status": status}


def align_method(text: Any) -> dict[str, str] | None:
    entry, status = match_method(text)
    if entry is None:
        return None
    return {
        "name": str(entry.get("name") or ""),
        "standard_no": str(entry.get("standard_no") or ""),
        "status": status,
    }


def version() -> str:
    return str(_indexes().get("version") or "")
