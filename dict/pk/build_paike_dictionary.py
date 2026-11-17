"""Replace the business dictionary with a customer's LIMS export (检测项目/试验方法 + 项目大类).

Input format (业务词表new.txt, exported from sm_item / sm_method):
    检测项目，项目大类：
    <item>,<category>           category may be empty or a quoted comma list
    试验方法，项目大类：
    <method code>,<free text>   free text mixes categories and techniques

The customer list is authoritative: only its names survive.  Categories are the distinct
item categories.  When a name already exists in the current snapshot (by name or alias;
methods by normalized standard number) the existing entry is reused so aliases/family keep
feeding the matcher.

Usage: python build_paike_dictionary.py <词表.txt> <current business_dictionary.json> <out.json> <new_app dir>
"""

from __future__ import annotations

import copy
import csv
import hashlib
import importlib.util
import json
import re
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

FEATURE_SPLIT = re.compile(r"\s*(?:[,，、/;；]|\s+|\d+\.)\s*")


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parse_export(text: str) -> tuple[list[tuple[str, list[str]]], list[tuple[str, list[str]]]]:
    sections: dict[str, list[tuple[str, list[str]]]] = {"item": [], "method": []}
    kind = None
    for raw in text.splitlines():
        line = raw.strip().lstrip("﻿")
        if not line or line.lower().startswith("select"):
            continue
        if line.endswith(("：", ":")) and "项目大类" in line:
            kind = "method" if "方法" in line else "item"
            continue
        if kind is None:
            raise ValueError(f"词条出现在分段标题之前：{line!r}")
        row = next(csv.reader([line]))
        name = row[0].strip()
        features = [f for f in FEATURE_SPLIT.split(",".join(row[1:])) if f and f != "/"]
        if name:
            sections[kind].append((name, features))
    return sections["item"], sections["method"]


def enrich_from_old_terms(entries: list[dict], old_terms: list[dict], h, stats: Counter) -> None:
    """Add aliases/English names (items) and full titles (methods) from the old system's
    LIMS-synced term bases.  An alias already owned by another entry is skipped so the
    matcher never sees it as ambiguous."""

    item_extra: dict = {}
    method_title: dict = {}
    for term in old_terms:
        extras = term.get("extras") or {}
        if term.get("base") == "检测项目" and extras.get("NAME"):
            item_extra.setdefault(h.entry_key("item", extras["NAME"]), extras)
        elif term.get("base") == "试验方法" and extras.get("METHOD_CODE") and extras.get("NAME"):
            for standard_no in h.extract_standards(extras["METHOD_CODE"]) or [h.clean(extras["METHOD_CODE"])]:
                method_title.setdefault(h.entry_key("method", standard_no), h.clean(extras["NAME"]))

    owner: dict = {}
    for entry in entries:
        if entry["type"] == "item":
            for name in [entry["business_name"], *(entry.get("aliases") or [])]:
                owner.setdefault(h.entry_key("item", name), entry["business_code"])

    for entry in entries:
        if entry["type"] == "item":
            extras = item_extra.get(h.entry_key("item", entry["business_name"]))
            if not extras:
                continue
            for alias in (extras.get("ITEM_ALIAS"), extras.get("ENGLISH_NAME")):
                alias = h.clean(alias or "")
                key = h.entry_key("item", alias)
                if not key[1] or owner.get(key, entry["business_code"]) != entry["business_code"]:
                    stats["old_alias_skipped_conflict"] += bool(key[1])
                    continue
                if alias not in (entry.get("aliases") or []) and alias != entry["business_name"]:
                    h.merge_aliases(entry, alias)
                    owner[key] = entry["business_code"]
                    stats["old_alias_added"] += 1
            if extras.get("UNIT"):
                entry.setdefault("facets", {})["unit"] = extras["UNIT"]
        elif entry["type"] == "method" and entry["business_name"] == entry.get("standard_no"):
            title = method_title.get(h.entry_key("method", entry["standard_no"]))
            if title and title != entry["business_name"]:
                h.merge_aliases(entry, entry["business_name"])
                entry["business_name"] = title
                stats["old_method_title"] += 1


def build(words: Path, current_path: Path, app_root: Path, old_terms: list[dict] | None = None) -> tuple[dict, dict]:
    h = load_module(app_root / "scripts/import_dictionary/import_xlsx_dictionary.py", "xlsx_import")
    hints = load_module(app_root / "services/sandbox/runtime/dictionary.py", "parser_dict").FEATURE_CATEGORY_HINTS
    raw = words.read_bytes()
    version = f"paike-lims-{hashlib.sha256(raw).hexdigest()[:8]}"
    items_in, methods_in = parse_export(raw.decode("utf-8-sig"))
    current = json.loads(current_path.read_text(encoding="utf-8"))
    old = [e for e in current.get("entries") or [] if isinstance(e, dict)]

    def index(kind: str, with_aliases: bool) -> dict:
        found: dict = {}
        for entry in old:
            if entry.get("type") != kind:
                continue
            if kind == "method":
                names = [entry.get("standard_no") or ""] + list(entry.get("aliases") or [])
                names = [h.normalize_standard(n)[0] for n in names if n]
            else:
                names = [entry.get("business_name") or ""]
                if with_aliases:
                    names += list(entry.get("aliases") or [])
            for name in names:
                key = h.entry_key(kind, str(name))
                if key[1] and key not in found:
                    found[key] = entry
        return found

    # 检测项目/大类只按名称完全相同复用，保证 LIMS 里每个名称都有独立词条；
    # 别名命中只用来借族类（methods 按标准号复用，别名即标准号写法）。
    indexes = {kind: index(kind, kind == "method") for kind in ("category", "item", "method")}
    alias_owner = {kind: index(kind, True) for kind in ("category", "item")}
    counters = {kind: h.next_code(old, kind) for kind in ("category", "item", "method")}
    entries: list[dict] = []
    by_code: dict[str, dict] = {}
    stats = Counter()

    def put(kind: str, name: str, key_name: str, **fields) -> tuple[dict, bool]:
        """Return (entry, created_now); an entry already emitted is returned as-is."""
        existing = indexes[kind].get(h.entry_key(kind, key_name))
        if existing is not None and existing["business_code"] in by_code:
            stats[f"merged_{kind}"] += 1
            return by_code[existing["business_code"]], False
        if existing is not None:
            entry = copy.deepcopy(existing)
            if kind != "method" and entry["business_name"] != name:
                h.merge_aliases(entry, entry["business_name"])
                entry["business_name"] = name
            stats[f"reused_{kind}"] += 1
        else:
            entry = {
                "business_code": f"{kind.upper()}:{counters[kind]}",
                "business_name": name, "type": kind, "family": None, "facets": {},
                "aliases": [], "standard_no": None, "category_code": None, "category_name": None,
                **fields,
            }
            owner = alias_owner.get(kind, {}).get(h.entry_key(kind, key_name))
            if owner is not None:
                entry["family"] = owner.get("family")
                stats[f"family_from_alias_{kind}"] += 1
            counters[kind] += 1
            stats[f"created_{kind}"] += 1
        entry.update(status="active", version=version, source_file=words.name)
        indexes[kind][h.entry_key(kind, key_name)] = entry
        by_code[entry["business_code"]] = entry
        entries.append(entry)
        return entry, True

    # 项目大类 = 检测项目里出现过的大类
    categories: dict[str, dict] = {}
    for _, features in items_in:
        for feature in features:
            if feature in categories:
                continue
            entry, _ = put("category", h.clean(feature), feature)
            hint = hints.get(feature)
            legacy = indexes["category"].get(h.entry_key("category", hint)) if hint else None
            if legacy is not None and legacy is not entry:
                # 解析内核的内部分类映射到汉唐名称：借用族类，并让汉唐名称也能命中该大类
                entry["family"] = entry.get("family") or legacy.get("family")
                h.merge_aliases(entry, legacy["business_name"], *(legacy.get("aliases") or []))
                stats["category_hint_enriched"] += 1
            categories[feature] = entry

    for name, features in items_in:
        entry, created = put("item", h.clean(name), name)
        if features:
            known = list(dict.fromkeys(entry.get("facets", {}).get("categories", [])))
            entry.setdefault("facets", {})["categories"] = list(dict.fromkeys(known + features))
            if created or not entry.get("category_code") or entry["category_code"] not in {
                c["business_code"] for c in categories.values()
            }:
                primary = categories[features[0]]
                entry["category_code"] = primary["business_code"]
                entry["category_name"] = primary["business_name"]
                entry["family"] = entry.get("family") or primary.get("family")
        elif entry.get("category_code") and entry["category_code"] not in {
            c["business_code"] for c in categories.values()
        }:
            entry["category_code"] = entry["category_name"] = None
            stats["item_category_dropped"] += 1

    for line, features in methods_in:
        standards = h.extract_standards(line) or [h.clean(line)]
        for standard_no in standards:
            entry, _ = put("method", standard_no, standard_no, standard_no=standard_no)
            if h.clean(line) != entry["business_name"]:
                h.merge_aliases(entry, h.clean(line))
            facets = entry.setdefault("facets", {})
            facets["lims_feature"] = list(dict.fromkeys(facets.get("lims_feature", []) + features))
            linked = next((categories[f] for f in features if f in categories), None)
            if linked and not entry.get("category_code"):
                entry["category_code"] = linked["business_code"]
                entry["category_name"] = linked["business_name"]

    if old_terms is not None:
        enrich_from_old_terms(entries, old_terms, h, stats)

    # 沿用的汉唐别名若恰好是另一个派克词条的名称，会让匹配变成“有歧义”，去掉
    for kind in ("category", "item"):
        owned = {h.entry_key(kind, e["business_name"]): e for e in entries if e["type"] == kind}
        for entry in entries:
            if entry["type"] != kind:
                continue
            kept = [a for a in entry.get("aliases") or []
                    if owned.get(h.entry_key(kind, a), entry) is entry]
            stats[f"alias_dropped_{kind}"] += len(entry.get("aliases") or []) - len(kept)
            entry["aliases"] = kept

    # 检测项目与项目大类一对多：每个大类各一条同名词条（独立编码），别名等信息相同。
    # 解析内核按名称合并同名词条，不会判为歧义；大类以表格所属分类为准。
    split: list[dict] = []
    for entry in entries:
        if entry["type"] != "item":
            continue
        listed = [c for c in (entry.get("facets") or {}).get("categories", []) if c in categories]
        if not listed:
            continue
        for index, feature in enumerate(listed):
            target = entry if index == 0 else copy.deepcopy(entry)
            if index:
                target["business_code"] = f"ITEM:{counters['item']}"
                counters["item"] += 1
                split.append(target)
                stats["item_split_extra"] += 1
            target["category_code"] = categories[feature]["business_code"]
            target["category_name"] = categories[feature]["business_name"]
            target["family"] = target.get("family") or categories[feature].get("family")
    entries.extend(split)

    order = {"category": 0, "item": 1, "method": 2}
    entries.sort(key=lambda e: (order[e["type"]], e["business_code"]))
    types = Counter(e["type"] for e in entries)
    payload = {
        "schema_version": current.get("schema_version") or "2.0",
        "version": version,
        "source": "paike-lims-export",
        "source_files": [words.name],
        "stats": {
            "entries": len(entries), "categories": types["category"], "items": types["item"],
            "methods": types["method"],
            "aliases": sum(len(e.get("aliases") or []) for e in entries),
            "active": len(entries), "inactive": 0,
        },
        "entries": entries,
    }
    report = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "input_rows": {"items": len(items_in), "methods": len(methods_in)},
        "changes": dict(stats),
        "stats": payload["stats"],
        "items_without_category": sum(1 for e in entries if e["type"] == "item" and not e.get("category_code")),
    }
    return payload, report


def main() -> int:
    words, current, out, app_root = (Path(p) for p in sys.argv[1:5])
    old_terms = json.loads(Path(sys.argv[5]).read_text(encoding="utf-8")) if len(sys.argv) > 5 else None
    payload, report = build(words, current, app_root, old_terms)
    codes = [e["business_code"] for e in payload["entries"]]
    assert len(set(codes)) == len(codes), "duplicate business_code"
    cat_codes = {e["business_code"] for e in payload["entries"] if e["type"] == "category"}
    assert all(not e.get("category_code") or e["category_code"] in cat_codes
               for e in payload["entries"]), "dangling category_code"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
