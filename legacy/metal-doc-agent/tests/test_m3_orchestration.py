"""M3 orchestration: state contract, context compaction, repair and graph paths."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from metal_doc_agent.contracts import AuditReport, CoveragePlan, DocumentMeta, Evidence, TableGrid
from metal_doc_agent.orchestration import (
    Budget,
    OrchestrationState,
    PipelineTools,
    ToolError,
    assemble_context,
    compact_context,
    context_regression,
    decide_repair,
    resume_orchestration,
    run_orchestrated,
)
from metal_doc_agent.orchestration.graph import NodeContext, build_workflow
from metal_doc_agent.settings import Settings

ROOT = Path(__file__).resolve().parents[1]

MECH_DOC = """# Page 1

## 4.5 室温力学性能

表1 力学性能

<table>
<tr><td>牌号</td><td>规格</td><td>状态</td><td>室温拉伸Rm/MPa</td><td>室温拉伸Rp0.2/MPa</td><td>室温拉伸A/%</td><td>冲击KU2/J</td><td>持久试验温度/℃</td><td>持久时间/h</td></tr>
<tr><td>2A14</td><td>10</td><td>T6</td><td>430</td><td>350</td><td>10</td><td>25</td><td>20</td><td>100</td></tr>
</table>
"""

AMBIGUOUS_DOC = """# Page 1

表1 板材力学性能

<table>
<tr><td>牌号</td><td>抗拉强度Rm/MPa</td><td>断后伸长率A/%</td></tr>
<tr><td>2A14</td><td>430</td><td>10</td></tr>
</table>
"""


def make_settings(root: Path) -> Settings:
    return Settings(
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
        business_dictionary_override_path=str(root / "no-override.json"),
        recipe_routing=True,
    )


class StateContractTests(unittest.TestCase):
    def test_state_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = OrchestrationState(job_id="job1", budget=Budget(max_steps=12))
            path = Path(tmp) / "m3_state.json"
            state.save(path)
            loaded = OrchestrationState.load(path)
            self.assertEqual(loaded.job_id, "job1")
            self.assertEqual(loaded.budget.max_steps, 12)
            self.assertEqual(loaded.status, "running")
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["stage"], "plan")


class ContextTests(unittest.TestCase):
    def _table(self) -> TableGrid:
        return TableGrid(
            table_id="T1",
            page_no=5,
            n_rows=3,
            n_cols=3,
            header_paths=[["牌号"], ["Rm(MPa)"], ["A(%)"]],
            rows=[["2A14", "430", "10"]],
            units=["MPa", "%"],
            profile="mechanical_properties",
        )

    def test_compaction_keeps_evidence_headers_units(self) -> None:
        context = assemble_context(
            {"doc_id": "d1"},
            table=self._table(),
            clauses=[
                {"clause_id": f"4.{i}", "title": f"条款{i}", "text": "很长的正文 " * 80}
                for i in range(12)
            ],
            evidence_ids=["ev1", "ev2"],
            schema_fields=["records.grade"],
            previous_errors=[{"code": "EVIDENCE_NOT_FOUND", "stage": "validate"}],
        )
        compacted = compact_context(context)
        regression = context_regression(context, compacted)
        self.assertTrue(regression["lossless"])
        self.assertEqual(compacted["evidence_ids"], ["ev1", "ev2"])
        self.assertEqual(compacted["table"]["header_paths"], context["table"]["header_paths"])
        self.assertEqual(compacted["table"]["units"], ["MPa", "%"])
        self.assertTrue(all(item["text_dropped"] for item in compacted["clauses"]))
        self.assertGreater(regression["token_reduction"], 0)
        self.assertIn("Rm", regression["fields_before"])
        self.assertIn("A", regression["fields_before"])
        self.assertEqual(regression["lost_fields"], [])
        self.assertEqual(regression["field_loss_rate"], 0.0)

    def test_context_is_capped(self) -> None:
        context = assemble_context(
            table=self._table(),
            clauses=[
                {"clause_id": f"c{i}", "title": "t", "text": "x" * 3000}
                for i in range(20)
            ],
            max_tokens=3000,
        )
        self.assertLessEqual(context["tokens"], 3000)
        self.assertGreater(len(context["clauses"]), 0)


class RepairDecisionTests(unittest.TestCase):
    def _state(self, **kwargs) -> OrchestrationState:
        state = OrchestrationState(job_id="j", budget=Budget())
        for key, value in kwargs.items():
            setattr(state, key, value)
        return state

    def test_low_ocr_quality_retries_ocr(self) -> None:
        decision = decide_repair(
            self._state(),
            ocr_quality=0.2,
            audit_status="pass",
            issue_codes=[],
            coverage_missing=0,
        )
        self.assertEqual(decision.action, "retry_ocr")

    def test_retryable_audit_error_retries_extract(self) -> None:
        decision = decide_repair(
            self._state(),
            ocr_quality=1.0,
            audit_status="fail",
            issue_codes=["EVIDENCE_NOT_FOUND"],
            coverage_missing=0,
        )
        self.assertEqual(decision.action, "retry_extract")

    def test_budget_exhaustion_sends_to_human(self) -> None:
        state = self._state()
        state.retries.extract = state.budget.max_extract_retries
        decision = decide_repair(
            state,
            ocr_quality=1.0,
            audit_status="fail",
            issue_codes=["EVIDENCE_NOT_FOUND"],
            coverage_missing=0,
        )
        self.assertEqual(decision.action, "human")

    def test_coverage_gap_goes_to_human(self) -> None:
        decision = decide_repair(
            self._state(),
            ocr_quality=1.0,
            audit_status="review",
            issue_codes=[],
            coverage_missing=3,
        )
        self.assertEqual(decision.action, "human")
        self.assertEqual(decision.code, "coverage_gap")

    def test_clean_run_stops(self) -> None:
        decision = decide_repair(
            self._state(), ocr_quality=1.0, audit_status="pass", issue_codes=[], coverage_missing=0
        )
        self.assertEqual(decision.action, "stop")


class ToolSandboxTests(unittest.TestCase):
    def test_unknown_tool_and_unsafe_paths_are_denied(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tools = PipelineTools(make_settings(Path(tmp)), Path(tmp) / "out")
            with self.assertRaises(ToolError):
                tools.call("exec_code", source="print(1)")
            with self.assertRaises(ToolError):
                tools.load_artifact("../secret.json")
            with self.assertRaises(ToolError):
                tools.write_artifact("state.json", {"x": 1})


class GraphPathTests(unittest.TestCase):
    def test_production_route_reaches_human_with_trace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            doc = root / "mech.md"
            doc.write_text(MECH_DOC, encoding="utf-8")
            out = root / "out"
            state = run_orchestrated(doc, out, make_settings(root))
            self.assertEqual(state.status, "human")
            self.assertEqual(state.route.queue, "production")
            self.assertIsNotNone(state.context.get("audit"))
            self.assertTrue((out / "m3_trace.json").exists())
            queue = root / "data" / "queues" / "human.jsonl"
            self.assertTrue(queue.exists())
            nodes = [item.node for item in state.history]
            self.assertEqual(
                nodes,
                ["plan", "extract", "ocr_gate", "route", "validate", "coverage", "repair", "human"],
            )

    def test_ambiguous_route_goes_human_before_validate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            doc = root / "amb.md"
            doc.write_text(AMBIGUOUS_DOC, encoding="utf-8")
            state = run_orchestrated(doc, root / "out", make_settings(root))
            self.assertEqual(state.status, "human")
            self.assertEqual(state.terminal_reason, "route_human")
            self.assertNotIn("validate", [item.node for item in state.history])

    def test_publish_gate_publishes_passing_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = OrchestrationState(job_id="j1", stage="publish_gate", doc_id="d1")
            state.context["audit"] = {"status": "pass", "codes": [], "coverage_missing": 0}
            settings = make_settings(root)
            out = root / "out"
            out.mkdir(parents=True)
            ctx = NodeContext(
                settings=settings,
                out_dir=out,
                tools=PipelineTools(settings, out),
                checkpoints=out / "m3_state.json",
            )
            result = build_workflow().run(state, ctx)
            self.assertEqual(result.status, "published")
            self.assertTrue((root / "data" / "queues" / "production.jsonl").exists())

    def test_resume_from_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            doc = root / "mech.md"
            doc.write_text(MECH_DOC, encoding="utf-8")
            out = root / "out"
            settings = make_settings(root)
            state = run_orchestrated(doc, out, settings)
            checkpoint = OrchestrationState.load(out / "m3_state.json")
            checkpoint.status = "running"
            checkpoint.stage = "assemble"
            checkpoint.terminal_reason = None
            checkpoint.save(out / "m3_state.json")
            resumed = resume_orchestration(out, settings, decision="publish")
            self.assertEqual(resumed.status, "published")
            self.assertGreater(resumed.cost.steps, checkpoint.cost.steps)

    def test_always_failing_extract_stops_at_budget(self) -> None:
        class FailingTools(PipelineTools):
            def run_extract(self, *args, **kwargs):
                self.extract_calls += 1
                raise RuntimeError("model down")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            doc = root / "mech.md"
            doc.write_text(MECH_DOC, encoding="utf-8")
            out = root / "out"
            settings = make_settings(root)
            tools = FailingTools(settings, out)
            state = run_orchestrated(doc, out, settings, tools=tools)
            self.assertEqual(state.status, "human")
            self.assertLessEqual(state.cost.steps, state.budget.max_steps + 1)
            self.assertGreaterEqual(state.retries.extract, 1)
            self.assertLessEqual(state.retries.extract, state.budget.max_extract_retries)
            nodes = [item.node for item in state.history]
            self.assertEqual(nodes[-1], "human")

    def test_transient_extract_failure_is_retried(self) -> None:
        class FlakyTools(PipelineTools):
            def __init__(self, settings, out):
                super().__init__(settings, out)
                self.failures = 1

            def run_extract(self, *args, **kwargs):
                if self.failures:
                    self.failures -= 1
                    self.extract_calls += 1
                    raise TimeoutError("first attempt timeout")
                return super().run_extract(*args, **kwargs)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            doc = root / "mech.md"
            doc.write_text(MECH_DOC, encoding="utf-8")
            out = root / "out"
            settings = make_settings(root)
            tools = FlakyTools(settings, out)
            state = run_orchestrated(doc, out, settings, tools=tools)
            self.assertEqual(state.retries.extract, 1)
            self.assertGreaterEqual(tools.extract_calls, 2)
            nodes = [item.node for item in state.history]
            self.assertEqual(nodes.count("extract"), 2)
            self.assertEqual(state.status, "human")


if __name__ == "__main__":
    unittest.main()
