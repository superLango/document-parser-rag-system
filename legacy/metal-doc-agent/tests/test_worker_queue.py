import tempfile
import unittest
from pathlib import Path

from metal_doc_agent.jobs import JobStore
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


class WorkerQueueTests(unittest.TestCase):
    def test_run_queued_processes_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            doc = root / "sample.md"
            doc.write_text(SAMPLE, encoding="utf-8")
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
            )
            store = JobStore(root / "data" / "jobs")
            state, created = store.reserve(
                job_id="queuejob01",
                idempotency_key="queue-key-1",
                source_name="sample.md",
                source_sha256="sha",
                doc_path=str(doc),
                options={"ocr": "mock", "extractor": "mock"},
            )
            self.assertTrue(created)

            ran = run_queued(store, settings)
            self.assertEqual(ran, [state.job_id])

            after = store.get(state.job_id)
            self.assertIsNotNone(after)
            self.assertIn(after.status, {"succeeded", "review"})
            self.assertTrue((Path(after.out_dir) / "result.json").exists())
            self.assertTrue((Path(after.out_dir) / "alignment.json").exists())
            self.assertFalse(
                [item for item in store.list() if item.status == "queued"]
            )

    def test_pool_only_runs_its_lane(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            doc = root / "sample.md"
            doc.write_text(SAMPLE, encoding="utf-8")
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
            )
            store = JobStore(root / "data" / "jobs")
            production, _ = store.reserve(
                job_id="prodjob001",
                idempotency_key="prod-key",
                source_name="sample.md",
                source_sha256="sha",
                doc_path=str(doc),
                options={"ocr": "mock", "extractor": "mock"},
            )
            explore, _ = store.reserve(
                job_id="explorejob1",
                idempotency_key="explore-key",
                source_name="sample.md",
                source_sha256="sha",
                doc_path=str(doc),
                options={"ocr": "mock", "extractor": "mock"},
                lane="explore",
            )

            ran = run_queued(store, settings, pool="production")
            self.assertEqual(ran, [production.job_id])
            self.assertEqual(store.get(explore.job_id).status, "queued")

            ran = run_queued(store, settings, pool="explore")
            self.assertEqual(ran, [explore.job_id])


if __name__ == "__main__":
    unittest.main()
