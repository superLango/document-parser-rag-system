"""R3 export tests: hanson schema, CSV, XLSX and share export."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

PROJECT = Path(__file__).resolve().parents[3]
API_DIR = Path(__file__).resolve().parents[1]
ENGINE_DIR = PROJECT / "metal-doc-agent"
for path in (str(API_DIR), str(ENGINE_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)

from hanson_api.app import build_app  # noqa: E402
from hanson_api.bootstrap import create_user  # noqa: E402
from hanson_api.config import PlatformSettings  # noqa: E402
from metal_doc_agent.settings import Settings  # noqa: E402

SAMPLE_MD = """# Page 1

表1 室温力学性能

<table>
<tr><td>牌号</td><td>抗拉强度Rm/MPa(不小于)</td><td>断后伸长率A/%(不小于)</td></tr>
<tr><td>2A14</td><td>430</td><td>10</td></tr>
</table>
"""


class ExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        engine_root = root / "engine_root"
        (engine_root / "configs").mkdir(parents=True, exist_ok=True)
        shutil.copyfile(
            ENGINE_DIR / "configs" / "business_dictionary.hanson.json",
            engine_root / "configs" / "business_dictionary.hanson.json",
        )
        self.settings = PlatformSettings(
            data_dir=root / "platform",
            database_url=f"sqlite:///{(root / 'platform' / 'platform.db').as_posix()}",
            secret_key="export-test-secret-0123456789abcdef",
            upload_dir=root / "platform" / "uploads",
            engine_data_dir=root / "engine",
            engine_root=engine_root,
            require_auth=True,
        )
        self.engine_settings = Settings(
            project_root=ENGINE_DIR,
            data_dir=root / "engine",
            ocr_backend="mock",
            extractor_backend="mock",
            glm_ocr_base_url=None,
            glm_ocr_model="GLM-OCR",
            qwen_base_url=None,
            qwen_model="Qwen3.5-9B",
            api_key=None,
            request_timeout=10.0,
        )
        create_user(self.settings, "admin", "admin-pass", display_name="Admin")
        self.app = build_app(self.settings, self.engine_settings)
        self.client = TestClient(self.app)
        self.client.__enter__()
        login = self.client.post(
            "/v1/auth/login",
            json={"username": "admin", "password": "admin-pass"},
        )
        self.assertEqual(login.status_code, 200, login.text)
        self.headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        kb = self.client.post(
            "/v1/knowledge-bases",
            headers=self.headers,
            json={"name": "导出测试"},
        )
        self.assertEqual(kb.status_code, 201, kb.text)
        self.kb_id = kb.json()["id"]
        document = self.client.post(
            "/v1/documents",
            headers=self.headers,
            data={"kb_id": self.kb_id},
            files={"file": ("sample.md", SAMPLE_MD, "text/markdown")},
        )
        self.assertEqual(document.status_code, 201, document.text)
        self.document_id = document.json()["id"]
        task = self.client.post(
            f"/v1/documents/{self.document_id}/parse", headers=self.headers
        )
        self.assertEqual(task.status_code, 202, task.text)
        self.job_id = task.json()["job_id"]
        deadline = time.time() + 15
        while time.time() < deadline:
            state = self.client.get(
                f"/v1/tasks/{self.job_id}", headers=self.headers
            ).json()
            if state["status"] not in {"queued", "running"}:
                self.assertIn(state["status"], {"succeeded", "review"}, state)
                break
            time.sleep(0.2)
        else:
            self.fail("parse did not finish")

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)
        self.tmp.cleanup()

    def test_hanson_csv_xlsx_exports(self) -> None:
        csv_response = self.client.get(
            f"/v1/documents/{self.document_id}/export?format=csv",
            headers=self.headers,
        )
        self.assertEqual(csv_response.status_code, 200, csv_response.text)
        self.assertIn("类别", csv_response.text)
        self.assertIn("2A14", csv_response.text)
        self.assertNotIn("record_id", csv_response.text)

        xlsx = self.client.get(
            f"/v1/documents/{self.document_id}/export?format=xlsx",
            headers=self.headers,
        )
        self.assertEqual(xlsx.status_code, 200, xlsx.text)
        self.assertTrue(xlsx.content.startswith(b"PK"))

        for legacy in ("hanson", "json"):
            removed = self.client.get(
                f"/v1/documents/{self.document_id}/export?format={legacy}",
                headers=self.headers,
            )
            self.assertEqual(removed.status_code, 422)

        bad = self.client.get(
            f"/v1/documents/{self.document_id}/export?format=pdf",
            headers=self.headers,
        )
        self.assertEqual(bad.status_code, 422)

    def test_share_export(self) -> None:
        share = self.client.post(
            f"/v1/documents/{self.document_id}/share", headers=self.headers
        )
        self.assertEqual(share.status_code, 200, share.text)
        token = share.json()["token"]
        bundle = self.client.get(f"/v1/share/{token}").json()
        self.assertEqual(bundle["document"]["id"], self.document_id)
        owner_records = self.client.get(
            f"/v1/documents/{self.document_id}/records", headers=self.headers
        ).json()
        owner_items = self.client.get(
            f"/v1/documents/{self.document_id}/items", headers=self.headers
        ).json()
        owner_evidence = self.client.get(
            f"/v1/documents/{self.document_id}/evidence", headers=self.headers
        ).json()
        self.assertEqual(len(bundle["records"]), len(owner_records))
        self.assertEqual(
            len(bundle["items"]["items"]), len(owner_items["items"])
        )
        self.assertEqual(len(bundle["evidence"]), len(owner_evidence))
        response = self.client.get(f"/v1/share/{token}/export?format=csv")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("2A14", response.text)
        tampered_token = token[:-1] + ("A" if token[-1] != "A" else "B")
        tampered = self.client.get(
            f"/v1/share/{tampered_token}/export?format=csv"
        )
        self.assertEqual(tampered.status_code, 401)


if __name__ == "__main__":
    unittest.main()
