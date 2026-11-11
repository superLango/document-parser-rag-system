"""Bindings-level shadow run for a candidate recipe (M2.5.3-03).

Replays the candidate over the same-family tables of a baseline corpus and
compares it with the active recipe's binding; optionally scores it against the
G1.6 column-binding gold set.

Usage:
    python -m tools.shadow_run \
      --recipe configs/recipes/candidates/candidate_mechanical_properties_66a957cb.json \
      --runs runs/m2_baseline --out eval/recipes/shadow-<id>.json
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from metal_doc_agent.contracts import Recipe, TableGrid
from metal_doc_agent.recipes import (
    GoldTable,
    evaluate_field_shadow,
    evaluate_shadow,
    load_recipes,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GOLD = ROOT / "goldset" / "column_binding" / "v0"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recipe", required=True, help="candidate recipe JSON path")
    parser.add_argument("--runs", default=str(ROOT / "runs" / "m2_baseline"))
    parser.add_argument("--gold", default=str(DEFAULT_GOLD), help="gold dir; empty to skip")
    parser.add_argument("--gold-runs", default=str(ROOT / "runs" / "m1.5_qwen"))
    parser.add_argument("--out", default="")
    parser.add_argument(
        "--record",
        action="store_true",
        help="write the run outcome into configs/recipes/registry.json stats",
    )
    args = parser.parse_args(argv)

    recipe = Recipe.model_validate_json(Path(args.recipe).read_text(encoding="utf-8"))
    tables = _load_tables(Path(args.runs), recipe.profile)
    documents = len({item[0] for item in tables})
    gold_tables = (
        _load_gold(Path(args.gold), Path(args.gold_runs)) if args.gold else []
    )
    all_recipes = load_recipes()
    report = evaluate_shadow(
        recipe,
        [item[1] for item in tables],
        recipes=all_recipes,
        gold_tables=gold_tables,
        documents=documents,
    )
    active_recipe = next(
        (
            item
            for item in all_recipes
            if item.status == "active"
            and item.profile == recipe.profile
            and item.recipe_id != recipe.recipe_id
        ),
        None,
    )
    field_report = evaluate_field_shadow(
        recipe,
        [item[1] for item in tables],
        active_recipe=active_recipe,
    )
    passed = report.passed and field_report.passed
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "recipe": str(Path(args.recipe)),
        "runs": str(Path(args.runs)),
        **report.to_dict(),
        "field_shadow": field_report.to_dict(),
        "overall_passed": passed,
    }
    out = Path(args.out or ROOT / "eval" / "recipes" / f"shadow-{recipe.recipe_id}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.record:
        from metal_doc_agent.recipes.lifecycle import RecipeRegistry

        registry = RecipeRegistry(ROOT / "configs" / "recipes" / "registry.json")
        registry.record_run(recipe.recipe_id, success=passed, source="shadow")
    print(
        f"recipe={report.recipe_id} tables={report.tables} docs={report.documents} "
        f"agreement={report.agreement:.4f} coverage={report.coverage:.4f} "
        f"orphan={report.orphan_rate:.4f} gold={report.gold_agreement} "
        f"field_agreement={field_report.agreement:.4f} "
        f"field_regressions={field_report.regressed} "
        f"core_regressions={field_report.core_regressions} passed={passed}"
    )
    print(f"out={out}")
    return 0 if passed else 1


def _load_tables(runs_dir: Path, profile: str) -> list[tuple[str, TableGrid]]:
    tables: list[tuple[str, TableGrid]] = []
    for path in sorted(runs_dir.glob("*/tablegrid/*.json")):
        table = TableGrid.model_validate_json(path.read_text(encoding="utf-8"))
        if table.profile != profile:
            continue
        tables.append((path.parents[1].name, table))
    return tables


def _load_gold(gold_dir: Path, gold_runs: Path) -> list[GoldTable]:
    manifest_path = gold_dir / "manifest.json"
    if not manifest_path.exists():
        return []
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    tables: list[GoldTable] = []
    for doc in manifest.get("docs", []):
        gold = json.loads((gold_dir / doc["file"]).read_text(encoding="utf-8"))
        source_run = gold.get("source_run") or f"runs/m1.5_qwen/{doc['doc_id']}"
        run_dir = ROOT / str(source_run)
        if not (run_dir / "tablegrid").exists():
            run_dir = gold_runs / doc["doc_id"]
        for table_id in doc.get("tables", []):
            table_path = run_dir / "tablegrid" / f"{table_id}.json"
            gold_table = (gold.get("tables") or {}).get(table_id)
            if not table_path.exists() or not gold_table:
                continue
            tables.append(
                GoldTable(
                    doc_id=doc["doc_id"],
                    table_id=table_id,
                    table=TableGrid.model_validate_json(
                        table_path.read_text(encoding="utf-8")
                    ),
                    columns=gold_table.get("columns") or {},
                )
            )
    return tables


if __name__ == "__main__":
    raise SystemExit(main())
