import json
import tempfile
import unittest
from pathlib import Path

from metal_doc_agent.jobs import JobStore
from tools.sla_probe import main


class SlaProbeTests(unittest.TestCase):
    def test_insufficient_and_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = JobStore(root / "jobs")
            for index in range(3):
                state, _ = store.reserve(
                    job_id=f"slajob{index:03d}",
                    idempotency_key=f"sla-{index}",
                    source_name="doc.md",
                    source_sha256="sha",
                    doc_path=str(root / "doc.md"),
                    options={"ocr": "mock", "extractor": "mock"},
                )
                out_dir = Path(state.out_dir)
                out_dir.mkdir(parents=True, exist_ok=True)
                (out_dir / "metrics.json").write_text(
                    json.dumps({"pipeline_seconds": 10.0}), encoding="utf-8"
                )
                store.update(state.job_id, status="running", stage="starting")
                store.update(state.job_id, status="succeeded", stage="done", progress=100)

            out = root / "sla.json"
            md = root / "sla.md"
            main(
                [
                    "--jobs",
                    str(root / "jobs"),
                    "--min-jobs",
                    "10",
                    "--out",
                    str(out),
                    "--md",
                    str(md),
                ]
            )
            report = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "insufficient_data")
            self.assertEqual(report["window"]["sampled_jobs"], 3)

            main(
                [
                    "--jobs",
                    str(root / "jobs"),
                    "--min-jobs",
                    "3",
                    "--out",
                    str(out),
                    "--md",
                    str(md),
                ]
            )
            report = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "pass")
            self.assertEqual(report["availability"], 1.0)
            self.assertLessEqual(report["p95_ms"], 300_000.0)


if __name__ == "__main__":
    unittest.main()
