"""Live business-system acceptance smoke (G1.8).

Fetches the business dictionary over HTTP, validates its shape, aligns the
M1.7 ItemInventory artifacts, and writes an acceptance report.

Environment variables (all optional):
    BUSINESS_API_BASE_URL, BUSINESS_API_KEY
    BUSINESS_DICTIONARY_PATH, BUSINESS_ITEMS_PATH, BUSINESS_METHODS_PATH
    BUSINESS_AUTH_HEADER, BUSINESS_AUTH_PREFIX
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from metal_doc_agent.canonicalize import (  # noqa: E402
    BusinessApiError,
    DictionaryIndex,
    HttpDictionaryAdapter,
    align_inventory,
)
from metal_doc_agent.canonicalize.items import property_aliases  # noqa: E402
from metal_doc_agent.canonicalize.normalize import (  # noqa: E402
    extract_standards,
    normalize_item_name,
    standard_base,
)
from metal_doc_agent.contracts import BusinessDictionary, ItemInventory  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=os.environ.get("BUSINESS_API_BASE_URL"))
    parser.add_argument("--api-key", default=os.environ.get("BUSINESS_API_KEY"))
    parser.add_argument(
        "--dictionary-path",
        default=os.environ.get("BUSINESS_DICTIONARY_PATH") or None,
    )
    parser.add_argument(
        "--items-path",
        default=os.environ.get("BUSINESS_ITEMS_PATH", "/items"),
    )
    parser.add_argument(
        "--methods-path",
        default=os.environ.get("BUSINESS_METHODS_PATH", "/methods"),
    )
    parser.add_argument(
        "--auth-header",
        default=os.environ.get("BUSINESS_AUTH_HEADER", "Authorization"),
    )
    parser.add_argument(
        "--auth-prefix",
        default=os.environ.get("BUSINESS_AUTH_PREFIX", "Bearer "),
    )
    parser.add_argument(
        "--snapshot",
        default=os.environ.get("BUSINESS_DICTIONARY_SNAPSHOT"),
        help="offline BusinessDictionary JSON (skips HTTP)",
    )
    parser.add_argument("--runs", default=str(ROOT / "runs" / "m1.5_qwen"))
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument(
        "--out", default=str(ROOT / "eval" / "business" / "live")
    )
    parser.add_argument("--min-item-rate", type=float, default=0.95)
    parser.add_argument("--min-category-rate", type=float, default=0.95)
    parser.add_argument("--min-method-rate", type=float, default=0.95)
    parser.add_argument("--skip-align", action="store_true")
    args = parser.parse_args(argv)

    try:
        dictionary = _load(args)
    except BusinessApiError as error:
        print(f"business API error: {error}")
        _write_failure(Path(args.out), args, str(error))
        return 1

    validation = _validate(dictionary)
    index = DictionaryIndex.build(dictionary)
    alignment = (
        _skip_alignment()
        if args.skip_align
        else _align(index, Path(args.runs), args.limit)
    )
    checks = _checks(validation, alignment, args)
    passed = all(check["passed"] for check in checks)
    report = {
        "mode": "snapshot" if args.snapshot else "http",
        "target": args.snapshot or args.base_url,
        "dictionary": {
            "version": dictionary.version,
            "source": dictionary.source,
            "entries": len(dictionary.entries),
            "categories": validation["categories_total"],
            "items": validation["items_total"],
            "methods": validation["methods_total"],
        },
        "validation": validation,
        "alignment": alignment,
        "checks": checks,
        "passed": passed,
    }
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "g1_8_live.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (out_dir / "g1_8_live.md").write_text(_render(report), encoding="utf-8")
    print(
        "entries={entries} categories={categories} items={items} methods={methods} "
        "known_category={category_rate:.3f} known_item={item_rate:.3f} "
        "known_method={method_rate:.3f} passed={passed}".format(
            entries=len(dictionary.entries),
            categories=validation["categories_total"],
            items=validation["items_total"],
            methods=validation["methods_total"],
            category_rate=alignment.get("category_match_rate", 0.0),
            item_rate=alignment.get("item_match_rate", 0.0),
            method_rate=alignment.get("method_match_rate", 0.0),
            passed=passed,
        )
    )
    print(f"out={out_dir}")
    return 0 if passed else 3


def _load(args) -> BusinessDictionary:
    if args.snapshot:
        return BusinessDictionary.model_validate_json(
            Path(args.snapshot).read_text(encoding="utf-8")
        )
    if not args.base_url:
        raise BusinessApiError(
            "missing --base-url / BUSINESS_API_BASE_URL or --snapshot"
        )
    adapter = HttpDictionaryAdapter(
        args.base_url,
        api_key=args.api_key,
        dictionary_path=args.dictionary_path,
        items_path=args.items_path,
        methods_path=args.methods_path,
        auth_header=args.auth_header,
        auth_prefix=args.auth_prefix,
    )
    return adapter.load()


def _validate(dictionary: BusinessDictionary) -> dict:
    categories = [
        entry for entry in dictionary.entries if entry.type == "category"
    ]
    items = [entry for entry in dictionary.entries if entry.type == "item"]
    methods = [entry for entry in dictionary.entries if entry.type == "method"]
    codes: Counter = Counter(
        (entry.type, entry.business_code) for entry in dictionary.entries
    )
    duplicates = [
        f"{entry_type}:{code}"
        for (entry_type, code), count in codes.items()
        if count > 1
    ]
    missing_names = [
        entry.business_code
        for entry in dictionary.entries
        if not entry.business_name.strip()
    ]
    items_without_category = [
        entry.business_code
        for entry in items
        if categories and not entry.category_code
    ]
    return {
        "version": dictionary.version,
        "source": dictionary.source,
        "entries_total": len(dictionary.entries),
        "categories_total": len(categories),
        "items_total": len(items),
        "methods_total": len(methods),
        "active_categories": sum(
            1 for entry in categories if entry.status == "active"
        ),
        "active_items": sum(1 for entry in items if entry.status == "active"),
        "active_methods": sum(1 for entry in methods if entry.status == "active"),
        "families": dict(
            Counter(entry.family or "unknown" for entry in items).most_common()
        ),
        "methods_with_standard": sum(
            1 for entry in methods if entry.standard_no
        ),
        "items_without_category": items_without_category,
        "duplicates": duplicates,
        "missing_names": missing_names,
    }


def _align(index: DictionaryIndex, runs_dir: Path, limit: int) -> dict:
    category_mode = index.has_categories
    totals: Counter = Counter()
    known: Counter = Counter()
    docs: list[dict] = []
    for path in sorted(runs_dir.glob("*/item_inventory.json"))[:limit]:
        inventory = ItemInventory.model_validate_json(
            path.read_text(encoding="utf-8")
        )
        aligned, result = align_inventory(inventory, index)
        summary = result.summary
        for key in (
            "categories_total",
            "categories_matched",
            "categories_new",
            "categories_ambiguous",
            "items_total",
            "items_matched",
            "items_new",
            "items_ambiguous",
            "properties_total",
            "properties_matched",
            "properties_new",
            "properties_ambiguous",
            "methods_total",
            "methods_matched",
            "methods_new",
            "methods_ambiguous",
            "new_categories",
            "new_items",
            "new_methods",
            "new_terms",
        ):
            totals[key] += summary[key]
        for entry, match in zip(aligned.items, result.item_matches):
            if category_mode:
                if _category_known(entry, index):
                    known["categories_total"] += 1
                    known["categories_matched"] += int(match.status == "matched")
            elif _item_known(entry, index):
                known["items_total"] += 1
                known["items_matched"] += int(match.status == "matched")
            for prop_match in entry.property_matches:
                if _property_known(prop_match.raw, index):
                    known["properties_total"] += 1
                    if prop_match.status == "matched":
                        known["properties_matched"] += 1
                    elif _duplicate_conflict(prop_match.reason):
                        known["properties_conflict"] += 1
        for method_match in result.method_matches:
            if _method_known(method_match.raw, index):
                known["methods_total"] += 1
                known["methods_matched"] += int(
                    method_match.status == "matched"
                )
        docs.append(
            {
                "doc": path.parent.name,
                **summary,
            }
        )

    item_known = (
        _known_rate(
            known["properties_matched"],
            known["properties_total"],
            known["properties_conflict"],
        )
        if known["properties_total"]
        else _known_rate(
            known["items_matched"],
            known["items_total"],
            known["items_conflict"],
        )
    )
    return {
        "docs": len(docs),
        "category_mode": category_mode,
        "categories_total": totals["categories_total"],
        "categories_matched": totals["categories_matched"],
        "categories_new": totals["categories_new"],
        "categories_ambiguous": totals["categories_ambiguous"],
        "category_coverage": _rate(
            totals["categories_matched"], totals["categories_total"]
        ),
        "category_match_rate": _known_rate(
            known["categories_matched"],
            known["categories_total"],
            known["categories_conflict"],
        ),
        "known_categories_total": known["categories_total"],
        "known_categories_matched": known["categories_matched"],
        "known_categories_conflict": known["categories_conflict"],
        "items_total": totals["items_total"],
        "items_matched": totals["items_matched"],
        "items_new": totals["items_new"],
        "items_ambiguous": totals["items_ambiguous"],
        "item_coverage": _rate(
            totals["items_matched"], totals["items_total"]
        ),
        "item_match_rate": item_known,
        "known_items_total": known["properties_total"] or known["items_total"],
        "known_items_matched": known["properties_matched"]
        or known["items_matched"],
        "known_items_conflict": known["properties_conflict"]
        or known["items_conflict"],
        "properties_total": totals["properties_total"],
        "properties_matched": totals["properties_matched"],
        "properties_new": totals["properties_new"],
        "properties_ambiguous": totals["properties_ambiguous"],
        "property_coverage": _rate(
            totals["properties_matched"], totals["properties_total"]
        ),
        "property_match_rate": _known_rate(
            known["properties_matched"],
            known["properties_total"],
            known["properties_conflict"],
        ),
        "known_properties_total": known["properties_total"],
        "known_properties_matched": known["properties_matched"],
        "known_properties_conflict": known["properties_conflict"],
        "methods_total": totals["methods_total"],
        "methods_matched": totals["methods_matched"],
        "methods_new": totals["methods_new"],
        "methods_ambiguous": totals["methods_ambiguous"],
        "method_coverage": _rate(
            totals["methods_matched"], totals["methods_total"]
        ),
        "method_match_rate": _known_rate(
            known["methods_matched"],
            known["methods_total"],
            known["methods_conflict"],
        ),
        "known_methods_total": known["methods_total"],
        "known_methods_matched": known["methods_matched"],
        "known_methods_conflict": known["methods_conflict"],
        "new_terms": totals["new_terms"],
        "new_categories": totals["new_categories"],
        "new_items": totals["new_items"],
        "new_methods": totals["new_methods"],
        "per_doc": docs,
    }


def _category_known(entry, index: DictionaryIndex) -> bool:
    for name in (entry.item_raw, entry.item_canonical):
        key = normalize_item_name(name)
        if key and (key in index.category_name_index or key in index.category_alias_index):
            return True
    return False


def _item_known(entry, index: DictionaryIndex) -> bool:
    for name in (entry.item_raw, entry.item_canonical):
        key = normalize_item_name(name)
        if key and (
            ("item", key) in index.name_index
            or ("item", key) in index.alias_index
        ):
            return True
    return False


def _property_known(raw: str, index: DictionaryIndex) -> bool:
    for name in (raw, *property_aliases(raw)):
        key = normalize_item_name(name)
        if key and (
            ("item", key) in index.name_index
            or ("item", key) in index.alias_index
        ):
            return True
    return False


def _duplicate_conflict(reason: str | None) -> bool:
    """Known term with several business entries sharing the same name/symbol.

    The matcher must not pick one silently; these are counted separately from
    matcher misses so the dictionary owner can clean them up.
    """

    text = reason or ""
    return "同名/同符号" in text or "同名多条" in text


def _method_known(raw: str, index: DictionaryIndex) -> bool:
    return any(
        standard_base(standard) in index.standard_index
        for standard in extract_standards(raw)
    )


def _skip_alignment() -> dict:
    return {
        "docs": 0,
        "category_mode": False,
        "categories_total": 0,
        "categories_matched": 0,
        "categories_new": 0,
        "categories_ambiguous": 0,
        "category_coverage": 0.0,
        "category_match_rate": 0.0,
        "known_categories_total": 0,
        "known_categories_matched": 0,
        "known_categories_conflict": 0,
        "items_total": 0,
        "items_matched": 0,
        "items_new": 0,
        "items_ambiguous": 0,
        "item_coverage": 0.0,
        "item_match_rate": 0.0,
        "known_items_total": 0,
        "known_items_matched": 0,
        "known_items_conflict": 0,
        "properties_total": 0,
        "properties_matched": 0,
        "properties_new": 0,
        "properties_ambiguous": 0,
        "property_coverage": 0.0,
        "property_match_rate": 0.0,
        "known_properties_total": 0,
        "known_properties_matched": 0,
        "known_properties_conflict": 0,
        "methods_total": 0,
        "methods_matched": 0,
        "methods_new": 0,
        "methods_ambiguous": 0,
        "method_coverage": 0.0,
        "method_match_rate": 0.0,
        "known_methods_total": 0,
        "known_methods_matched": 0,
        "known_methods_conflict": 0,
        "new_terms": 0,
        "new_categories": 0,
        "new_items": 0,
        "new_methods": 0,
        "per_doc": [],
        "skipped": True,
    }


def _checks(validation: dict, alignment: dict, args) -> list[dict]:
    checks = [
        _check(
            "dictionary_reachable",
            validation["entries_total"] > 0,
            f"{validation['entries_total']} entries",
        ),
        _check(
            "dictionary_schema",
            not validation["duplicates"] and not validation["missing_names"],
            f"duplicates={len(validation['duplicates'])} "
            f"missing_names={len(validation['missing_names'])}",
        ),
        _check(
            "categories_available",
            validation["categories_total"] == 0
            or validation["active_categories"] > 0,
            f"{validation['active_categories']} active categories",
        ),
        _check(
            "items_available",
            validation["active_items"] > 0,
            f"{validation['active_items']} active items",
        ),
        _check(
            "methods_available",
            validation["active_methods"] > 0,
            f"{validation['active_methods']} active methods",
        ),
        _check(
            "dictionary_version",
            bool(validation["version"]),
            validation["version"],
        ),
        _check(
            "category_match_rate",
            alignment.get("skipped")
            or not alignment["category_mode"]
            or alignment["known_categories_total"] == 0
            or alignment["category_match_rate"] >= args.min_category_rate,
            f"{alignment['category_match_rate']:.3f} "
            f"of {alignment['known_categories_total']} known categories "
            f"(conflicts {alignment.get('known_categories_conflict', 0)}; "
            f"target {args.min_category_rate:.2f})",
        ),
        _check(
            "item_match_rate",
            alignment.get("skipped")
            or alignment["known_items_total"] == 0
            or alignment["item_match_rate"] >= args.min_item_rate,
            f"{alignment['item_match_rate']:.3f} "
            f"of {alignment['known_items_total']} known items "
            f"(conflicts {alignment.get('known_items_conflict', 0)}; "
            f"target {args.min_item_rate:.2f})",
        ),
        _check(
            "method_match_rate",
            alignment.get("skipped")
            or alignment["known_methods_total"] == 0
            or alignment["method_match_rate"] >= args.min_method_rate,
            f"{alignment['method_match_rate']:.3f} "
            f"of {alignment['known_methods_total']} known methods "
            f"(conflicts {alignment.get('known_methods_conflict', 0)}; "
            f"target {args.min_method_rate:.2f})",
        ),
    ]
    return checks


def _check(name: str, passed: bool, detail: str) -> dict:
    return {"name": name, "passed": bool(passed), "detail": detail}


def _render(report: dict) -> str:
    dictionary = report["dictionary"]
    lines = [
        "# G1.8 真实业务系统验收",
        "",
        f"- 模式：{report['mode']}",
        f"- 目标：{report['target']}",
        f"- 词典版本：{dictionary['version']}",
        f"- 条目：{dictionary['entries']} "
        f"（项目大类 {dictionary['categories']} / 检测项目 {dictionary['items']} / "
        f"试验方法 {dictionary['methods']}）",
        f"- 结论：{'PASS' if report['passed'] else 'FAIL'}",
        "",
        "## 检查项",
        "",
        "| 检查 | 结果 | 明细 |",
        "|---|---|---|",
    ]
    for check in report["checks"]:
        lines.append(
            f"| {check['name']} | {'PASS' if check['passed'] else 'FAIL'} | "
            f"{check['detail']} |"
        )
    alignment = report["alignment"]
    if not alignment.get("skipped"):
        category_mode = alignment.get("category_mode")
        lines.extend(
            [
                "",
                "## 对齐结果",
                "",
                f"- 文档：{alignment['docs']}",
                f"- 匹配率（仅统计业务词典中存在的词，冲突项单列）：",
                f"  - 项目大类：{alignment['known_categories_matched']}"
                f"/{alignment['known_categories_total']}"
                f"（{alignment['category_match_rate']:.3f}；冲突 "
                f"{alignment.get('known_categories_conflict', 0)}）",
                f"  - 检测项目：{alignment['known_properties_matched']}"
                f"/{alignment['known_properties_total']}"
                f"（{alignment['property_match_rate']:.3f}；业务数据冲突 "
                f"{alignment.get('known_properties_conflict', 0)}）",
                f"  - 试验方法：{alignment['known_methods_matched']}"
                f"/{alignment['known_methods_total']}"
                f"（{alignment['method_match_rate']:.3f}；冲突 "
                f"{alignment.get('known_methods_conflict', 0)}）",
                "",
                f"- 覆盖率（全部抽取项）：",
                f"  - 项目大类：{alignment['categories_matched']}"
                f"/{alignment['categories_total']}"
                f"（{alignment['category_coverage']:.3f}）；"
                f"new {alignment['categories_new']}；"
                f"ambiguous {alignment['categories_ambiguous']}",
                f"  - 检测项目：{alignment['properties_matched']}"
                f"/{alignment['properties_total']}"
                f"（{alignment['property_coverage']:.3f}）；"
                f"new {alignment['properties_new']}；"
                f"ambiguous {alignment['properties_ambiguous']}",
                f"  - 试验方法：{alignment['methods_matched']}"
                f"/{alignment['methods_total']}"
                f"（{alignment['method_coverage']:.3f}）；"
                f"new {alignment['methods_new']}；"
                f"ambiguous {alignment['methods_ambiguous']}",
                f"- 新词候选：{alignment['new_terms']}"
                f"（大类 {alignment['new_categories']} / "
                f"项目 {alignment['new_items']} / "
                f"方法 {alignment['new_methods']}）",
                "",
                "| 文档 | 项目大类命中 | 检测项目命中 | 方法命中 | new | ambiguous |",
                "|---|---|---|---|---|---|",
            ]
        )
        for doc in alignment["per_doc"]:
            category_cell = (
                f"{doc['categories_matched']}/{doc['categories_total']}"
                if category_mode
                else "-"
            )
            lines.append(
                f"| {doc['doc']} | {category_cell} | "
                f"{doc['properties_matched']}/{doc['properties_total']} | "
                f"{doc['methods_matched']}/{doc['methods_total']} | "
                f"{doc['new_terms']} | "
                f"{doc['categories_ambiguous'] + doc['properties_ambiguous']} |"
            )
    validation = report["validation"]
    if validation["duplicates"] or validation["missing_names"]:
        lines.extend(["", "## 数据问题", ""])
        for code in validation["duplicates"]:
            lines.append(f"- 重复编码：{code}")
        for code in validation["missing_names"]:
            lines.append(f"- 缺少名称：{code}")
    if validation.get("items_without_category"):
        lines.extend(["", f"- 未挂项目大类的检测项目：{len(validation['items_without_category'])} 条"])
    return "\n".join(lines) + "\n"


def _write_failure(out_dir: Path, args, error: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "mode": "snapshot" if args.snapshot else "http",
        "target": args.snapshot or args.base_url,
        "passed": False,
        "error": error,
    }
    (out_dir / "g1_8_live.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _known_rate(matched: float, total: float, conflict: float) -> float:
    denominator = total - conflict
    return round(matched / denominator, 4) if denominator > 0 else 0.0


def _rate(numerator: float, denominator: float) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


if __name__ == "__main__":
    raise SystemExit(main())
