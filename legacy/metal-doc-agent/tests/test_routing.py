"""M2.5.2 routing, queues and fallback."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from metal_doc_agent.contracts import Recipe, RecipeSignature, TableGrid
from metal_doc_agent.queues import QueueStore, fallback_to_explore
from metal_doc_agent.recipes import (
    RouteDecision,
    decide_route,
    doc_queue,
    load_recipes,
)
from metal_doc_agent.recipes.routing import MAX_COLS, PRODUCTION_SCORE
from metal_doc_agent.tablegrid.parser import parse_table

RUNS_DIR = Path(__file__).resolve().parents[1] / "runs" / "m2_baseline"
ROOT = Path(__file__).resolve().parents[1]

MECH_HTML = (
    "<table>"
    "<tr><td>牌号</td><td>热处理状态</td><td>取样方向</td>"
    "<td>抗拉强度Rm/MPa(不小于)</td><td>断后伸长率A/%(不小于)</td></tr>"
    "<tr><td>2A14</td><td>T6</td><td>切向</td><td>430</td><td>10</td></tr>"
    "</table>"
)


def mech_table():
    return parse_table(MECH_HTML, "T1", 5, caption="表1 力学性能")


class RoutingTests(unittest.TestCase):
    @unittest.skipUnless(RUNS_DIR.exists(), "baseline runs not available")
    def test_real_table_routes_to_production(self) -> None:
        recipes = load_recipes()
        production = []
        for path in sorted(RUNS_DIR.glob("*/tablegrid/*.json"))[:40]:
            table = TableGrid.model_validate(
                json.loads(path.read_text(encoding="utf-8"))
            )
            decision = decide_route(table, recipes)
            if decision.queue == "production":
                production.append(decision)
        self.assertTrue(production, "no production decision in first 40 tables")
        for decision in production:
            self.assertGreaterEqual(decision.score, PRODUCTION_SCORE)
            self.assertTrue(any("signature_score" in reason for reason in decision.reasons))

    def test_classification_table_goes_to_production(self) -> None:
        table = parse_table(
            "<table><tr><td>牌号</td><td>类别</td></tr>"
            "<tr><td>2A14</td><td>普通级</td></tr></table>",
            "T1",
            5,
            caption="表1 分类",
        )
        decision = decide_route(table, load_recipes())
        self.assertEqual(decision.queue, "production")
        self.assertEqual(decision.recipe_id, "classification_v1")

    def test_ambiguous_top2_goes_to_human(self) -> None:
        table = mech_table()
        template = load_recipes()[0]
        base = RecipeSignature(
            profile="mechanical_properties",
            orientation="grade_rows",
            n_cols=table.n_cols,
            tokens=[token for token in template.signature.tokens][:5],
        )
        twin_a = Recipe(recipe_id="twin_a", profile="mechanical_properties", signature=base)
        twin_b = Recipe(recipe_id="twin_b", profile="mechanical_properties", signature=base)
        decision = decide_route(table, [twin_a, twin_b])
        self.assertEqual(decision.queue, "human")
        self.assertTrue(any("ambiguous_top2" in reason for reason in decision.reasons))

    def test_oversized_table_and_force_human_go_to_human(self) -> None:
        table = mech_table()
        wide = table.model_copy(update={"n_cols": MAX_COLS + 5})
        decision = decide_route(wide, load_recipes())
        self.assertEqual(decision.queue, "human")
        self.assertIn("risky_table_size", decision.reasons)
        forced = decide_route(table, load_recipes(), force_human=True)
        self.assertEqual(forced.queue, "human")
        self.assertEqual(forced.reasons, ["forced_human"])

    def test_header_hints_disambiguate_mechanical_from_hardness(self) -> None:
        table = mech_table()
        base = RecipeSignature(
            profile="mechanical_properties",
            orientation="grade_rows",
            n_cols=table.n_cols,
            tokens=["牌号", "rm", "rp0.2", "ku2", "硬度"],
        )
        mechanical = Recipe(
            recipe_id="mechanical_properties_v1",
            profile="mechanical_properties",
            signature=base,
        )
        hardness = Recipe(
            recipe_id="zzz_hardness_v1",
            profile="mechanical_properties",
            signature=base,
        )
        decision = decide_route(table, [mechanical, hardness])
        self.assertEqual(decision.queue, "production")
        self.assertTrue(
            any("disambiguated_by_header" in reason for reason in decision.reasons)
        )

    def test_history_lowers_confidence(self) -> None:
        decision = decide_route(
            mech_table(), load_recipes(), history={"mechanical_properties_v1": 0.2}
        )
        self.assertLess(decision.confidence, decision.score)
        self.assertTrue(any("history_success" in reason for reason in decision.reasons))

    def test_doc_queue_priority(self) -> None:
        prod = RouteDecision("production", "candidate", "r1", 0.8, 0.8, [])
        human = RouteDecision("human", "candidate", "r1", 0.8, 0.8, ["forced_human"])
        self.assertEqual(doc_queue([prod]), "production")
        self.assertEqual(doc_queue([prod, human]), "production")
        self.assertEqual(doc_queue([human]), "human")


class QueueStoreTests(unittest.TestCase):
    def test_lanes_are_isolated_and_fifo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = QueueStore(tmp)
            first = store.enqueue("explore", {"doc_id": "d1"})
            second = store.enqueue("explore", {"doc_id": "d2"})
            store.enqueue("production", {"doc_id": "d3"})
            self.assertEqual(store.stats(), {"production": 1, "explore": 2, "human": 0})
            head = store.dequeue("explore")
            self.assertEqual(head["item_id"], first)
            self.assertEqual(store.peek("explore")["item_id"], second)
            self.assertNotEqual(head["doc_id"], "d3")

    def test_fallback_moves_item_to_explore(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = QueueStore(tmp)
            item_id = store.enqueue("production", {"doc_id": "d1"})
            fallback_to_explore(store, store.dequeue("production"), "extract_failed")
            record = store.peek("explore")
            self.assertEqual(record["item_id"], item_id)
            self.assertEqual(record["fallback_from"], "production")
            self.assertEqual(record["fallback_reason"], "extract_failed")

    def test_unknown_lane_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                QueueStore(tmp).enqueue("nowhere", {})


class PipelineRoutingTests(unittest.TestCase):
    SAMPLE = """# Page 1

## 4.5 室温力学性能

表1 力学性能

<table border="1">
  <tr><td rowspan="2">牌号</td><td colspan="3">室温力学性能</td></tr>
  <tr><td>Rm/MPa</td><td>Rp0.2/MPa</td><td>A/%</td></tr>
  <tr><td>2A14</td><td>430</td><td>350</td><td>10</td></tr>
</table>
"""

    def test_pipeline_enqueues_document_when_routing_enabled(self) -> None:
        from metal_doc_agent.pipeline import run_pipeline
        from metal_doc_agent.settings import Settings

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            doc = root / "sample.md"
            doc.write_text(self.SAMPLE, encoding="utf-8")
            settings = Settings(
                project_root=ROOT,
                data_dir=root / "data",
                ocr_backend="mock",
                extractor_backend="mock",
                glm_ocr_base_url=None,
                glm_ocr_model="GLM-OCR",
                qwen_base_url=None,
                qwen_model="Qwen3.5-9B",
                api_key=None,
                request_timeout=10.0,
                recipe_routing=True,
            )
            out = root / "out"
            result = run_pipeline(doc, out, settings=settings)
            routing = json.loads((out / "routing.json").read_text(encoding="utf-8"))
            self.assertIn(routing["queue"], {"production", "explore", "human"})
            self.assertTrue(routing["queued"])
            self.assertIn("T1", routing["tables"])
            self.assertIn("routing", result.result.artifacts)
            queue_path = settings.data_dir / "queues" / f"{routing['queue']}.jsonl"
            self.assertTrue(queue_path.exists())
            records = [
                json.loads(line)
                for line in queue_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertEqual(records[0]["lane"], routing["queue"])
            trace = json.loads((out / "trace.json").read_text(encoding="utf-8"))
            names = [step["name"] for step in trace["steps"]]
            self.assertIn("routing", names)
            self.assertEqual(trace["versions"]["routing"], "m2.5.3")


if __name__ == "__main__":
    unittest.main()
