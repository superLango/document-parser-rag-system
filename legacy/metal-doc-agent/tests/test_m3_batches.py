"""M3.4 batch API: create, aggregate status, idempotent replay."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

try:
    from fastapi.testclient import TestClient

    from metal_doc_agent.api import create_app

    API_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    API_AVAILABLE = False

from metal_doc_agent.settings import Settings

ROOT = Path(__file__).resolve().parents[1]

SAMPLE = """# Page 1

## 4.5 室温力学性能

表1 力学性能

<table>
<tr><td>牌号</td><td>规格</td><td>状态</td><td>室温拉伸Rm/MPa</td><td>室温拉伸Rp0.2/MPa</td><td>室温拉伸A/%</td><td>冲击KU2/J</td><td>持久试验温度/℃</td><td>持久时间/h</td></tr>
<tr><td>2A14</td><td>10</td><td>T6</td><td>430</td><td>350</td><td>10</td><td>25</td><td>20</td><td>100</td></tr>
</table>
"""


def make_settings(root: Path, *, orchestrate: bool = False) -> Settings:
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
        layout_service_url=None,
        business_dictionary_override_path=str(root / "no-override.json"),
        orchestrate=orchestrate,
    )


@unittest.skipUnless(API_AVAILABLE, "fastapi not installed")
class BatchApiTests(unittest.TestCase):
    def _client(self, root: Path) -> TestClient:
        return TestClient(create_app(make_settings(root)))

    def test_batch_runs_jobs_and_aggregates_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "a.md"
            second = root / "b.md"
            first.write_text(SAMPLE, encoding="utf-8")
            second.write_text(SAMPLE.replace("2A14", "5A06"), encoding="utf-8")
            client = self._client(root)
            response = client.post(
                "/v1/batches",
                json={"items": [{"path": str(first)}, {"path": str(second)}]},
            )
            self.assertEqual(response.status_code, 201)
            batch = response.json()
            self.assertEqual(len(batch["items"]), 2)
            self.assertIn(
                batch["status"], {"queued", "running", "review", "succeeded", "partial"}
            )
            fetched = client.get(f"/v1/batches/{batch['batch_id']}")
            self.assertEqual(fetched.status_code, 200)
            self.assertEqual(fetched.json()["batch_id"], batch["batch_id"])
            self.assertIn(fetched.json()["status"], {"review", "succeeded", "partial"})
            self.assertEqual(fetched.json()["summary"].get("failed", 0), 0)
            listing = client.get("/v1/batches").json()
            self.assertEqual(listing[0]["batch_id"], batch["batch_id"])

    def test_batch_idempotency_key_replays(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            doc = root / "b.md"
            doc.write_text(SAMPLE, encoding="utf-8")
            client = self._client(root)
            payload = {"items": [{"path": str(doc)}], "idempotency_key": "batch-key-1"}
            first = client.post("/v1/batches", json=payload)
            self.assertEqual(first.status_code, 201)
            second = client.post("/v1/batches", json=payload)
            self.assertEqual(second.status_code, 200)
            self.assertEqual(second.headers.get("X-Idempotent-Replay"), "true")
            self.assertEqual(first.json()["batch_id"], second.json()["batch_id"])

    def test_batch_rejects_bad_items(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            client = self._client(root)
            self.assertEqual(client.post("/v1/batches", json={"items": []}).status_code, 422)
            missing = client.post("/v1/batches", json={"items": [{"path": str(root / "nope.md")}]})
            self.assertEqual(missing.status_code, 422)
            self.assertEqual(client.get("/v1/batches/doesnotexist").status_code, 404)


@unittest.skipUnless(API_AVAILABLE, "fastapi not installed")
class OrchestratedJobApiTests(unittest.TestCase):
    def test_job_runs_graph_and_resumes_from_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            client = TestClient(create_app(make_settings(root, orchestrate=True)))
            created = client.post(
                "/v1/jobs",
                data={"template": "product_full", "ocr": "mock", "extractor": "mock"},
                files={"file": ("m3.md", SAMPLE.encode("utf-8"), "text/markdown")},
            )
            self.assertEqual(created.status_code, 201)
            job_id = created.json()["job_id"]
            state = client.get(f"/v1/jobs/{job_id}").json()
            self.assertEqual(state["status"], "review")
            self.assertEqual(state["summary"]["orchestrated"], 1)
            self.assertTrue((Path(state["out_dir"]) / "m3_state.json").exists())
            resumed = client.post(f"/v1/jobs/{job_id}/resume")
            self.assertEqual(resumed.status_code, 202)
            final = client.get(f"/v1/jobs/{job_id}").json()
            self.assertEqual(final["status"], "succeeded")
            m3 = json.loads(
                (Path(final["out_dir"]) / "m3_state.json").read_text(encoding="utf-8")
            )
            self.assertEqual(m3["status"], "published")
            self.assertEqual(m3["route"]["queue"], "production")


if __name__ == "__main__":
    unittest.main()
