"""Recipe authoring pilot (M1.6-09): propose/promote candidate recipes."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from metal_doc_agent.contracts import TableGrid  # noqa: E402
from metal_doc_agent.recipes import (  # noqa: E402
    bind_columns,
    is_duplicate,
    load_aliases,
    load_recipes,
    match_recipe,
    promote_candidate,
    propose_recipe,
    save_candidate,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", default="runs/m1.5_qwen/gbt40303_2021")
    parser.add_argument("--table", default=None, help="single table id, e.g. T14")
    parser.add_argument("--recipes", default="configs/recipes")
    parser.add_argument("--out", default="configs/recipes/candidates")
    parser.add_argument("--promote", default=None, help="candidate json path")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    recipe_dir = ROOT / args.recipes
    if args.promote:
        target = promote_candidate(ROOT / args.promote, recipe_dir, force=args.force)
        print(f"promoted={target}")
        return 0

    table_dir = ROOT / args.run / "tablegrid"
    if not table_dir.exists():
        print(f"no tablegrid directory under {table_dir}")
        return 1
    recipes = load_recipes(recipe_dir)
    aliases = load_aliases(ROOT / "configs" / "column_aliases.json")
    candidates = 0
    duplicates = 0
    skipped = 0
    for path in sorted(table_dir.glob("T*.json")):
        if args.table and path.stem != args.table:
            continue
        table = TableGrid.model_validate_json(path.read_text(encoding="utf-8"))
        match = match_recipe(table, recipes)
        if match.status == "exact":
            skipped += 1
            continue
        bound = bind_columns(
            table,
            recipe=match.recipe,
            aliases=aliases,
            match_status=match.status,
        )
        try:
            candidate = propose_recipe(table, bound)
        except ValueError:
            skipped += 1
            continue
        duplicate = is_duplicate(candidate, recipes)
        if duplicate is not None:
            duplicates += 1
            print(f"{table.table_id}: duplicate of {duplicate.recipe_id}")
            continue
        saved = save_candidate(candidate, ROOT / args.out)
        candidates += 1
        print(
            f"{table.table_id}: candidate {candidate.recipe_id} -> {saved} "
            f"(measures={len(candidate.bindings.get('measures', {}))})"
        )
    print(f"candidates={candidates} duplicates={duplicates} skipped={skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
