"""M2.5.1 recipe contracts: JSON Schema, signature, router fixtures."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from metal_doc_agent.contracts import Recipe, RecipeSignature, TableGrid
from metal_doc_agent.recipes import (
    load_recipes,
    match_recipe,
    recipe_id_matches_stem,
    route_table,
    validate_recipe,
)
from metal_doc_agent.recipes.signature import build_signature
from metal_doc_agent.tablegrid.parser import parse_table

ROOT = Path(__file__).resolve().parents[1]
RECIPE_DIR = ROOT / "configs" / "recipes"
RUNS_DIR = ROOT / "runs" / "m2_baseline"


def _load_table(path: Path) -> TableGrid:
    return TableGrid.model_validate(json.loads(path.read_text(encoding="utf-8")))


class RecipeSchemaTests(unittest.TestCase):
    def test_active_recipe_files_match_schema_and_stem(self) -> None:
        files = [
            path
            for path in sorted(RECIPE_DIR.glob("*.json"))
            if json.loads(path.read_text(encoding="utf-8")).get("recipe_id")
        ]
        self.assertGreaterEqual(len(files), 6)
        for file_path in files:
            errors = validate_recipe(file_path)
            self.assertEqual(errors, [], f"{file_path.name}: {errors}")
            self.assertTrue(recipe_id_matches_stem(file_path), file_path.name)

    def test_candidate_files_match_schema(self) -> None:
        for file_path in sorted((RECIPE_DIR / "candidates").glob("*.json")):
            errors = validate_recipe(file_path)
            self.assertEqual(errors, [], f"{file_path.name}: {errors}")

    def test_retired_recipe_is_never_matched(self) -> None:
        table = parse_table(
            "<table><tr><td>牌号</td><td>抗拉强度Rm/MPa</td></tr>"
            "<tr><td>2A14</td><td>430</td></tr></table>",
            "T1",
            5,
            caption="表1 力学性能",
        )
        retired = Recipe(
            recipe_id="retired_probe",
            status="retired",
            profile="mechanical_properties",
            signature=RecipeSignature(
                profile="mechanical_properties",
                orientation="grade_rows",
                n_cols=2,
                tokens=["牌号", "rm"],
            ),
        )
        match = match_recipe(table, [retired])
        self.assertIsNone(match.recipe)
        self.assertEqual(match.status, "unknown")


class RecipeSignatureTests(unittest.TestCase):
    def test_multi_header_and_units_are_part_of_signature(self) -> None:
        table = parse_table(
            "<table>"
            "<tr><td>牌号</td><td>力学性能</td></tr>"
            "<tr><td></td><td>抗拉强度Rm/MPa</td></tr>"
            "<tr><td>2A14</td><td>430</td></tr>"
            "</table>",
            "T1",
            5,
            caption="表1 力学性能",
        )
        signature = build_signature(table)
        self.assertTrue(signature.multi_header)
        self.assertIn("rm", signature.tokens)


@unittest.skipUnless(RUNS_DIR.exists(), "baseline runs not available")
class RecipeFixtureTests(unittest.TestCase):
    def test_each_active_recipe_hits_a_representative_table(self) -> None:
        fixtures: dict[tuple[str, str], TableGrid] = {}
        for path in sorted(RUNS_DIR.glob("*/tablegrid/*.json")):
            table = _load_table(path)
            key = (table.profile, table.orientation)
            fixtures.setdefault(key, table)
        recipes = load_recipes()
        self.assertGreaterEqual(len(recipes), 6)
        for recipe in recipes:
            key = (recipe.signature.profile, recipe.signature.orientation)
            table = fixtures.get(key)
            self.assertIsNotNone(
                table, f"no fixture table for {recipe.recipe_id} ({key})"
            )
            match = route_table(table, recipes)
            self.assertNotEqual(match.status, "unknown", recipe.recipe_id)
            self.assertGreaterEqual(match.score, 0.6, recipe.recipe_id)


if __name__ == "__main__":
    unittest.main()
