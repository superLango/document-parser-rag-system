"""Import the hansonDoc_RAG three term sets into a business dictionary snapshot.

Input: ``data/business_terms/raw/hanson_terms_export.json`` exported from the
hansonDoc_RAG Postgres ``term_bases``/``terms`` tables:

* 项目大类 (category)  -> ``type="category"``
* 检测项目 (item)      -> ``type="item"`` with ``category_code/category_name``
* 试验方法 (method)    -> ``type="method"`` with ``standard_no``

Output: ``configs/business_dictionary.hanson.json`` (BusinessDictionary).

Usage:
    python tools/import_hanson_terms.py
    python tools/import_hanson_terms.py --input <json> --out <json>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from metal_doc_agent.contracts import (  # noqa: E402
    BusinessDictionary,
    BusinessDictionaryEntry,
)
from metal_doc_agent.items.taxonomy import classify_item  # noqa: E402

BASE_NAMES = ("项目大类", "检测项目", "试验方法")
PAREN_RE = re.compile(r"[（(]([^）)]+)[）)]")
TRAILING_SYMBOL_RE = re.compile(r"([A-Za-z][A-Za-z0-9.]*)$")
ALIAS_SPLIT_RE = re.compile(r"[,，、;；]+")
FEATURE_SPLIT_RE = re.compile(r"[,，、;；.]+")
# Names carrying these words end with a label, not a measurement symbol
# ("晶间腐蚀-方法A" is a test method, not elongation A).
SYMBOL_BLOCK_WORDS = ("方法", "评级", "级别", "类型", "序号", "备注")
CATEGORY_STATUS = {"active": "active", "inactive": "inactive", "pending": "pending"}

# Domain synonyms that bridge document wording to the business category names.
# Kept deliberately small: only well-established metallurgy synonyms.
CATEGORY_ALIASES = {
    "低倍": ["低倍组织"],
    "高倍组织": ["显微组织"],
    "化学成分": ["化学分析"],
    "室温拉伸": ["常温拉伸"],
    "夏比冲击": ["冲击"],
    "布氏硬度": ["HBW"],
    "洛氏硬度": ["HRC", "HRB"],
    "维氏硬度": ["HV"],
    "非金属夹杂": ["非金属夹杂物", "夹杂物"],
    "断裂韧性": ["KIC"],
    "淬透性": ["末端淬透性"],
    "α层": ["α相"],
    "断口": ["断口组织"],
    "晶间腐蚀": ["晶间腐蚀试验"],
    "低周疲劳": ["低循环疲劳"],
    "裂纹扩展速率": ["疲劳裂纹扩展速率", "裂纹扩展"],
    "弯曲": ["冷弯"],
    "扭转": ["扭转试验"],
    "热膨胀": ["线膨胀"],
    "相变点": ["相变温度"],
    "抗氧化": ["抗氧化性"],
    "步冷实验": ["步冷试验"],
    "塔形": ["塔形发纹"],
    "脱碳层": ["脱碳层深度"],
    "铁素体": ["自由铁素体"],
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        default=str(ROOT / "data" / "business_terms" / "raw" / "hanson_terms_export.json"),
    )
    parser.add_argument(
        "--out",
        default=str(ROOT / "configs" / "business_dictionary.hanson.json"),
    )
    parser.add_argument("--version", default=None)
    args = parser.parse_args(argv)

    source = Path(args.input)
    raw_bytes = source.read_bytes()
    payload = json.loads(raw_bytes.decode("utf-8"))
    bases = {base.get("name"): base for base in payload.get("bases", [])}
    missing = [name for name in BASE_NAMES if name not in bases]
    if missing:
        print(f"missing term bases: {', '.join(missing)}")
        return 2

    version = args.version or f"hanson-{hashlib.sha256(raw_bytes).hexdigest()[:8]}"
    categories = _categories(bases["项目大类"].get("terms", []), version)
    category_by_name = {entry.business_name: entry for entry in categories}
    items = _items(bases["检测项目"].get("terms", []), category_by_name, version)
    methods = _methods(bases["试验方法"].get("terms", []), version)

    dictionary = BusinessDictionary(
        version=version,
        source="offline_snapshot",
        entries=[*categories, *items, *methods],
    )
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        dictionary.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"version={version} categories={len(categories)} items={len(items)} "
        f"methods={len(methods)} total={len(dictionary.entries)}"
    )
    print(f"out={target}")
    return 0


def _categories(terms: list[dict], version: str) -> list[BusinessDictionaryEntry]:
    entries: list[BusinessDictionaryEntry] = []
    for term in terms:
        name = _text(term.get("display_name")) or _text(term.get("term_name"))
        code = _text(term.get("code"))
        if not code or not name:
            continue
        family, facets = classify_item(name)
        entries.append(
            BusinessDictionaryEntry(
                business_code=code,
                business_name=name,
                type="category",
                family=None if family == "unknown" else family,
                facets=_facet_lists(facets),
                aliases=CATEGORY_ALIASES.get(name, []),
                status=_status(term.get("status")),
                version=version,
            )
        )
    return entries


def _items(
    terms: list[dict],
    category_by_name: dict[str, BusinessDictionaryEntry],
    version: str,
) -> list[BusinessDictionaryEntry]:
    paren_symbols: dict[str, set[str]] = {}
    for term in terms:
        name = _text(term.get("display_name")) or ""
        feature = _text(term.get("feature")) or ""
        paren_symbols.setdefault(feature, set()).update(
            _parenthetical(name)
        )

    entries: list[BusinessDictionaryEntry] = []
    for term in terms:
        name = _text(term.get("display_name"))
        code = _text(term.get("code"))
        feature = _text(term.get("feature")) or ""
        if not code or not name:
            continue
        extras = _extras(term)
        category = category_by_name.get(feature)
        family, facets = classify_item(name)
        if family == "unknown" and category is not None:
            family = category.family or "unknown"
        entries.append(
            BusinessDictionaryEntry(
                business_code=code,
                business_name=name,
                type="item",
                family=None if family == "unknown" else family,
                facets=_facet_lists(facets),
                aliases=_item_aliases(
                    name, extras, paren_symbols.get(feature, set())
                ),
                category_code=category.business_code if category else None,
                category_name=feature or None,
                status=_status(term.get("status")),
                version=version,
            )
        )
    return entries


def _methods(terms: list[dict], version: str) -> list[BusinessDictionaryEntry]:
    entries: list[BusinessDictionaryEntry] = []
    for term in terms:
        name = _text(term.get("display_name"))
        code = _text(term.get("code"))
        if not code or not name:
            continue
        extras = _extras(term)
        feature = _text(extras.get("FEATURE")) or ""
        aliases = []
        extra_name = _text(extras.get("NAME"))
        if extra_name and extra_name != name:
            aliases.append(extra_name)
        entries.append(
            BusinessDictionaryEntry(
                business_code=code,
                business_name=name,
                type="method",
                facets={"technique": _split_feature(feature)} if feature else {},
                aliases=aliases,
                standard_no=_text(extras.get("METHOD_CODE")),
                status=_status(term.get("status")),
                version=version,
            )
        )
    return entries


def _item_aliases(
    name: str, extras: dict, paren_symbols: set[str]
) -> list[str]:
    aliases: set[str] = set()
    alias_text = _text(extras.get("ITEM_ALIAS"))
    if alias_text:
        for part in ALIAS_SPLIT_RE.split(alias_text):
            _add(aliases, part, name)
    english = _text(extras.get("ENGLISH_NAME"))
    if english:
        _add(aliases, english, name)

    parens = _parenthetical(name)
    for inner in parens:
        _add(aliases, inner, name)
    stripped = PAREN_RE.sub("", name).strip()
    if stripped and stripped != name:
        _add(aliases, stripped, name)

    base = name.split("/")[0].strip()
    if base and base != name:
        _add(aliases, base, name)
    symbol = _trailing_symbol(base)
    if (
        symbol
        and symbol not in paren_symbols
        and not any(word in name for word in SYMBOL_BLOCK_WORDS)
    ):
        _add(aliases, symbol, name)
    return sorted(aliases, key=len)


def _parenthetical(name: str) -> list[str]:
    return [match.group(1).strip() for match in PAREN_RE.finditer(name) if match.group(1).strip()]


def _trailing_symbol(text: str) -> str | None:
    match = TRAILING_SYMBOL_RE.search(text or "")
    if not match:
        return None
    if match.start() > 0 and text[match.start() - 1].isspace():
        return None
    prefix = text[: match.start()]
    if not re.search(r"[\u4e00-\u9fff]", prefix):
        return None
    return match.group(1)


def _add(values: set[str], value: str, name: str) -> None:
    text = (value or "").strip()
    if text and text != name:
        values.add(text)


def _facet_lists(facets: dict[str, str]) -> dict[str, list[str]]:
    return {
        key: [value] for key, value in facets.items() if value
    }


def _split_feature(feature: str) -> list[str]:
    return [part.strip() for part in FEATURE_SPLIT_RE.split(feature) if part.strip()]


def _extras(term: dict) -> dict:
    value = term.get("extras")
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _text(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _status(value) -> str:
    text = str(value or "active").strip().lower()
    return CATEGORY_STATUS.get(text, "active")


if __name__ == "__main__":
    raise SystemExit(main())
