"""Evaluate M1.8 business-dictionary matching."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from metal_doc_agent.canonicalize import (  # noqa: E402
    DictionaryIndex,
    load_dictionary,
    match_item,
    match_method,
    match_method_cell,
)
from metal_doc_agent.contracts import ItemInventory, ItemInventoryEntry  # noqa: E402

DEFAULT_GOLD = ROOT / "goldset" / "canonical" / "v0"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gold", default=str(DEFAULT_GOLD))
    parser.add_argument("--runs", default=str(ROOT / "runs" / "m1.5_qwen"))
    parser.add_argument("--out", default=str(ROOT / "eval" / "canonical"))
    parser.add_argument("--skip-runs", action="store_true")
    args = parser.parse_args(argv)
    cases = json.loads(
        (Path(args.gold) / "cases.json").read_text(encoding="utf-8")
    )
    index = DictionaryIndex.build(load_dictionary(ROOT))
    totals: Counter = Counter()
    misses: list[dict] = []

    for case in cases["item_cases"]:
        entry = ItemInventoryEntry(
            item_raw=case["raw"],
            item_canonical=case["raw"],
            item_family=case["family"],
            facets=case.get("facets") or {},
        )
        match = match_item(entry, index)
        expected_code = case.get("expected_code")
        expected_status = case.get("expected_status", "matched")
        ok, kind = _judge(match, expected_code, expected_status)
        totals[f"item_{kind}_total"] += 1
        totals["item_total"] += 1
        totals["version_ok"] += 1 if match.dictionary_version else 0
        totals["version_total"] += 1
        if ok:
            totals[f"item_{kind}_correct"] += 1
        else:
            misses.append(
                {
                    "type": "item",
                    "raw": case["raw"],
                    "expected": expected_code or expected_status,
                    "pred": match.canonical_id or match.status,
                    "match_type": match.match_type,
                }
            )
        if expected_status == "new" and match.status == "matched":
            totals["false_merge"] += 1

    for case in cases["method_cases"]:
        match = match_method(case["raw"], index)
        expected_code = case.get("expected_code")
        expected_status = case.get("expected_status", "matched")
        ok, kind = _judge(match, expected_code, expected_status)
        totals[f"method_{kind}_total"] += 1
        totals["method_total"] += 1
        totals["version_ok"] += 1 if match.dictionary_version else 0
        totals["version_total"] += 1
        if ok:
            totals[f"method_{kind}_correct"] += 1
        else:
            misses.append(
                {
                    "type": "method",
                    "raw": case["raw"],
                    "expected": expected_code or expected_status,
                    "pred": match.canonical_id or match.status,
                    "match_type": match.match_type,
                }
            )
        if expected_status == "new" and match.status == "matched":
            totals["false_merge"] += 1

    for case in cases.get("method_cell_cases") or []:
        matches = match_method_cell(case["raw"], index)
        expected_codes = case.get("expected_codes")
        if expected_codes:
            actual = sorted(
                item.canonical_id for item in matches if item.canonical_id
            )
            ok = actual == sorted(expected_codes)
        else:
            ok = all(item.status == "new" for item in matches) if matches else True
        totals["method_cell_total"] += 1
        if ok:
            totals["method_cell_correct"] += 1
        else:
            misses.append(
                {
                    "type": "method_cell",
                    "raw": case["raw"],
                    "expected": expected_codes or "new",
                    "pred": [item.canonical_id or item.status for item in matches],
                }
            )

    runs = []
    if not args.skip_runs:
        for path in sorted(
            (Path(args.runs)).glob("*/item_inventory.json")
        ):
            inventory = ItemInventory.model_validate_json(
                path.read_text(encoding="utf-8")
            )
            item_counts = Counter()
            method_counts = Counter()
            for item in inventory.items:
                if item.status == "ambiguous":
                    continue
                match = match_item(item, index)
                item_counts[match.status] += 1
                if item.method_standard:
                    for method_match in match_method_cell(
                        item.method_standard, index
                    ):
                        method_counts[method_match.status] += 1
            runs.append(
                {
                    "doc": path.parent.name,
                    "items": dict(item_counts),
                    "methods": dict(method_counts),
                }
            )
            totals["run_items_total"] += sum(item_counts.values())
            totals["run_items_matched"] += item_counts["matched"]
            totals["run_items_new"] += item_counts["new"]
            totals["run_items_ambiguous"] += item_counts["ambiguous"]
            totals["run_methods_total"] += sum(method_counts.values())
            totals["run_methods_matched"] += method_counts["matched"]
            totals["run_methods_new"] += method_counts["new"]

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "eval.json").write_text(
        json.dumps(
            {"totals": dict(totals), "misses": misses, "runs": runs},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    _write_report(out_dir, totals, misses, runs)
    print(
        "item_known={:.3f} item_ambiguous={:.3f} item_new={:.3f} "
        "method_known={:.3f} method_new={:.3f} false_merge={} run_item={:.3f}".format(
            _ratio(totals["item_known_correct"], totals["item_known_total"]),
            _ratio(totals["item_ambiguous_correct"], totals["item_ambiguous_total"]),
            _ratio(totals["item_new_correct"], totals["item_new_total"]),
            _ratio(totals["method_known_correct"], totals["method_known_total"]),
            _ratio(totals["method_new_correct"], totals["method_new_total"]),
            totals["false_merge"],
            _ratio(totals["run_items_matched"], totals["run_items_total"]),
        )
    )
    print(f"out={out_dir}")
    return 0


def _judge(match, expected_code: str | None, expected_status: str) -> tuple[bool, str]:
    if expected_code:
        return (
            match.status == "matched" and match.canonical_id == expected_code,
            "known",
        )
    if expected_status == "ambiguous":
        return match.status == "ambiguous", "ambiguous"
    if expected_status == "new":
        return match.status == "new", "new"
    return False, "known"


def _write_report(out_dir: Path, totals: Counter, misses: list[dict], runs: list[dict]) -> None:
    lines = [
        "# 业务主数据对齐评测（M1.8 / G1.8）",
        "",
        f"- 已知项目匹配率：{_ratio(totals['item_known_correct'], totals['item_known_total']):.3f}"
        f"（{totals['item_known_correct']}/{totals['item_known_total']}）",
        f"- 项目歧义识别：{_ratio(totals['item_ambiguous_correct'], totals['item_ambiguous_total']):.3f}"
        f"（{totals['item_ambiguous_correct']}/{totals['item_ambiguous_total']}）",
        f"- new 项目标记：{_ratio(totals['item_new_correct'], totals['item_new_total']):.3f}"
        f"（{totals['item_new_correct']}/{totals['item_new_total']}）",
        f"- 已知方法匹配率：{_ratio(totals['method_known_correct'], totals['method_known_total']):.3f}"
        f"（{totals['method_known_correct']}/{totals['method_known_total']}）",
        f"- new 方法标记：{_ratio(totals['method_new_correct'], totals['method_new_total']):.3f}"
        f"（{totals['method_new_correct']}/{totals['method_new_total']}）",
        f"- 多标准单元格：{_ratio(totals['method_cell_correct'], totals['method_cell_total']):.3f}"
        f"（{totals['method_cell_correct']}/{totals['method_cell_total']}）",
        f"- 误合并：{totals['false_merge']}",
        f"- dictionary_version 记录率：{_ratio(totals['version_ok'], totals['version_total']):.3f}"
        f"（{totals['version_ok']}/{totals['version_total']}）",
        "",
        "## 真实项目清单覆盖（20 文档）",
        "",
        f"- 业务词典命中：{_ratio(totals['run_items_matched'], totals['run_items_total']):.3f}"
        f"（{totals['run_items_matched']}/{totals['run_items_total']}）",
        f"- new：{totals['run_items_new']}；ambiguous：{totals['run_items_ambiguous']}",
        f"- 方法命中：{_ratio(totals['run_methods_matched'], totals['run_methods_total']):.3f}"
        f"（{totals['run_methods_matched']}/{totals['run_methods_total']}）；"
        f"new {totals['run_methods_new']}",
        "",
        "## 未命中",
        "",
        "| 类型 | raw | 期望 | 预测 | match_type |",
        "|---|---|---|---|---|",
    ]
    for miss in misses[:100]:
        lines.append(
            f"| {miss['type']} | {miss['raw']} | {miss['expected']} | "
            f"{miss['pred']} | {miss.get('match_type', '')} |"
        )
    if runs:
        lines.extend(
            [
                "",
                "## 分文档",
                "",
                "| 文档 | 项目命中 | 项目 new | 项目歧义 | 方法命中 | 方法 new |",
                "|---|---|---|---|---|---|",
            ]
        )
        for run in runs:
            items = run["items"]
            methods = run["methods"]
            lines.append(
                f"| {run['doc']} | {items.get('matched', 0)} | "
                f"{items.get('new', 0)} | {items.get('ambiguous', 0)} | "
                f"{methods.get('matched', 0)} | {methods.get('new', 0)} |"
            )
    (out_dir / "eval.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


if __name__ == "__main__":
    raise SystemExit(main())
