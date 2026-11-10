"""FastAPI job API tests using TestClient."""

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

SAMPLE_MD = """# Page 1

# Q/Du 302-2015

表1 室温力学性能

<table>
<tr><td>牌号</td><td>抗拉强度Rm/MPa(不小于)</td><td>断后伸长率A/%(不小于)</td></tr>
<tr><td>2A14</td><td>430</td><td>10</td></tr>
</table>
"""

REPO_ROOT = Path(__file__).resolve().parents[1]


def make_settings(root: Path, project_root: Path | None = None) -> Settings:
    return Settings(
        project_root=project_root or root,
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
        business_dictionary_override_path=str(root / "no-override.json"),
    )


@unittest.skipUnless(API_AVAILABLE, "FastAPI is not installed")
class ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.client = TestClient(create_app(make_settings(self.root)))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _create(self, template: str = "enterprise") -> dict:
        response = self.client.post(
            "/v1/jobs",
            data={"template": template, "ocr": "mock", "extractor": "mock"},
            files={"file": ("Q-Du 302-2015.md", SAMPLE_MD.encode("utf-8"), "text/markdown")},
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_health(self) -> None:
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_job_lifecycle_and_artifacts(self) -> None:
        state = self._create()
        job_id = state["job_id"]

        status = self.client.get(f"/v1/jobs/{job_id}")
        self.assertEqual(status.status_code, 200)
        self.assertIn(status.json()["status"], {"review", "succeeded"})
        self.assertEqual(status.json()["progress"], 100)

        result = self.client.get(f"/v1/jobs/{job_id}/result")
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(len(result.json()["records"]), 1)

        evidence = self.client.get(f"/v1/jobs/{job_id}/evidence")
        self.assertEqual(evidence.status_code, 200)
        self.assertEqual(len(evidence.json()), 2)

        audit = self.client.get(f"/v1/jobs/{job_id}/audit")
        self.assertEqual(audit.status_code, 200)
        self.assertIn("审核报告", audit.text)

        trace = self.client.get(f"/v1/jobs/{job_id}/trace")
        self.assertEqual(trace.status_code, 200)
        self.assertEqual(trace.json()["job_id"], job_id)

        artifacts = self.client.get(f"/v1/jobs/{job_id}/artifacts")
        self.assertEqual(artifacts.status_code, 200)
        paths = {item["path"] for item in artifacts.json()["artifacts"]}
        self.assertIn("result.json", paths)
        self.assertIn("evidence.jsonl", paths)

        verify = self.client.get(f"/v1/jobs/{job_id}/artifacts/verify")
        self.assertEqual(verify.status_code, 200)
        self.assertTrue(verify.json()["ok"])

        listing = self.client.get("/v1/jobs")
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.json()[0]["job_id"], job_id)

        recipes = self.client.get("/v1/recipes")
        names = {item["name"] for item in recipes.json()}
        self.assertIn("enterprise", names)

    def test_job_lane_filter(self) -> None:
        response = self.client.post(
            "/v1/jobs",
            data={
                "template": "enterprise",
                "ocr": "mock",
                "extractor": "mock",
                "lane": "explore",
            },
            files={"file": ("Q-Du 302-2015.md", SAMPLE_MD.encode("utf-8"), "text/markdown")},
        )
        self.assertEqual(response.status_code, 201, response.text)
        state = response.json()
        self.assertEqual(state["lane"], "explore")

        explore = self.client.get("/v1/jobs", params={"lane": "explore"})
        self.assertEqual(explore.status_code, 200)
        self.assertTrue(
            any(item["job_id"] == state["job_id"] for item in explore.json())
        )
        production = self.client.get("/v1/jobs", params={"lane": "production"})
        self.assertFalse(
            any(item["job_id"] == state["job_id"] for item in production.json())
        )

        bad = self.client.get("/v1/jobs", params={"lane": "bogus"})
        self.assertEqual(bad.status_code, 422)
        bad_create = self.client.post(
            "/v1/jobs",
            data={"template": "enterprise", "ocr": "mock", "extractor": "mock", "lane": "bogus"},
            files={"file": ("Q-Du 302-2015.md", SAMPLE_MD.encode("utf-8"), "text/markdown")},
        )
        self.assertEqual(bad_create.status_code, 422)

    def test_business_alignment_endpoints(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            client = TestClient(create_app(make_settings(root, REPO_ROOT)))
            response = client.post(
                "/v1/jobs",
                data={"template": "enterprise", "ocr": "mock", "extractor": "mock"},
                files={
                    "file": (
                        "Q-Du 302-2015.md",
                        SAMPLE_MD.encode("utf-8"),
                        "text/markdown",
                    )
                },
            )
            self.assertEqual(response.status_code, 201, response.text)
            job_id = response.json()["job_id"]

            items = client.get(f"/v1/jobs/{job_id}/items")
            self.assertEqual(items.status_code, 200)
            self.assertTrue(items.json()["items"])

            alignment = client.get(f"/v1/jobs/{job_id}/alignment")
            self.assertEqual(alignment.status_code, 200)
            payload = alignment.json()
            self.assertTrue(payload["dictionary_version"].startswith("hanson-"))
            self.assertEqual(
                payload["summary"]["categories_total"],
                len(items.json()["items"]),
            )

            new_terms = client.get(f"/v1/jobs/{job_id}/new-terms")
            self.assertEqual(new_terms.status_code, 200)

            dictionary = client.get(
                "/v1/business-dictionary?type=category&limit=5"
            )
            self.assertEqual(dictionary.status_code, 200)
            self.assertGreater(
                dictionary.json()["counts"]["categories"], 0
            )
            self.assertEqual(len(dictionary.json()["entries"]), 5)

    def test_idempotent_upload(self) -> None:
        first = self._create()
        second = self.client.post(
            "/v1/jobs",
            data={"template": "enterprise", "ocr": "mock", "extractor": "mock"},
            files={"file": ("other-name.md", SAMPLE_MD.encode("utf-8"), "text/markdown")},
        )
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.headers.get("X-Idempotent-Replay"), "true")
        self.assertEqual(second.json()["job_id"], first["job_id"])

    def test_different_options_create_new_job(self) -> None:
        first = self._create()
        second = self.client.post(
            "/v1/jobs",
            data={"template": "product_full", "ocr": "mock", "extractor": "mock"},
            files={"file": ("sample.md", SAMPLE_MD.encode("utf-8"), "text/markdown")},
        )
        self.assertEqual(second.status_code, 201)
        self.assertNotEqual(second.json()["job_id"], first["job_id"])

    def test_invalid_upload_and_unknown_job(self) -> None:
        bad = self.client.post(
            "/v1/jobs",
            files={"file": ("notes.txt", b"text", "text/plain")},
        )
        self.assertEqual(bad.status_code, 415)
        missing = self.client.get("/v1/jobs/deadbeef0000")
        self.assertEqual(missing.status_code, 404)

    def test_retry_rejects_succeeded_job(self) -> None:
        state = self._create(template="classification")
        current = self.client.get(f"/v1/jobs/{state['job_id']}")
        self.assertEqual(current.json()["status"], "succeeded")
        retry = self.client.post(f"/v1/jobs/{state['job_id']}/retry")
        self.assertEqual(retry.status_code, 409)


if __name__ == "__main__":
    unittest.main()
