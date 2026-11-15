"""Recipe governance migration: one test per version, full digest, candidate cleanup.

Usage:
    python scripts/recipes/govern_recipes.py            # dry run
    python scripts/recipes/govern_recipes.py --apply    # write manifests
    python scripts/recipes/govern_recipes.py --apply --archive-stale
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from services.recipe_registry.package import (  # noqa: E402
    RecipeManifest,
    dump_manifest,
    validate_manifest,
)
from services.recipe_registry.registry import RecipeRegistry  # noqa: E402

SHARED_TEST = "tests/contract/recipes/test_recipe_contract.py::test_recipe_manifest_contract"


def _manifest_paths(root: Path) -> list[Path]:
    return sorted(root.glob("*/*/manifest.json"))


def migrate_manifests(root: Path, *, apply: bool) -> tuple[int, int]:
    updated = 0
    total = 0
    for path in _manifest_paths(root):
        total += 1
        payload = json.loads(path.read_text(encoding="utf-8"))
        tests = list(payload.get("tests") or [])
        if SHARED_TEST not in tests:
            tests.append(SHARED_TEST)
        payload["tests"] = tests
        payload["checksum"] = ""
        manifest = validate_manifest(RecipeManifest.model_validate(payload))
        if manifest.checksum != json.loads(path.read_text(encoding="utf-8")).get("checksum"):
            updated += 1
            if apply:
                path.write_text(dump_manifest(manifest), encoding="utf-8")
    return total, updated


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--archive-stale", action="store_true")
    parser.add_argument("--actor", default="governance")
    parser.add_argument(
        "--root",
        default=str(ROOT / "services/recipe_registry/data/recipes"),
    )
    args = parser.parse_args()
    root = Path(args.root)
    total, updated = migrate_manifests(root, apply=args.apply)
    print(f"manifests={total} updated={updated} applied={args.apply}")

    if args.archive_stale and args.apply:
        registry = RecipeRegistry(root)
        for recipe in registry.list_recipes():
            moved = registry.archive_stale_candidates(
                recipe["recipe_id"], actor=args.actor
            )
            if moved:
                print(f"archived {recipe['recipe_id']}: {len(moved)} version(s)")

    registry = RecipeRegistry(root)
    issues = registry.governance()
    print(f"governance_issues={len(issues)}")
    for issue in issues[:30]:
        print(json.dumps(issue, ensure_ascii=False))
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
