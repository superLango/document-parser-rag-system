"""M2.5.3 recipe lifecycle: levels, gates, promotion, rollback, deprecation."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from metal_doc_agent.contracts import Recipe, RecipeSignature
from metal_doc_agent.recipes import (
    LifecycleError,
    RecipeRegistry,
    load_recipes,
)

ROOT = Path(__file__).resolve().parents[1]
RECIPE_DIR = ROOT / "configs" / "recipes"


def make_recipe(recipe_id: str, status: str = "candidate") -> Recipe:
    return Recipe(
        recipe_id=recipe_id,
        status=status,
        profile="mechanical_properties",
        signature=RecipeSignature(
            profile="mechanical_properties",
            orientation="grade_rows",
            n_cols=9,
            tokens=["牌号", "rm", "rp0.2"],
        ),
    )


def write_recipe(directory: Path, recipe: Recipe) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{recipe.recipe_id}.json"
    path.write_text(
        json.dumps(recipe.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


SHADOW_OK = {"agreement": 0.99, "coverage": 0.97, "orphan_rate": 0.002}
APPROVAL_OK = {"approved_by": ["metal-qa"], "approval_note": "首批 20 份文档通过"}


class LifecycleLevelTests(unittest.TestCase):
    def test_derived_levels_and_apply(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry = RecipeRegistry(root / "registry.json")
            active = make_recipe("legacy_active", "active")
            candidate = make_recipe("legacy_candidate", "candidate")
            retired = make_recipe("legacy_retired", "retired")
            write_recipe(root, active)
            write_recipe(root / "candidates", candidate)
            write_recipe(root, retired)
            self.assertEqual(registry.level_for(active), "L4")
            self.assertEqual(registry.level_for(candidate), "L2")
            self.assertEqual(registry.level_for(retired), "L5")
            applied = registry.apply([active, candidate, retired])
            self.assertEqual([item.status for item in applied], ["active", "candidate", "retired"])

    def test_unknown_recipe_has_no_derived_level(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry = RecipeRegistry(Path(tmp) / "registry.json")
            self.assertIsNone(registry.level_of("does_not_exist"))
            registry.record_run("does_not_exist", success=True)
            self.assertEqual(registry.level_of("does_not_exist"), "L0")


class PromotionTests(unittest.TestCase):
    def test_l3_requires_shadow_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            recipe = make_recipe("cand", "candidate")
            write_recipe(root / "candidates", recipe)
            registry = RecipeRegistry(root / "registry.json")
            with self.assertRaises(LifecycleError):
                registry.promote("cand", "L3", actor="qa")
            entry = registry.promote("cand", "L3", actor="qa", evidence=SHADOW_OK)
            self.assertEqual(entry["level"], "L3")
            self.assertEqual(entry["history"][-1]["from"], "L2")

    def test_illegal_transition_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            recipe = make_recipe("cand", "candidate")
            write_recipe(root / "candidates", recipe)
            registry = RecipeRegistry(root / "registry.json")
            with self.assertRaises(LifecycleError):
                registry.promote("cand", "L4", actor="qa", evidence=APPROVAL_OK)

    def test_l4_requires_human_signoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            recipe = make_recipe("cand", "candidate")
            write_recipe(root / "candidates", recipe)
            registry = RecipeRegistry(root / "registry.json")
            registry.promote("cand", "L3", actor="qa", evidence=SHADOW_OK)
            with self.assertRaises(LifecycleError):
                registry.promote("cand", "L4", actor="qa", evidence={"approved_by": []})
            entry = registry.promote("cand", "L4", actor="leader", evidence=APPROVAL_OK)
            self.assertEqual(entry["level"], "L4")
            self.assertEqual(entry["history"][-1]["kind"], "promote")

    def test_force_bypasses_gate_but_is_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            recipe = make_recipe("cand", "candidate")
            write_recipe(root / "candidates", recipe)
            registry = RecipeRegistry(root / "registry.json")
            entry = registry.promote(
                "cand", "L3", actor="ops", evidence={}, force=True
            )
            self.assertTrue(entry["history"][-1]["forced"])

    def test_promotion_persists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            recipe = make_recipe("cand", "candidate")
            write_recipe(root / "candidates", recipe)
            registry = RecipeRegistry(root / "registry.json")
            registry.promote("cand", "L3", actor="qa", evidence=SHADOW_OK)
            reloaded = RecipeRegistry(root / "registry.json")
            self.assertEqual(reloaded.level_of("cand"), "L3")
            self.assertEqual(len(reloaded.entry("cand")["history"]), 1)


class RollbackTests(unittest.TestCase):
    def test_rollback_walks_back_one_promotion_at_a_time(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            recipe = make_recipe("cand", "candidate")
            write_recipe(root / "candidates", recipe)
            registry = RecipeRegistry(root / "registry.json")
            registry.promote("cand", "L3", actor="qa", evidence=SHADOW_OK)
            registry.promote("cand", "L4", actor="leader", evidence=APPROVAL_OK)
            entry = registry.rollback("cand", actor="ops")
            self.assertEqual(entry["level"], "L3")
            entry = registry.rollback("cand", actor="ops")
            self.assertEqual(entry["level"], "L2")
            history = [item["kind"] for item in entry["history"]]
            self.assertEqual(history, ["promote", "promote", "rollback", "rollback"])

    def test_rollback_without_history_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry = RecipeRegistry(Path(tmp) / "registry.json")
            with self.assertRaises(LifecycleError):
                registry.rollback("cand", actor="ops")

    def test_deprecate_then_reactivate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            recipe = make_recipe("active_recipe", "active")
            write_recipe(root, recipe)
            registry = RecipeRegistry(root / "registry.json")
            entry = registry.deprecate("active_recipe", actor="ops", note="GB/T 换版")
            self.assertEqual(entry["level"], "L5")
            entry = registry.rollback("active_recipe", actor="ops")
            self.assertEqual(entry["level"], "L4")


class StatsAndLoadTests(unittest.TestCase):
    def test_record_run_and_success_rates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry = RecipeRegistry(Path(tmp) / "registry.json")
            registry.record_run("cand", success=True)
            registry.record_run("cand", success=False)
            self.assertEqual(registry.success_rates(), {"cand": 0.5})
            self.assertEqual(registry.level_of("cand"), "L0")

    def test_load_recipes_applies_registry_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = json.loads(
                (RECIPE_DIR / "mechanical_properties_v1.json").read_text(encoding="utf-8")
            )
            (root / "mechanical_properties_v1.json").write_text(
                json.dumps(source, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            registry = RecipeRegistry(root / "registry.json")
            registry.entries["mechanical_properties_v1"] = {
                "recipe_id": "mechanical_properties_v1",
                "level": "L5",
                "history": [],
            }
            registry.save()
            recipes = load_recipes(root)
            self.assertEqual(recipes[0].status, "retired")

    def test_shipped_registry_is_empty_and_keeps_active_recipes(self) -> None:
        registry = RecipeRegistry(RECIPE_DIR / "registry.json")
        self.assertEqual(registry.entries, {})
        recipes = load_recipes(RECIPE_DIR)
        active = [item for item in recipes if item.status == "active"]
        self.assertGreaterEqual(len(active), 6)


if __name__ == "__main__":
    unittest.main()
