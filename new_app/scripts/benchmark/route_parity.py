"""Routing parity: new matcher (migrated packages) vs legacy matcher.

Run from ``new_app``:

    python scripts/benchmark/route_parity.py
"""

import json
import sys
from pathlib import Path

NEW_APP_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = NEW_APP_DIR.parent
GOLDEN_DIR = NEW_APP_DIR / "tests" / "golden" / "table"
LEGACY_ROOT = REPO_ROOT / "legacy" / "metal-doc-agent"

sys.path.insert(0, str(NEW_APP_DIR))
sys.path.append(str(LEGACY_ROOT))

from services.ocr.algorithms.table_grid import extract_tables  # noqa: E402
from services.ocr.contracts import Page  # noqa: E402
from services.recipe_registry.matcher import match_table  # noqa: E402
from services.recipe_registry.registry import RecipeRegistry  # noqa: E402


def run_new(table):
    registry = RecipeRegistry()
    return match_table(table, registry.active_manifests("stable"))


def run_legacy(table):
    from metal_doc_agent.contracts import TableBlock as LegacyTableBlock
    from metal_doc_agent.contracts import TableGrid as LegacyTableGrid
    from metal_doc_agent.recipes.router import load_recipes, match_recipe

    legacy_table = LegacyTableGrid(
        table_id=table.table_id,
        page_no=table.page_no,
        caption=table.caption,
        n_rows=table.n_rows,
        n_cols=table.n_cols,
        header_rows=table.header_rows,
        rows=table.rows,
        header_paths=table.header_paths,
        units=table.units,
        profile=table.profile,
        orientation=table.orientation,
        blocks=[
            LegacyTableBlock(
                block_id=block.block_id,
                start_row=block.start_row,
                header_rows=block.header_rows,
                header_paths=block.header_paths,
                rows=block.rows,
            )
            for block in table.blocks
        ],
    )
    return match_recipe(legacy_table, load_recipes())


def main() -> None:
    cases = sorted(GOLDEN_DIR.glob("*.md"))
    rows: list[list[str]] = []
    matches = 0
    status_matches = 0
    total = 0

    for path in cases:
        text = path.read_text(encoding="utf-8")
        tables = extract_tables([Page(page_no=1, markdown=text)])
        if not tables:
            continue
        table = tables[0]
        new = run_new(table)
        old = run_legacy(table)
        total += 1
        same_recipe = (new.recipe_id or "") == (old.recipe.recipe_id if old.recipe else "")
        same_status = new.status == old.status
        matches += int(same_recipe)
        status_matches += int(same_status)
        rows.append(
            [
                path.stem,
                new.recipe_id or "-",
                f"{new.score:.4f}",
                new.status,
                old.recipe.recipe_id if old.recipe else "-",
                f"{old.score:.4f}",
                old.status,
                "yes" if same_recipe and same_status else "no",
            ]
        )

    header = (
        "| case | new_recipe | new_score | new_status | legacy_recipe | "
        "legacy_score | legacy_status | parity |"
    )
    print(header)
    print("|---|---|---|---|---|---|---|---|")
    for row in rows:
        print("| " + " | ".join(row) + " |")

    print()
    recipe_parity = matches / total
    status_parity = status_matches / total
    print(f"cases={total} recipe_parity={recipe_parity:.4f} status_parity={status_parity:.4f}")
    print(json.dumps({"cases": total, "recipe_parity": matches / total}, ensure_ascii=False))


if __name__ == "__main__":
    main()
