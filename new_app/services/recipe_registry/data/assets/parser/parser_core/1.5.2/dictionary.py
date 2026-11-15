"""Business dictionary alignment for parsed items and methods.

Standard library only.  The snapshot (``dictionary_data.json``) is published
with the parser bundle so its version moves together with the parsing rules.

Alignment is authoritative for display: a matched item switches to the
dictionary name, a matched method switches to the newest dictionary edition,
and an unmatched feature is reported so the UI can grey it out.
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
    "高倍组织": "高倍",
    "高温持久": "持久试验",
    "外观": "外观质量",
}


# Internal measure symbols whose business item name is unambiguous even though
# qualified variants ("低温抗拉强度(Rm)") also exist.  Keys are normalized.
MEASURE_ITEM_HINTS = {
    "rm": "抗拉强度",
    "rp02": "屈服强度",
    "rel": "下屈服强度",
    "reh": "上屈服强度",
    "a": "断后伸长率",
    "z": "断面收缩率",
    "kv2": "冲击吸收功(KV2)",
    "ku2": "冲击吸收功(KU2)",
    "hb": "布氏硬度",
    "hbs": "布氏硬度",
    "hbw": "布氏硬度",
    "hrb": "洛氏硬度",
    "hrc": "洛氏硬度",
    "hv": "维氏硬度",
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
        for base in _base_variants(number):
            bucket = method_bases.setdefault(base, [])
            if not any(
                _normalize_standard(item.get("standard_no")) == number
                for item in bucket
            ):
                bucket.append(entry)
    # Newest edition wins when several editions share a base number.
    for bucket in method_bases.values():
        bucket.sort(key=lambda item: (-_edition_year(item), str(item.get("name") or "")))
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


def _edition_year(entry: dict) -> int:
    """Four-digit edition year of a method entry; 0 when the edition is unknown."""
    number = str(entry.get("standard_no") or entry.get("name") or "").lower()
    match = re.search(r"-(\d{2,4})(?=[a-z]?$)", number)
    if not match:
        return 0
    year = int(match.group(1))
    if len(match.group(1)) == 2:
        year += 1900 if year >= 70 else 2000
    return year


def _base_variants(number: str) -> list[str]:
    """Base-number candidates for a normalized standard number.

    ``gb/t 228.1-2021`` and ``gb/t 228.1`` share a base; ``ams 2643f`` also
    answers to ``ams 2643`` because the revision letter is not always printed.
    """
    variants = [number]
    base = re.sub(r"-\d{2,4}[a-z]?$", "", number)
    if base and base != number:
        variants.append(base)
    for value in list(variants):
        trimmed = re.sub(r"(?<=\d)[a-z]{1,2}$", "", value)
        if trimmed and trimmed != value and trimmed not in variants:
            variants.append(trimmed)
    return variants


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
    hint = MEASURE_ITEM_HINTS.get(_normalize(text))
    if hint:
        entry = indexes["item_exact"].get(_normalize(hint))
        if entry is not None:
            return entry, "alias"
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
    r"(GB\s*/\s*T|GB|GJB|JB\s*/\s*T|JB|YB\s*/\s*T|YB|YS\s*/\s*T|HB\s*/\s*T|HB|"
    r"ASTM|ASME|AMS|AETM|ISO|EN|DIN|JIS|SAE|API|MIL|NB|Q\s*/\s*HT|JY\s*/\s*T|GBN)"
    r"\s*([A-Z]{0,3})\s*(-?)\s*(\d+(?:\.\d+)*)"
    r"\s*([A-Za-z])?\s*(?:[-—–－]\s*(\d{2,4}))?([A-Za-z])?",
    re.IGNORECASE,
)


def _newest(entries: list[dict]) -> dict | None:
    if not entries:
        return None
    return min(entries, key=lambda item: (-_edition_year(item), str(item.get("standard_no") or "")))


def _match_number(raw_number: str) -> tuple[dict | None, str]:
    indexes = _indexes()
    key = _normalize_standard(raw_number)
    if not key:
        return None, "miss"
    candidates: list[dict] = []
    for base in _base_variants(key):
        candidates.extend(indexes["method_bases"].get(base) or [])
    newest = _newest(candidates)
    if newest is not None:
        status = (
            "standard_no"
            if _normalize_standard(newest.get("standard_no")) == key
            else "standard_base"
        )
        return newest, status
    entry = indexes["method_numbers"].get(key)
    if entry is not None:
        return entry, "standard_no"
    return None, "miss"


def match_method(text: Any) -> tuple[dict | None, str]:
    indexes = _indexes()
    raw = unicodedata.normalize("NFKC", str(text or ""))
    for match in NUMBER_IN_TEXT.finditer(raw):
        entry, status = _match_number(match.group(0))
        if entry is not None:
            return entry, status
    entry, status = _match(
        raw,
        indexes["method_exact"],
        indexes["method_aliases"],
        min_contained=4,
    )
    return entry, status


def align_feature(feature: Any) -> dict[str, Any]:
    """Check whether an internal feature maps to a business dictionary category."""
    entry, status = _category_for(feature)
    if entry is None:
        return {"category": "", "family": "", "status": status, "matched": False}
    return {
        "category": str(entry.get("name") or ""),
        "family": str(entry.get("family") or ""),
        "status": status,
        "matched": True,
    }


def _method_display(entry: dict) -> str:
    """Prefer the standard number; proprietary entries fall back to their name."""
    standard_no = str(entry.get("standard_no") or "").strip()
    if standard_no:
        return standard_no
    return str(entry.get("name") or "").strip()


def _strip_edition(text: str) -> str:
    stripped = re.sub(r"\s*[-—–－]\s*(\d{4}|\d{2})\s*$", "", text.strip())
    return stripped.strip() or text.strip()


def normalize_method(text: Any) -> dict[str, Any]:
    """Normalize one 试验方法 cell against the dictionary.

    Matched standard numbers switch to the newest dictionary edition; unmatched
    text keeps the original wording with the edition year stripped.
    """
    raw = unicodedata.normalize("NFKC", str(text or "")).strip()
    if not raw:
        return {"text": "", "matched": False, "name": "", "standard_no": "", "status": "miss"}
    pieces: list[str] = []
    last = 0
    matched_entry: dict | None = None
    matched_status = "miss"
    replaced = 0
    for match in NUMBER_IN_TEXT.finditer(raw):
        entry, status = _match_number(match.group(0))
        if entry is None:
            continue
        pieces.append(raw[last : match.start()])
        pieces.append(_method_display(entry))
        last = match.end()
        replaced += 1
        if matched_entry is None:
            matched_entry = entry
            matched_status = status
    if matched_entry is None:
        entry, status = _match(
            raw,
            _indexes()["method_exact"],
            _indexes()["method_aliases"],
            min_contained=4,
        )
        if entry is not None:
            return {
                "text": _method_display(entry),
                "matched": True,
                "name": str(entry.get("name") or ""),
                "standard_no": str(entry.get("standard_no") or ""),
                "status": status,
            }
        return {
            "text": _strip_edition(raw),
            "matched": False,
            "name": "",
            "standard_no": "",
            "status": status,
        }
    pieces.append(raw[last:])
    normalized = re.sub(r"\s{2,}", " ", "".join(pieces)).strip(" 、,，;；")
    return {
        "text": normalized,
        "matched": True,
        "name": str(matched_entry.get("name") or ""),
        "standard_no": str(matched_entry.get("standard_no") or ""),
        "status": matched_status,
        "replaced": replaced,
    }


def align_method(text: Any) -> dict[str, str] | None:
    entry, status = match_method(text)
    if entry is None:
        return None
    return {
        "name": str(entry.get("name") or ""),
        "standard_no": str(entry.get("standard_no") or ""),
        "status": status,
    }


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
