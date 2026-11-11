"""Artifact manifest and job store tests."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from metal_doc_agent.artifacts import (
    MANIFEST_NAME,
    read_artifact_manifest,
    verify_artifacts,
)
from metal_doc_agent.jobs import JobStore
from metal_doc_agent.pipeline import run_pipeline
from metal_doc_agent.runner import run_job
from metal_doc_agent.settings import Settings

SAMPLE_MD = """# Page 1

# Q/Du 302-2015

表1 室温力学性能

<table>
<tr><td>牌号</td><td>抗拉强度Rm/MPa(不小于)</td><td>断后伸长率A/%(不小于)</td></tr>
<tr><td>2A14</td><td>430</td><td>10</td></tr>
</table>
"""


def make_settings(root: Path) -> Settings:
    return Settings(
        project_root=root,
        data_dir=root,
        ocr_backend="mock",
        extractor_backend="mock",
        glm_ocr_base_url=None,
        glm_ocr_model="GLM-OCR",
        qwen_base_url=None,
        qwen_model="Qwen3.5-9B",
        api_key=None,
        request_timeout=10.0,
        layout_service_url=None,
    )


class ArtifactTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.doc = self.root / "sample.md"
        self.doc.write_text(SAMPLE_MD, encoding="utf-8")
        self.settings = make_settings(self.root)
        self.run_dir = self.root / "run"
        self.pipeline = run_pipeline(
            self.doc,
            self.run_dir,
            settings=self.settings,
            coverage_template="enterprise",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_manifest_written_and_verifies(self) -> None:
        path = self.run_dir / MANIFEST_NAME
        self.assertTrue(path.exists())
        manifest = read_artifact_manifest(self.run_dir)
        self.assertEqual(manifest.doc_id, self.pipeline.result.document.doc_id)
        self.assertEqual(self.pipeline.result.artifacts["artifact_manifest"], MANIFEST_NAME)
        entries = {entry.path: entry for entry in manifest.artifacts}
        self.assertIn("result.json", entries)
        self.assertIn("evidence.jsonl", entries)
        self.assertIn("tablegrid/T1.json", entries)
        self.assertNotIn("state.json", entries)
        verification = verify_artifacts(self.run_dir)
        self.assertTrue(verification.ok, verification.issues)
        self.assertGreaterEqual(verification.checked, 8)

    def test_tamper_detected(self) -> None:
        evidence = self.run_dir / "evidence.jsonl"
        original = evidence.read_text(encoding="utf-8")
        evidence.write_text(original + "\n", encoding="utf-8")
        verification = verify_artifacts(self.run_dir)
        self.assertFalse(verification.ok)
        self.assertIn("SIZE_MISMATCH", {issue["code"] for issue in verification.issues})

    def test_missing_required_artifact_detected(self) -> None:
        (self.run_dir / "result.json").unlink()
        verification = verify_artifacts(self.run_dir)
        self.assertFalse(verification.ok)
        codes = {issue["code"] for issue in verification.issues}
        self.assertIn("ARTIFACT_MISSING", codes)

    def test_missing_manifest(self) -> None:
        (self.run_dir / MANIFEST_NAME).unlink()
        verification = verify_artifacts(self.run_dir)
        self.assertFalse(verification.ok)
        self.assertEqual(verification.issues[0]["code"], "MANIFEST_MISSING")


class JobStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.doc = self.root / "sample.md"
        self.doc.write_text(SAMPLE_MD, encoding="utf-8")
        self.store = JobStore(self.root / "jobs")
        self.settings = make_settings(self.root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_reserve_is_idempotent(self) -> None:
        state, created = self.store.reserve(
            job_id="abc12345",
            idempotency_key="key-1",
            source_name="sample.md",
            source_sha256="sha",
            doc_path=str(self.doc),
            options={"ocr": "mock", "extractor": "mock", "template": "enterprise"},
        )
        self.assertTrue(created)
        duplicate, created_again = self.store.reserve(
            job_id="def67890",
            idempotency_key="key-1",
            source_name="sample.md",
            source_sha256="sha",
            doc_path=str(self.doc),
            options={"ocr": "mock", "extractor": "mock", "template": "enterprise"},
        )
        self.assertFalse(created_again)
        self.assertEqual(duplicate.job_id, state.job_id)

    def test_state_persists_and_reloads(self) -> None:
        state, _ = self.store.reserve(
            job_id="abc12345",
            idempotency_key="key-2",
            source_name="sample.md",
            source_sha256="sha",
            doc_path=str(self.doc),
            options={"ocr": "mock", "extractor": "mock", "template": "enterprise"},
        )
        self.store.update(state.job_id, status="running", stage="starting")
        self.store.update(state.job_id, status="review", stage="done", progress=100)
        reloaded = JobStore(self.root / "jobs").get(state.job_id)
        self.assertIsNotNone(reloaded)
        assert reloaded is not None
        self.assertEqual(reloaded.status, "review")
        self.assertEqual(reloaded.progress, 100)
        self.assertIsNotNone(reloaded.finished_at)

    def test_runner_updates_job_and_artifacts(self) -> None:
        state, _ = self.store.reserve(
            job_id="abc12345",
            idempotency_key="key-3",
            source_name="sample.md",
            source_sha256="sha",
            doc_path=str(self.doc),
            options={"ocr": "mock", "extractor": "mock", "template": "enterprise"},
        )
        result = run_job(self.store, state.job_id, self.settings)
        self.assertIsNotNone(result)
        final = self.store.get(state.job_id)
        assert final is not None
        self.assertEqual(final.status, "review")
        self.assertEqual(final.progress, 100)
        self.assertEqual(final.attempts, 1)
        self.assertEqual(final.summary["records"], 1)
        self.assertTrue((Path(final.out_dir) / MANIFEST_NAME).exists())
        self.assertTrue(verify_artifacts(final.out_dir).ok)

    def test_reset_for_retry_clears_error(self) -> None:
        state, _ = self.store.reserve(
            job_id="abc12345",
            idempotency_key="key-4",
            source_name="sample.md",
            source_sha256="sha",
            doc_path=str(self.doc),
            options={"ocr": "mock", "extractor": "mock", "template": "enterprise"},
        )
        self.store.update(state.job_id, status="running", stage="starting")
        self.store.update(state.job_id, status="failed", stage="error", error="boom")
        reset = self.store.reset_for_retry(state.job_id)
        self.assertEqual(reset.status, "queued")
        self.assertEqual(reset.progress, 0)
        self.assertIsNone(reset.error)

    def test_trace_has_versions_and_job_id(self) -> None:
        state, _ = self.store.reserve(
            job_id="abc12345",
            idempotency_key="key-5",
            source_name="sample.md",
            source_sha256="sha",
            doc_path=str(self.doc),
            options={"ocr": "mock", "extractor": "mock", "template": "enterprise"},
        )
        run_job(self.store, state.job_id, self.settings)
        trace = json.loads((Path(state.out_dir) / "trace.json").read_text(encoding="utf-8"))
        self.assertEqual(trace["job_id"], state.job_id)
        self.assertEqual(trace["versions"]["ocr"], "mock")
        self.assertEqual(trace["versions"]["extractor"], "mock")
        self.assertIn("artifact_manifest", trace)


if __name__ == "__main__":
    unittest.main()
