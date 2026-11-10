"""Evaluate ItemInventory against the G1.7 gold set."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from metal_doc_agent.contracts import ItemInventory  # noqa: E402
from metal_doc_agent.items.taxonomy import (  # noqa: E402
    IDENTITY_FACETS_BY_FAMILY,
    classify_item,
    normalize_item,
)

DEFAULT_GOLD = ROOT / "goldset" / "item_inventory" / "v0"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gold", default=str(DEFAULT_GOLD))
    parser.add_argument("--runs", default=str(ROOT / "runs" / "m1.5_qwen"))
    parser.add_argument("--out", default=str(ROOT / "eval" / "item_inventory"))
    args = parser.parse_args(argv)
    gold_dir = Path(args.gold)
    manifest = json.loads((gold_dir / "manifest.json").read_text(encoding="utf-8"))

    totals: Counter = Counter()
    details: list[dict] = []
    missing: list[dict] = []
    extra: list[dict] = []
    facet_misses: list[dict] = []
    for doc in manifest["docs"]:
        gold = json.loads((gold_dir / doc["file"]).read_text(encoding="utf-8"))
        run_dir = Path(args.runs) / doc.get("run", doc["doc_id"])
        inventory = ItemInventory.model_validate_json(
            (run_dir / "item_inventory.json").read_text(encoding="utf-8")
        )
        doc_stats: Counter = Counter()
        allowed_unknown = set(gold.get("unknown_ok") or [])
        gold_items = [item for item in gold["items"] if item.get("required", True)]
        pred_items = list(inventory.items)
        pred_keys: dict[tuple, object] = {}
        for item in pred_items:
            pred_keys.setdefault(_item_key(item), item)

        matched_pred: set[int] = set()
        for gold_item in gold_items:
            key = _gold_key(gold_item)
            doc_stats["gold"] += 1
            totals["gold"] += 1
            pred = pred_keys.get(key)
            if pred is None:
                doc_stats["missing"] += 1
                totals["missing"] += 1
                missing.append({"doc": doc["doc_id"], "gold": gold_item})
                continue
            doc_stats["matched"] += 1
            totals["matched"] += 1
            matched_pred.add(id(pred))
            for facet, value in (gold_item.get("facets") or {}).items():
                doc_stats["facet_total"] += 1
                totals["facet_total"] += 1
                if pred.facets.get(facet) == value:
                    doc_stats["facet_correct"] += 1
                    totals["facet_correct"] += 1
                else:
                    facet_misses.append(
                        {
                            "doc": doc["doc_id"],
                            "canonical": gold_item["item_canonical"],
                            "facet": facet,
                            "gold": value,
                            "pred": pred.facets.get(facet),
                        }
                    )
            if pred.evidence:
                doc_stats["evidence"] += 1
                totals["evidence"] += 1

        for pred in pred_items:
            if id(pred) in matched_pred:
                continue
            doc_stats["extra"] += 1
            totals["extra"] += 1
            extra.append(
                {
                    "doc": doc["doc_id"],
                    "item": pred.item_canonical,
                    "family": pred.item_family,
                    "facets": pred.facets,
                    "source": pred.source,
                }
            )

        for candidate in inventory.unknown_candidates:
            raw = str(candidate.get("raw", ""))
            family, _ = classify_item(raw)
            if family == "unknown" and raw not in allowed_unknown:
                doc_stats["unexpected_unknown"] += 1
                totals["unexpected_unknown"] += 1

        coverage = inventory.coverage or {}
        if coverage.get("measure_columns_total"):
            doc_stats["coverage_total"] += 1
            doc_stats["coverage_sum"] += float(
                coverage.get("measure_column_coverage", 0.0)
            )
            totals["coverage_total"] += 1
            totals["coverage_sum"] += float(
                coverage.get("measure_column_coverage", 0.0)
            )
        doc_stats["predicted"] += len(pred_items)
        totals["predicted"] += len(pred_items)
        details.append({"doc_id": doc["doc_id"], "stats": dict(doc_stats)})

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "eval.json").write_text(
        json.dumps(
            {
                "totals": dict(totals),
                "docs": details,
                "missing": missing,
                "extra": extra,
                "facet_misses": facet_misses,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    recall = _ratio(totals["matched"], totals["gold"])
    precision = _ratio(totals["matched"], totals["predicted"])
    facet = _ratio(totals["facet_correct"], totals["facet_total"])
    coverage = _ratio(totals["coverage_sum"], totals["coverage_total"])
    unknown_rate = _ratio(totals["unexpected_unknown"], totals["predicted"])
    lines = [
        "# 项目清单评测（G1.7）",
        "",
        "- 文档数：{}".format(len(details))
        + "".join(f"（{item['doc_id']}）" for item in details),
        "- 金标项目：{}".format(totals["gold"]),
        "- 预测项目：{}".format(totals["predicted"]),
        "- 项目召回：{:.3f}（{}/{}）".format(
            recall, totals["matched"], totals["gold"]
        ),
        "- 项目精确：{:.3f}（{}/{}）".format(
            precision, totals["matched"], totals["predicted"]
        ),
        "- 细分准确率：{:.3f}（{}/{}）".format(
            facet, totals["facet_correct"], totals["facet_total"]
        ),
        "- 证据覆盖：{:.3f}（{}/{}）".format(
            _ratio(totals["evidence"], totals["matched"]),
            totals["evidence"],
            totals["matched"],
        ),
        "- 测量列覆盖：{:.3f}".format(coverage),
        "- 非预期未知候选：{}（{:.3f}）".format(
            totals["unexpected_unknown"], unknown_rate
        ),
        "- 缺失：{} / 多出：{}".format(totals["missing"], totals["extra"]),
        "",
        "## 分文档",
        "",
        "| 文档 | 金标 | 预测 | 命中 | 缺失 | 多出 | 细分 | 覆盖 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for item in details:
        stats = item["stats"]
        doc_coverage = (
            stats["coverage_sum"] / stats["coverage_total"]
            if stats.get("coverage_total")
            else None
        )
        lines.append(
            f"| {item['doc_id']} | {stats.get('gold', 0)} | "
            f"{stats.get('predicted', 0)} | {stats.get('matched', 0)} | "
            f"{stats.get('missing', 0)} | {stats.get('extra', 0)} | "
            f"{_ratio_text(stats.get('facet_correct', 0), stats.get('facet_total', 0))} | "
            f"{'%.3f' % doc_coverage if doc_coverage is not None else '-'} |"
        )
    lines.extend(
        [
            "",
            "## 缺失项目",
            "",
            "| 文档 | 规范名 | family | facets |",
            "|---|---|---|---|",
        ]
    )
    for item in missing:
        gold_item = item["gold"]
        lines.append(
            f"| {item['doc']} | {gold_item['item_canonical']} | "
            f"{gold_item['item_family']} | "
            f"`{json.dumps(gold_item.get('facets') or {}, ensure_ascii=False)}` |"
        )
    lines.extend(
        [
            "",
            "## 多出项目",
            "",
            "| 文档 | 规范名 | family | facets | 来源 |",
            "|---|---|---|---|---|",
        ]
    )
    for item in extra:
        lines.append(
            f"| {item['doc']} | {item['item']} | {item['family']} | "
            f"`{json.dumps(item['facets'], ensure_ascii=False)}` | {item['source']} |"
        )
    lines.extend(
        [
            "",
            "## 细分错误",
            "",
            "| 文档 | 项目 | facet | gold | pred |",
            "|---|---|---|---|---|",
        ]
    )
    for item in facet_misses:
        lines.append(
            f"| {item['doc']} | {item['canonical']} | {item['facet']} | "
            f"{item['gold']} | {item['pred']} |"
        )
    (out_dir / "eval.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(
        f"docs={len(details)} recall={recall:.3f} precision={precision:.3f} "
        f"facet={facet:.3f} coverage={coverage:.3f} "
        f"unknown={totals['unexpected_unknown']}"
    )
    print(f"out={out_dir}")
    return 0


def _item_key(item) -> tuple:
    dims = IDENTITY_FACETS_BY_FAMILY.get(item.item_family, ())
    facets = tuple(
        sorted(
            (key, item.facets[key])
            for key in dims
            if item.facets.get(key)
        )
    )
    return (
        normalize_item(item.item_canonical or item.item_raw),
        item.item_family,
        facets,
    )


def _gold_key(item: dict) -> tuple:
    family = item["item_family"]
    dims = IDENTITY_FACETS_BY_FAMILY.get(family, ())
    facets = item.get("facets") or {}
    return (
        normalize_item(item["item_canonical"]),
        family,
        tuple(sorted((key, facets[key]) for key in dims if facets.get(key))),
    )


def _ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def _ratio_text(numerator: int, denominator: int) -> str:
    return f"{numerator / denominator:.3f}" if denominator else "-"


if __name__ == "__main__":
    raise SystemExit(main())
