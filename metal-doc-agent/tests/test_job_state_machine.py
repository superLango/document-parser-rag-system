"""A9 job state-machine tests: transitions, claims and stale recovery."""

from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from metal_doc_agent.jobs import CLAIM_NAME, JobStore
from metal_doc_agent.runner import _failure_code, _store_orchestrated_result, run_job
from metal_doc_agent.settings import Settings
from metal_doc_agent.worker import run_queued

ROOT = Path(__file__).resolve().parents[1]

SAMPLE = """# Page 1

表1 室温力学性能

<table>
<tr><td>牌号</td><td>抗拉强度Rm/MPa(不小于)</td></tr>
<tr><td>2A14</td><td>430</td></tr>
</table>
"""


class JobStateMachineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.doc = self.root / "sample.md"
        self.doc.write_text(SAMPLE, encoding="utf-8")
        self.settings = Settings(
            project_root=ROOT,
            data_dir=self.root / "data",
            ocr_backend="mock",
            extractor_backend="mock",
            glm_ocr_base_url=None,
            glm_ocr_model="GLM-OCR",
            qwen_base_url=None,
            qwen_model="Qwen3.5-9B",
            api_key=None,
            request_timeout=10.0,
        )
        self.jobs_root = self.root / "data" / "jobs"
        self.store = JobStore(self.jobs_root, stale_seconds=60.0)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _reserve(self, job_id: str = "statejob01") -> str:
        state, created = self.store.reserve(
            job_id=job_id,
            idempotency_key=f"state-key-{job_id}",
            source_name="sample.md",
            source_sha256="sha",
            doc_path=str(self.doc),
            options={"ocr": "mock", "extractor": "mock"},
        )
        self.assertTrue(created)
        return state.job_id

    def test_lane_defaults_and_list_filter(self) -> None:
        production, _ = self.store.reserve(
            job_id="lanejob001",
            idempotency_key="lane-key-1",
            source_name="sample.md",
            source_sha256="sha",
            doc_path=str(self.doc),
            options={"ocr": "mock", "extractor": "mock"},
        )
        explore, _ = self.store.reserve(
            job_id="lanejob002",
            idempotency_key="lane-key-2",
            source_name="sample.md",
            source_sha256="sha",
            doc_path=str(self.doc),
            options={"ocr": "mock", "extractor": "mock"},
            lane="explore",
        )
        self.assertEqual(production.lane, "production")
        self.assertEqual(explore.lane, "explore")
        self.assertEqual(
            [state.job_id for state in self.store.list(lane="explore")],
            ["lanejob002"],
        )
        self.assertEqual(
            [state.job_id for state in self.store.list(lane="production")],
            ["lanejob001"],
        )
        with self.assertRaises(ValueError):
            self.store.reserve(
                job_id="lanejob003",
                idempotency_key="lane-key-3",
                source_name="sample.md",
                source_sha256="sha",
                doc_path=str(self.doc),
                options={"ocr": "mock", "extractor": "mock"},
                lane="bogus",
            )

    def test_invalid_transitions_are_rejected(self) -> None:
        job_id = self._reserve()
        with self.assertRaises(ValueError):
            self.store.update(job_id, status="succeeded")
        self.store.update(job_id, status="running", stage="starting")
        with self.assertRaises(ValueError):
            self.store.update(job_id, status="queued")
        self.store.update(job_id, status="review", stage="done", progress=100)
        self.store.update(job_id, status="queued", stage="retry", progress=0)
        self.store.update(job_id, status="running", stage="starting")
        self.store.update(job_id, status="succeeded", stage="done", progress=100)
        with self.assertRaises(RuntimeError):
            self.store.reset_for_retry(job_id)
        with self.assertRaises(RuntimeError):
            run_job(self.store, job_id, self.settings)

    def test_claim_is_exclusive(self) -> None:
        job_id = self._reserve()
        other = JobStore(self.jobs_root, stale_seconds=60.0)
        claimed = self.store.claim(job_id)
        self.assertIsNotNone(claimed)
        assert claimed is not None
        self.assertEqual(claimed.status, "running")
        self.assertEqual(claimed.attempts, 1)
        self.assertIsNone(other.claim(job_id))

        self.store.release_claim(job_id)
        self.assertFalse((self.jobs_root / job_id / CLAIM_NAME).exists())
        self.assertIsNone(other.claim(job_id))

    def test_fresh_claim_is_not_recovered(self) -> None:
        job_id = self._reserve()
        self.assertIsNotNone(self.store.claim(job_id))
        self.assertEqual(self.store.recover_stale_running(), [])
        state = self.store.get(job_id)
        assert state is not None
        self.assertEqual(state.status, "running")

    def test_stale_running_is_requeued_and_run(self) -> None:
        job_id = self._reserve()
        self.assertIsNotNone(self.store.claim(job_id))
        marker = self.jobs_root / job_id / CLAIM_NAME
        old = time.time() - 3600
        os.utime(marker, (old, old))

        self.assertEqual(self.store.recover_stale_running(), [job_id])
        recovered = self.store.get(job_id)
        assert recovered is not None
        self.assertEqual(recovered.status, "queued")
        self.assertEqual(recovered.stage, "retry")
        self.assertEqual(recovered.error, "stale runner recovered")

        ran = run_queued(self.store, self.settings)
        self.assertEqual(ran, [job_id])
        final = self.store.get(job_id)
        assert final is not None
        self.assertIn(final.status, {"succeeded", "review"})
        self.assertFalse(marker.exists())

    def test_running_job_without_marker_is_recovered(self) -> None:
        job_id = self._reserve()
        self.store.update(job_id, status="running", stage="starting")
        self.assertEqual(self.store.recover_stale_running(), [job_id])
        state = self.store.get(job_id)
        assert state is not None
        self.assertEqual(state.status, "queued")

    def test_run_queued_skips_claimed_job(self) -> None:
        job_id = self._reserve()
        self.assertIsNotNone(self.store.claim(job_id))
        self.assertEqual(run_queued(self.store, self.settings), [])
        state = self.store.get(job_id)
        assert state is not None
        self.assertEqual(state.status, "running")

    def test_run_job_retries_failed_job(self) -> None:
        job_id = self._reserve()
        self.store.update(job_id, status="running", stage="starting", attempts=1)
        self.store.update(
            job_id, status="failed", stage="error", error="boom", attempts=1
        )
        result = run_job(self.store, job_id, self.settings)
        self.assertIsNotNone(result)
        final = self.store.get(job_id)
        assert final is not None
        self.assertIn(final.status, {"succeeded", "review"})
        self.assertEqual(final.attempts, 2)

    def test_orchestrated_review_reports_failure_context(self) -> None:
        job_id = self._reserve("orchfail01")
        self.store.update(job_id, status="running", stage="starting", progress=1)
        out_dir = Path(self.store.get(job_id).out_dir)
        m3 = SimpleNamespace(
            status="human",
            terminal_reason="retry_exhausted",
            context={},
            errors=[
                SimpleNamespace(
                    message="layout: request failed: [Errno 111] Connection refused"
                )
            ],
            cost=SimpleNamespace(
                steps=5, extract_calls=3, ocr_pages=0, model_tokens=0
            ),
            retries=SimpleNamespace(extract=2, ocr=0),
        )
        _store_orchestrated_result(self.store, job_id, out_dir, m3)
        final = self.store.get(job_id)
        assert final is not None
        self.assertEqual(final.status, "review")
        self.assertEqual(final.failure_code, "layout_failed")
        self.assertIn("layout", final.error or "")

        ocr_job = self._reserve("orchfail02")
        self.store.update(ocr_job, status="running", stage="starting", progress=1)
        ocr_m3 = SimpleNamespace(
            status="human",
            terminal_reason="coverage_gap",
            context={"ocr_quality": 0.0},
            errors=[],
            cost=SimpleNamespace(
                steps=3, extract_calls=1, ocr_pages=1, model_tokens=0
            ),
            retries=SimpleNamespace(extract=0, ocr=0),
        )
        _store_orchestrated_result(
            self.store, ocr_job, Path(self.store.get(ocr_job).out_dir), ocr_m3
        )
        ocr_final = self.store.get(ocr_job)
        assert ocr_final is not None
        self.assertEqual(ocr_final.status, "review")
        self.assertEqual(ocr_final.failure_code, "ocr_failed")
        self.assertEqual(ocr_final.error, "ocr quality 0.0")


class FailureCodeTests(unittest.TestCase):
    def test_failed_job_records_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = JobStore(Path(tmp) / "jobs")
            state, _ = store.reserve(
                job_id="job-missing",
                idempotency_key="missing",
                source_name="missing.md",
                source_sha256="0",
                doc_path=str(Path(tmp) / "missing.md"),
                options={},
            )
            self.assertEqual(state.status, "queued")
            settings = Settings(
                project_root=ROOT,
                data_dir=Path(tmp) / "data",
                ocr_backend="mock",
                extractor_backend="mock",
                glm_ocr_base_url=None,
                glm_ocr_model="GLM-OCR",
                qwen_base_url=None,
                qwen_model="Qwen3.5-9B",
                api_key=None,
                request_timeout=10.0,
            )
            self.assertIsNone(run_job(store, "job-missing", settings))
            final = store.get("job-missing")
            assert final is not None
            self.assertEqual(final.status, "failed")
            self.assertEqual(final.failure_code, "invalid_input")

    def test_failure_taxonomy(self) -> None:
        self.assertEqual(_failure_code(FileNotFoundError("missing")), "invalid_input")
        self.assertEqual(_failure_code(TimeoutError("slow")), "timeout")
        self.assertEqual(_failure_code(RuntimeError("OCR service down")), "ocr_failed")
        self.assertEqual(_failure_code(RuntimeError("layout timeout")), "timeout")
        self.assertEqual(_failure_code(RuntimeError("qwen json invalid")), "extract_failed")
        self.assertEqual(_failure_code(ValueError("bad table")), "invalid_input")
        self.assertEqual(_failure_code(RuntimeError("boom")), "engine_failed")


if __name__ == "__main__":
    unittest.main()
