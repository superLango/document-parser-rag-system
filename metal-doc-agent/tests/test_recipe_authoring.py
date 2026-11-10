import json
import tempfile
import unittest
from pathlib import Path

from metal_doc_agent.recipes import (
    bind_columns,
    is_duplicate,
    load_recipes,
    promote_candidate,
    propose_recipe,
    save_candidate,
)
from tests.test_recipes import mechanical_table


class RecipeAuthoringTests(unittest.TestCase):
    def test_propose_candidate_from_bindings(self) -> None:
        table = mechanical_table()
        bindings = bind_columns(table, match_status="candidate")
        candidate = propose_recipe(table, bindings)
        self.assertEqual(candidate.status, "candidate")
        self.assertEqual(candidate.profile, "mechanical_properties")
        self.assertIn("Rm", candidate.bindings["measures"])
        self.assertIn("KU2", candidate.bindings["measures"])
        self.assertIn("持久时间", candidate.bindings["measures"])
        self.assertIn("牌号", candidate.bindings["row_key"])
        self.assertTrue(candidate.rules["candidate"])

    def test_duplicate_detection(self) -> None:
        table = mechanical_table()
        bindings = bind_columns(table, match_status="candidate")
        candidate = propose_recipe(table, bindings)
        duplicate = is_duplicate(candidate, load_recipes())
        self.assertIsNotNone(duplicate)
        self.assertEqual(duplicate.recipe_id, "mechanical_properties_v1")

    def test_save_and_promote_candidate(self) -> None:
        table = mechanical_table()
        bindings = bind_columns(table, match_status="candidate")
        candidate = propose_recipe(table, bindings)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            saved = save_candidate(candidate, tmp_path / "candidates")
            payload = json.loads(saved.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "candidate")
            promoted = promote_candidate(saved, tmp_path / "recipes", force=True)
            payload = json.loads(promoted.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "active")
            self.assertTrue(promoted.exists())


if __name__ == "__main__":
    unittest.main()
