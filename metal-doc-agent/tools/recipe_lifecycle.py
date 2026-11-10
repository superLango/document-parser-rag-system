"""Recipe lifecycle operations: levels, promote, rollback, deprecate (M2.5.3).

Usage:
    python -m tools.recipe_lifecycle levels
    python -m tools.recipe_lifecycle promote <recipe_id> L3 --actor zhang --evidence shadow.json
    python -m tools.recipe_lifecycle promote <recipe_id> L4 --actor zhang \
        --evidence approval.json
    python -m tools.recipe_lifecycle rollback <recipe_id> --actor ops
    python -m tools.recipe_lifecycle deprecate <recipe_id> --actor ops --note "GB/T 换版"
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from metal_doc_agent.recipes import LifecycleError, RecipeRegistry, load_recipes

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "configs" / "recipes" / "registry.json"
RECIPE_DIR = ROOT / "configs" / "recipes"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", default=str(REGISTRY_PATH))
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("levels", help="show derived and registered levels")

    promote = sub.add_parser("promote", help="promote a recipe")
    promote.add_argument("recipe_id")
    promote.add_argument("level", choices=("L1", "L2", "L3", "L4", "L5"))
    promote.add_argument("--actor", required=True)
    promote.add_argument("--note", default="")
    promote.add_argument("--evidence", default="", help="JSON file with gate evidence")
    promote.add_argument("--force", action="store_true")

    rollback = sub.add_parser("rollback", help="restore a previous level")
    rollback.add_argument("recipe_id")
    rollback.add_argument("--actor", required=True)
    rollback.add_argument("--to", default="")
    rollback.add_argument("--note", default="")

    deprecate = sub.add_parser("deprecate", help="mark a recipe L5")
    deprecate.add_argument("recipe_id")
    deprecate.add_argument("--actor", required=True)
    deprecate.add_argument("--note", default="")

    args = parser.parse_args(argv)
    registry = RecipeRegistry(Path(args.registry))

    try:
        if args.command == "levels":
            recipes = load_recipes(RECIPE_DIR)
            levels = registry.levels(recipes)
            for recipe_id, level in sorted(levels.items()):
                print(f"{recipe_id}\t{level}\t{registry.success_rates().get(recipe_id, '-')}")
            return 0
        if args.command == "promote":
            evidence = (
                json.loads(Path(args.evidence).read_text(encoding="utf-8"))
                if args.evidence
                else {}
            )
            entry = registry.promote(
                args.recipe_id,
                args.level,
                actor=args.actor,
                note=args.note,
                evidence=evidence,
                force=args.force,
            )
            print(f"{args.recipe_id} -> {entry['level']}")
            return 0
        if args.command == "rollback":
            entry = registry.rollback(
                args.recipe_id,
                actor=args.actor,
                to_level=args.to or None,
                note=args.note,
            )
            print(f"{args.recipe_id} rolled back to {entry['level']}")
            return 0
        entry = registry.deprecate(args.recipe_id, actor=args.actor, note=args.note)
        print(f"{args.recipe_id} -> {entry['level']}")
        return 0
    except LifecycleError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
