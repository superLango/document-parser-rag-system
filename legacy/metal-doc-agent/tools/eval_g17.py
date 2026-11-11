"""Evaluate G1.7 gold set: items, links, clauses and coverage."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from metal_doc_agent.contracts import (  # noqa: E402
    ClauseRecord,
    ItemInventory,
    TableLinkResult,
)
from metal_doc_agent.items.taxonomy import (  # noqa: E402
    IDENTITY_FACETS_BY_FAMILY,
    normalize_item,
)

DEFAULT_GOLD = ROOT / "goldset" / "g1_7" / "v0"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gold", default=str(DEFAULT_GOLD))
    parser.add_argument("--runs", default=str(ROOT / "runs" / "m1.5_qwen"))
    parser.add_argument("--out", default=str(ROOT / "eval" / "g1_7"))
    parser.add_argument("--docs", nargs="*", default=None)
    args = parser.parse_args(argv)
    gold_dir = Path(args.gold)
    manifest = json.loads((gold_dir / "manifest.json").read_text(encoding="utf-8"))

    totals: Counter = Counter()
    details: list[dict] = []
    item_missing: list[dict] = []
    item_extra: list[dict] = []
    link_misses: list[dict] = []
    clause_missing: list[dict] = []
    clause_extra: list[dict] = []
    for doc in manifest["docs"]:
        if args.docs and doc["doc_id"] not in args.docs:
            continue
        gold = json.loads((gold_dir / doc["file"]).read_text(encoding="utf-8"))
        run_dir = Path(args.runs) / doc.get("run", doc["doc_id"])
        doc_stats: Counter = Counter()
        _eval_items(
            doc, gold, run_dir, doc_stats, totals, item_missing, item_extra
        )
        _eval_links(doc, gold, run_dir, doc_stats, totals, link_misses)
        _eval_clauses(
            doc, gold, run_dir, doc_stats, totals, clause_missing, clause_extra
        )
        audit = json.loads(
            (run_dir / "coverage_audit.json").read_text(encoding="utf-8")
        )
        stats = audit["stats"]
        doc_stats["tables"] = stats.get("tables", 0)
        doc_stats["linked"] = stats.get("tables_linked", 0)
        doc_stats["orphan_tables"] = stats.get("orphan_tables", 0)
        doc_stats["mention_total"] = stats.get("clause_mentions", 0)
        doc_stats["mention_mapped"] = stats.get("clause_mentions_mapped", 0)
        if stats.get("measure_columns_total"):
            doc_stats["measure_total"] = stats["measure_columns_total"]
            doc_stats["measure_mapped"] = stats["measure_columns_mapped"]
            totals["measure_total"] += stats["measure_columns_total"]
            totals["measure_mapped"] += stats["measure_columns_mapped"]
        totals["tables"] += doc_stats["tables"]
        totals["linked"] += doc_stats["linked"]
        totals["orphan_tables"] += doc_stats["orphan_tables"]
        totals["mention_total"] += doc_stats["mention_total"]
        totals["mention_mapped"] += doc_stats["mention_mapped"]
        details.append(
            {
                "doc_id": doc["doc_id"],
                "stats": dict(doc_stats),
                "audit_status": audit.get("status"),
            }
        )

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "eval.json").write_text(
        json.dumps(
            {
                "totals": dict(totals),
                "docs": details,
                "item_missing": item_missing,
                "item_extra": item_extra,
                "link_misses": link_misses,
                "clause_missing": clause_missing,
                "clause_extra": clause_extra,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    _write_report(
        out_dir,
        details,
        totals,
        item_missing,
        item_extra,
        link_misses,
        clause_missing,
        clause_extra,
    )
    print(
        "docs={} recall={:.3f} precision={:.3f} link={:.3f} "
        "clause_f1={:.3f} measure={:.3f} mentions={:.3f} orphan={}".format(
            len(details),
            _ratio(totals["item_matched"], totals["item_gold"]),
            _ratio(totals["item_matched"], totals["item_predicted"]),
            _ratio(totals["link_correct"], totals["link_scope"]),
            _clause_f1(totals)[0],
            _ratio(totals["measure_mapped"], totals["measure_total"]),
            _ratio(totals["mention_mapped"], totals["mention_total"]),
            totals["orphan_tables"],
        )
    )
    print(f"out={out_dir}")
    return 0


def _eval_items(doc, gold, run_dir, doc_stats, totals, missing, extra) -> None:
    inventory = ItemInventory.model_validate_json(
        (run_dir / "item_inventory.json").read_text(encoding="utf-8")
    )
    gold_items = [item for item in gold.get("items") or [] if item.get("required", True)]
    pred_items = [item for item in inventory.items if item.status != "ambiguous"]
    pred_keys: dict[tuple, object] = {}
    for item in pred_items:
        pred_keys.setdefault(_pred_item_key(item), item)
    matched: set[int] = set()
    for gold_item in gold_items:
        pred = pred_keys.get(_gold_item_key(gold_item))
        doc_stats["item_gold"] += 1
        totals["item_gold"] += 1
        if pred is None:
            missing.append({"doc": doc["doc_id"], "item": gold_item})
            continue
        doc_stats["item_matched"] += 1
        totals["item_matched"] += 1
        matched.add(id(pred))
    for pred in pred_items:
        if id(pred) in matched:
            continue
        extra.append(
            {
                "doc": doc["doc_id"],
                "item": pred.item_canonical,
                "family": pred.item_family,
                "facets": pred.facets,
                "source": pred.source,
            }
        )
    doc_stats["item_predicted"] += len(pred_items)
    totals["item_predicted"] += len(pred_items)


def _eval_links(doc, gold, run_dir, doc_stats, totals, misses) -> None:
    links = TableLinkResult.model_validate_json(
        (run_dir / "links.json").read_text(encoding="utf-8")
    )
    pred = {link.table_id: link for link in links.links}
    for table_id in gold.get("link_scope") or []:
        expected = (gold.get("links") or {}).get(table_id, {}).get("clause_id")
        doc_stats["link_scope"] += 1
        totals["link_scope"] += 1
        actual = pred.get(table_id)
        if actual is not None and _link_related(expected, actual.clause_id):
            doc_stats["link_correct"] += 1
            totals["link_correct"] += 1
        else:
            misses.append(
                {
                    "doc": doc["doc_id"],
                    "table": table_id,
                    "gold": expected,
                    "pred": actual.clause_id if actual else None,
                    "basis": actual.basis if actual else None,
                }
            )


def _link_related(gold: str | None, predicted: str | None) -> bool:
    if not gold or not predicted:
        return False
    if gold == predicted:
        return True
    if predicted.startswith(gold + ".") or gold.startswith(predicted + "."):
        return True
    if gold.startswith("附录") and predicted.startswith(gold[-1] + "."):
        return True
    if predicted.startswith("附录") and gold.startswith(predicted[-1] + "."):
        return True
    return False


def _eval_clauses(doc, gold, run_dir, doc_stats, totals, missing, extra) -> None:
    path = run_dir / "clauses.jsonl"
    clauses = [
        ClauseRecord.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    pred = {}
    for clause in clauses:
        pred.setdefault(clause.clause_id, clause)
    gold_clauses = {
        clause["clause_id"]: clause for clause in gold.get("clauses") or []
    }
    gold_ids = sorted(
        gold_clauses, key=lambda clause_id: clause_id.count("."), reverse=True
    )
    covered: set[str] = set()
    true_positives = 0
    false_positives = 0
    for clause_id, clause in pred.items():
        matched_gold = _gold_ancestor(clause_id, gold_ids)
        if matched_gold is None:
            false_positives += 1
            extra.append(
                {
                    "doc": doc["doc_id"],
                    "clause": clause_id,
                    "title": clause.title,
                    "kind": clause.kind,
                }
            )
            continue
        true_positives += 1
        for gold_id in gold_ids:
            if gold_id == matched_gold or _is_ancestor(gold_id, matched_gold):
                covered.add(gold_id)
        doc_stats["kind_total"] += 1
        totals["kind_total"] += 1
        if clause.kind == gold_clauses[matched_gold].get("kind"):
            doc_stats["kind_correct"] += 1
            totals["kind_correct"] += 1
    for clause_id, gold_clause in gold_clauses.items():
        doc_stats["clause_gold"] += 1
        totals["clause_gold"] += 1
        if clause_id not in covered:
            missing.append({"doc": doc["doc_id"], "clause": gold_clause})
    doc_stats["clause_matched"] += true_positives
    totals["clause_matched"] += true_positives
    doc_stats["clause_covered"] += len(covered)
    totals["clause_covered"] += len(covered)
    doc_stats["clause_fp"] += false_positives
    totals["clause_fp"] += false_positives
    doc_stats["clause_predicted"] += len(pred)
    totals["clause_predicted"] += len(pred)


def _gold_ancestor(clause_id: str, gold_ids: list[str]) -> str | None:
    for gold_id in gold_ids:
        if gold_id == clause_id or _is_ancestor(gold_id, clause_id):
            return gold_id
    return None


def _is_ancestor(ancestor: str, clause_id: str) -> bool:
    if clause_id.startswith(ancestor + "."):
        return True
    return ancestor.startswith("附录") and clause_id.startswith(ancestor[-1] + ".")


def _pred_item_key(item) -> tuple:
    dims = IDENTITY_FACETS_BY_FAMILY.get(item.item_family, ())
    facets = tuple(
        sorted((key, item.facets[key]) for key in dims if item.facets.get(key))
    )
    return (normalize_item(item.item_canonical or item.item_raw), item.item_family, facets)


def _gold_item_key(item: dict) -> tuple:
    family = item["item_family"]
    dims = IDENTITY_FACETS_BY_FAMILY.get(family, ())
    facets = item.get("facets") or {}
    return (
        normalize_item(item["item_canonical"]),
        family,
        tuple(sorted((key, facets[key]) for key in dims if facets.get(key))),
    )


def _write_report(
    out_dir,
    details,
    totals,
    item_missing,
    item_extra,
    link_misses,
    clause_missing,
    clause_extra,
) -> None:
    recall = _ratio(totals["item_matched"], totals["item_gold"])
    precision = _ratio(totals["item_matched"], totals["item_predicted"])
    link = _ratio(totals["link_correct"], totals["link_scope"])
    clause_f1, clause_precision, clause_recall = _clause_f1(totals)
    lines = [
        "# G1.7 评测（20 份金标）",
        "",
        "> 金标口径：qdu302/gbt40303/gbt3880/jx25/gjb2057a 为人工核验；其余 15 份为规则播种 + 原文 quote 校验。"
        "条款金标仅覆盖 schema 相关条款，条款 F1 的 precision 受标注范围影响。",
        "",
        f"- 文档数：{len(details)}",
        f"- 项目：召回 {recall:.3f}（{totals['item_matched']}/{totals['item_gold']}），"
        f"精确 {precision:.3f}（{totals['item_matched']}/{totals['item_predicted']}）",
        f"- 表-条款链接：{link:.3f}（{totals['link_correct']}/{totals['link_scope']}）",
        f"- 条款：F1 {clause_f1:.3f}（P {clause_precision:.3f}，R {clause_recall:.3f}；"
        f"覆盖 {totals['clause_covered']}/{totals['clause_gold']} 个金标条款，"
        f"命中预测 {totals['clause_matched']}，越界预测 {totals['clause_fp']}）",
        f"- 条款 kind 准确率：{_ratio(totals['kind_correct'], totals['kind_total']):.3f}"
        f"（{totals['kind_correct']}/{totals['kind_total']}）",
        f"- measure 列覆盖：{_ratio(totals['measure_mapped'], totals['measure_total']):.3f}"
        f"（{totals['measure_mapped']}/{totals['measure_total']}）",
        f"- 条款提及映射：{_ratio(totals['mention_mapped'], totals['mention_total']):.3f}"
        f"（{totals['mention_mapped']}/{totals['mention_total']}）",
        f"- 表链接率：{_ratio(totals['linked'], totals['tables']):.3f}"
        f"（{totals['linked']}/{totals['tables']}）；孤儿表 {totals['orphan_tables']}",
        "",
        "## 分文档",
        "",
        "| 文档 | 项目召回 | 项目精确 | 链接 | 条款 F1 | measure | 提及 | 审计 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for detail in details:
        stats = detail["stats"]
        lines.append(
            f"| {detail['doc_id']} | "
            f"{_ratio_text(stats.get('item_matched', 0), stats.get('item_gold', 0))} | "
            f"{_ratio_text(stats.get('item_matched', 0), stats.get('item_predicted', 0))} | "
            f"{_ratio_text(stats.get('link_correct', 0), stats.get('link_scope', 0))} | "
            f"{_clause_f1_text(stats)} | "
            f"{_ratio_text(stats.get('measure_mapped', 0), stats.get('measure_total', 0))} | "
            f"{_ratio_text(stats.get('mention_mapped', 0), stats.get('mention_total', 0))} | "
            f"{detail['audit_status']} |"
        )
    lines.extend(
        [
            "",
            "## 项目缺失（前 100）",
            "",
            "| 文档 | 项目 | family | facets |",
            "|---|---|---|---|",
        ]
    )
    for item in item_missing[:100]:
        gold_item = item["item"]
        lines.append(
            f"| {item['doc']} | {gold_item['item_canonical']} | "
            f"{gold_item['item_family']} | "
            f"`{json.dumps(gold_item.get('facets') or {}, ensure_ascii=False)}` |"
        )
    lines.extend(
        [
            "",
            "## 项目多出（前 100）",
            "",
            "| 文档 | 项目 | family | facets | 来源 |",
            "|---|---|---|---|---|",
        ]
    )
    for item in item_extra[:100]:
        lines.append(
            f"| {item['doc']} | {item['item']} | {item['family']} | "
            f"`{json.dumps(item['facets'], ensure_ascii=False)}` | {item['source']} |"
        )
    lines.extend(
        [
            "",
            "## 链接未命中",
            "",
            "| 文档 | 表 | gold | pred | 依据 |",
            "|---|---|---|---|---|",
        ]
    )
    for item in link_misses:
        lines.append(
            f"| {item['doc']} | {item['table']} | {item['gold']} | "
            f"{item['pred']} | {item['basis'] or ''} |"
        )
    lines.extend(
        [
            "",
            "## 条款缺失（前 100）",
            "",
            "| 文档 | 条款 | kind |",
            "|---|---|---|",
        ]
    )
    for item in clause_missing[:100]:
        lines.append(
            f"| {item['doc']} | {item['clause']['clause_id']} | "
            f"{item['clause'].get('kind')} |"
        )
    lines.extend(
        [
            "",
            "## 条款多出（前 100）",
            "",
            "| 文档 | 条款 | kind | 标题 |",
            "|---|---|---|---|",
        ]
    )
    for item in clause_extra[:100]:
        lines.append(
            f"| {item['doc']} | {item['clause']} | {item['kind']} | {item['title'] or ''} |"
        )
    (out_dir / "eval.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def _ratio_text(numerator: int, denominator: int) -> str:
    return f"{numerator / denominator:.3f}" if denominator else "-"


def _clause_f1(totals: Counter) -> tuple[float, float, float]:
    precision = _ratio(
        totals["clause_matched"],
        totals["clause_matched"] + totals["clause_fp"],
    )
    recall = _ratio(totals["clause_covered"], totals["clause_gold"])
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision + recall
        else 0.0
    )
    return f1, precision, recall


def _clause_f1_text(stats: dict) -> str:
    price = _ratio(
        stats.get("clause_matched", 0),
        stats.get("clause_matched", 0) + stats.get("clause_fp", 0),
    )
    recall = _ratio(stats.get("clause_covered", 0), stats.get("clause_gold", 0))
    if price + recall == 0:
        return "-"
    return f"{2 * price * recall / (price + recall):.3f}"


if __name__ == "__main__":
    raise SystemExit(main())
