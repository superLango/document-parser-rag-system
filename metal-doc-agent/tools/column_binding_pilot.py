"""Pilot column binding (M1.6) on an existing run's TableGrid artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from metal_doc_agent.contracts import TableGrid  # noqa: E402
from metal_doc_agent.recipes import bind_columns, load_aliases, load_recipes  # noqa: E402
from metal_doc_agent.recipes.router import match_recipe  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", default="runs/m1.5_qwen/gbt3880_1_2012")
    parser.add_argument("--recipes", default="configs/recipes")
    parser.add_argument("--aliases", default="configs/column_aliases.json")
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    run_dir = ROOT / args.run
    table_dir = run_dir / "tablegrid"
    if not table_dir.exists():
        print(f"no tablegrid directory under {run_dir}")
        return 1
    recipes = load_recipes(ROOT / args.recipes)
    aliases = load_aliases(ROOT / args.aliases)
    results = []
    for path in sorted(table_dir.glob("T*.json")):
        table = TableGrid.model_validate_json(path.read_text(encoding="utf-8"))
        match = match_recipe(table, recipes)
        result = bind_columns(
            table,
            recipe=match.recipe,
            aliases=aliases,
            match_status=match.status,
        )
        payload = result.model_dump(mode="json")
        payload["source_file"] = path.name
        payload["recipe_score"] = match.score
        payload["profile"] = table.profile
        payload["orientation"] = table.orientation
        payload["caption"] = table.caption
        results.append(payload)

    out_dir = Path(args.out) if args.out else run_dir
    (out_dir / "column_bindings.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    match_counts = Counter(item["match_status"] for item in results)
    family_counts = Counter()
    for item in results:
        for group in item["item_groups"]:
            family_counts[group["item_family"]] += 1
    lines = [
        "# 列绑定试点报告（M1.6）",
        "",
        f"- 表数：{len(results)}",
        f"- 配方匹配：{dict(match_counts)}",
        f"- 项目组：{dict(family_counts)}",
        f"- 冲突列：{sum(len(item['conflicts']) for item in results)}",
        f"- 歧义列：{sum(len(item['ambiguous']) for item in results)}",
        f"- 未映射列：{sum(len(item['unmapped_columns']) for item in results)}",
        "",
        "| 表 | profile | 配方 | 匹配 | 项目组 | 冲突 | 歧义 | 未映射 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for item in results:
        lines.append(
            f"| {item['table_id']} | {item['profile']} | {item['recipe_id'] or '-'} | "
            f"{item['match_status']} | {len(item['item_groups'])} | "
            f"{len(item['conflicts'])} | {len(item['ambiguous'])} | "
            f"{len(item['unmapped_columns'])} |"
        )
    (out_dir / "column_binding_report.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    print(f"tables={len(results)} matches={dict(match_counts)}")
    print(f"out={out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
