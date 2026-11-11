"""Canonicalize one ItemInventory run against the business dictionary."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from metal_doc_agent.canonicalize import (  # noqa: E402
    DictionaryIndex,
    JsonDictionaryAdapter,
    align_inventory,
    load_new_terms,
    merge_new_terms,
    save_new_terms,
)
from metal_doc_agent.contracts import ItemInventory, NewTermStore  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", default="runs/m1.5_qwen/gbt40303_2021")
    parser.add_argument("--out", default=None)
    parser.add_argument(
        "--dictionary",
        default="configs/business_dictionary.hanson.json",
        help="business dictionary snapshot (project-relative path)",
    )
    parser.add_argument("--terms", default=None)
    parser.add_argument("--cumulative", action="store_true")
    args = parser.parse_args(argv)
    run_dir = ROOT / args.run
    inventory = ItemInventory.model_validate_json(
        (run_dir / "item_inventory.json").read_text(encoding="utf-8")
    )
    dictionary = JsonDictionaryAdapter(
        ROOT / args.dictionary,
        ROOT / "configs" / "business_dictionary.local.json",
    ).load()
    index = DictionaryIndex.build(dictionary)
    aligned, result = align_inventory(inventory, index)
    out_dir = Path(args.out) if args.out else run_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "item_inventory_aligned.json").write_text(
        json.dumps(aligned.model_dump(mode="json"), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    (out_dir / "alignment.json").write_text(
        json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    terms_path = Path(args.terms) if args.terms else out_dir / "new_terms.json"
    existing = load_new_terms(terms_path)
    store = merge_new_terms(
        existing,
        result.new_terms,
        keep_missing=args.cumulative,
    )
    store.dictionary_version = dictionary.version
    save_new_terms(store, terms_path)
    (out_dir / "canonical_report.md").write_text(
        _report(result, store), encoding="utf-8"
    )
    summary = result.summary
    print(
        f"categories={summary['categories_total']} "
        f"matched={summary['categories_matched']} "
        f"properties={summary['properties_total']} "
        f"matched={summary['properties_matched']} "
        f"methods={summary['methods_total']} "
        f"matched={summary['methods_matched']} "
        f"new_terms={summary['new_terms']}"
    )
    print(f"out={out_dir}")
    return 0


def _report(result, store: NewTermStore) -> str:
    lines = [
        f"# 业务对齐：{result.doc_id}",
        "",
        f"- 词典版本：{result.dictionary_version}",
    ]
    for key, value in result.summary.items():
        lines.append(f"- {key}: {value}")
    lines.extend(
        [
            "",
            "## 项目大类匹配",
            "",
            "| raw | 业务编码 | 业务名称 | 类型 | 分数 | 状态 |",
            "|---|---|---|---|---|---|",
        ]
    )
    for match in result.item_matches:
        lines.append(
            f"| {match.raw} | {match.canonical_id or ''} | "
            f"{match.canonical_name or ''} | {match.match_type} | "
            f"{match.score:.3f} | {match.status} |"
        )
    if result.property_matches:
        lines.extend(
            [
                "",
                "## 检测项目匹配",
                "",
                "| raw | 业务编码 | 业务名称 | 所属大类 | 类型 | 状态 |",
                "|---|---|---|---|---|---|",
            ]
        )
        for match in result.property_matches:
            lines.append(
                f"| {match.raw} | {match.canonical_id or ''} | "
                f"{match.canonical_name or ''} | {match.category_name or ''} | "
                f"{match.match_type} | {match.status} |"
            )
    if result.method_matches:
        lines.extend(
            [
                "",
                "## 试验方法匹配",
                "",
                "| raw | 业务编码 | 业务名称 | 类型 | 状态 |",
                "|---|---|---|---|---|",
            ]
        )
        for match in result.method_matches:
            lines.append(
                f"| {match.raw} | {match.canonical_id or ''} | "
                f"{match.canonical_name or ''} | {match.match_type} | {match.status} |"
            )
    lines.extend(
        [
            "",
            "## 新词候选",
            "",
            "| 类型 | raw | family | facets | 频次 | 状态 |",
            "|---|---|---|---|---|---|",
        ]
    )
    for term in store.terms:
        lines.append(
            f"| {term.type} | {term.raw} | {term.family or ''} | "
            f"{json.dumps(term.facets, ensure_ascii=False)} | "
            f"{term.frequency} | {term.status} |"
        )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
