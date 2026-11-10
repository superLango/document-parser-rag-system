"""Evaluate column binding against the G1.6 gold set."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from metal_doc_agent.contracts import TableGrid  # noqa: E402
from metal_doc_agent.recipes import (  # noqa: E402
    bind_columns,
    load_aliases,
    load_recipes,
    match_recipe,
)

DEFAULT_GOLD = ROOT / "goldset" / "column_binding" / "v0"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gold", default=str(DEFAULT_GOLD))
    parser.add_argument("--runs", default=str(ROOT / "runs" / "m1.5_qwen"))
    parser.add_argument("--out", default=str(ROOT / "eval" / "column_binding"))
    args = parser.parse_args(argv)
    gold_dir = Path(args.gold)
    manifest = json.loads((gold_dir / "manifest.json").read_text(encoding="utf-8"))
    recipes = load_recipes()
    aliases = load_aliases()

    totals = Counter()
    details: list[dict] = []
    mismatches: list[dict] = []
    for doc in manifest["docs"]:
        gold = json.loads((gold_dir / doc["file"]).read_text(encoding="utf-8"))
        run_dir = Path(args.runs) / doc["doc_id"] / "tablegrid"
        doc_stats = Counter()
        for table_id in doc["tables"]:
            table_path = run_dir / f"{table_id}.json"
            if not table_path.exists():
                continue
            table = TableGrid.model_validate_json(table_path.read_text(encoding="utf-8"))
            match = match_recipe(table, recipes)
            bound = bind_columns(
                table,
                recipe=match.recipe,
                aliases=aliases,
                match_status=match.status,
            )
            gold_table = gold["tables"][table_id]
            expected_recipe = gold_table.get("expected_recipe")
            if expected_recipe is not None:
                doc_stats["recipe_total"] += 1
                totals["recipe_total"] += 1
                if bound.recipe_id == expected_recipe:
                    doc_stats["recipe_hit"] += 1
                    totals["recipe_hit"] += 1
            table_ok = True
            for column_str, expected in gold_table["columns"].items():
                column = int(column_str)
                if column >= len(bound.bindings):
                    continue
                pred = bound.bindings[column]
                role_ok = _role_ok(pred, expected)
                doc_stats["role_total"] += 1
                totals["role_total"] += 1
                if role_ok:
                    doc_stats["role_correct"] += 1
                    totals["role_correct"] += 1
                else:
                    table_ok = False
                    mismatches.append(
                        {
                            "doc": doc["doc_id"],
                            "table": table_id,
                            "column": column,
                            "gold": expected,
                            "pred": {
                                "role": pred.role,
                                "family": pred.item_family,
                                "property": pred.property,
                                "status": pred.status,
                                "facets": pred.facets,
                            },
                        }
                    )
                if expected.get("role") == "measure":
                    if expected.get("family"):
                        doc_stats["family_total"] += 1
                        totals["family_total"] += 1
                        if pred.item_family == expected["family"]:
                            doc_stats["family_correct"] += 1
                            totals["family_correct"] += 1
                        else:
                            table_ok = False
                    if expected.get("property"):
                        doc_stats["property_total"] += 1
                        totals["property_total"] += 1
                        if pred.property == expected["property"]:
                            doc_stats["property_correct"] += 1
                            totals["property_correct"] += 1
                        else:
                            table_ok = False
                    for key, value in (expected.get("facets") or {}).items():
                        doc_stats["facet_total"] += 1
                        totals["facet_total"] += 1
                        if pred.facets.get(key) == value:
                            doc_stats["facet_correct"] += 1
                            totals["facet_correct"] += 1
                        else:
                            table_ok = False
                if pred.status == "unmapped" and expected.get("status") != "unmapped":
                    doc_stats["unexpected_unmapped"] += 1
                    totals["unexpected_unmapped"] += 1
            doc_stats["tables"] += 1
            totals["tables"] += 1
            if table_ok:
                doc_stats["table_exact"] += 1
                totals["table_exact"] += 1
            doc_stats["ambiguous"] += len(bound.ambiguous)
            doc_stats["unmapped"] += len(bound.unmapped_columns)
        details.append({"doc_id": doc["doc_id"], "stats": dict(doc_stats)})

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "eval.json").write_text(
        json.dumps(
            {"totals": dict(totals), "docs": details, "mismatches": mismatches},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    lines = [
        "# 列绑定评测（G1.6）",
        "",
        "- 文档数：{}".format(len(details)),
        "- 表数：{}".format(totals["tables"]),
        "- 角色准确率：{:.3f}（{}/{}）".format(
            _ratio(totals["role_correct"], totals["role_total"]),
            totals["role_correct"],
            totals["role_total"],
        ),
        "- 属性准确率：{:.3f}（{}/{}）".format(
            _ratio(totals["property_correct"], totals["property_total"]),
            totals["property_correct"],
            totals["property_total"],
        ),
        "- family 准确率：{:.3f}（{}/{}）".format(
            _ratio(totals["family_correct"], totals["family_total"]),
            totals["family_correct"],
            totals["family_total"],
        ),
        "- facet 准确率：{:.3f}（{}/{}）".format(
            _ratio(totals["facet_correct"], totals["facet_total"]),
            totals["facet_correct"],
            totals["facet_total"],
        ),
        "- 配方命中：{:.3f}（{}/{}）".format(
            _ratio(totals["recipe_hit"], totals["recipe_total"]),
            totals["recipe_hit"],
            totals["recipe_total"],
        ),
        "- 整表精确：{:.3f}（{}/{}）".format(
            _ratio(totals["table_exact"], totals["tables"]),
            totals["table_exact"],
            totals["tables"],
        ),
        "- 歧义列：{}".format(totals["ambiguous"]),
        "- 未映射列：{}（非预期 {}）".format(
            totals["unmapped"], totals["unexpected_unmapped"]
        ),
        "",
        "## 分文档",
        "",
        "| 文档 | 表 | 角色 | 属性 | family | facet | 配方 | 整表 | 歧义 | 未映射 |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for item in details:
        stats = item["stats"]
        lines.append(
            f"| {item['doc_id']} | {stats.get('tables', 0)} | "
            f"{_ratio_text(stats.get('role_correct', 0), stats.get('role_total', 0))} | "
            f"{_ratio_text(stats.get('property_correct', 0), stats.get('property_total', 0))} | "
            f"{_ratio_text(stats.get('family_correct', 0), stats.get('family_total', 0))} | "
            f"{_ratio_text(stats.get('facet_correct', 0), stats.get('facet_total', 0))} | "
            f"{_ratio_text(stats.get('recipe_hit', 0), stats.get('recipe_total', 0))} | "
            f"{stats.get('table_exact', 0)}/{stats.get('tables', 0)} | "
            f"{stats.get('ambiguous', 0)} | {stats.get('unmapped', 0)} |"
        )
    lines.extend(
        [
            "",
            "## 未命中列（前 100）",
            "",
            "| 文档 | 表 | 列 | gold | pred |",
            "|---|---|---|---|---|",
        ]
    )
    for item in mismatches[:100]:
        lines.append(
            f"| {item['doc']} | {item['table']} | {item['column']} | "
            f"`{json.dumps(item['gold'], ensure_ascii=False)}` | "
            f"`{json.dumps(item['pred'], ensure_ascii=False)}` |"
        )
    (out_dir / "eval.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"tables={totals['tables']} role={_ratio(totals['role_correct'], totals['role_total']):.3f}")
    print(f"property={_ratio(totals['property_correct'], totals['property_total']):.3f}")
    print(f"out={out_dir}")
    return 0


def _role_ok(pred, expected: dict) -> bool:
    status = expected.get("status")
    if status == "ambiguous":
        return pred.status == "ambiguous"
    if status == "unmapped":
        return pred.status == "unmapped"
    return pred.role == expected.get("role")


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _ratio_text(numerator: int, denominator: int) -> str:
    return f"{numerator / denominator:.3f}" if denominator else "-"


if __name__ == "__main__":
    raise SystemExit(main())
