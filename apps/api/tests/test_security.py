"""R2 security boundary tests: engine route closure, login limits, cross-KB."""

from __future__ import annotations

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
from hanson_api.security import create_access_token, create_share_token  # noqa: E402
from metal_doc_agent.settings import Settings  # noqa: E402

SAMPLE_MD = """# Page 1

表1 室温力学性能

<table>
<tr><td>牌号</td><td>抗拉强度Rm/MPa(不小于)</td><td>断后伸长率A/%(不小于)</td></tr>
<tr><td>2A14</td><td>430</td><td>10</td></tr>
</table>
"""


class SecurityBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        engine_root = root / "engine_root"
        (engine_root / "configs").mkdir(parents=True, exist_ok=True)
        shutil.copyfile(
            ENGINE_DIR / "configs" / "business_dictionary.hanson.json",
            engine_root / "configs" / "business_dictionary.hanson.json",
        )
        self.root = root
        self.settings = PlatformSettings(
            data_dir=root / "platform",
            database_url=f"sqlite:///{(root / 'platform' / 'platform.db').as_posix()}",
            secret_key="security-test-secret-key-0123456789abcdef",
            upload_dir=root / "platform" / "uploads",
            engine_data_dir=root / "engine",
            engine_root=engine_root,
            login_max_failures=3,
            login_window_seconds=60,
            login_lockout_seconds=1,
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
        create_user(self.settings, "user_a", "pass-a", display_name="A")
        create_user(self.settings, "user_b", "pass-b", display_name="B")
        create_user(self.settings, "limited", "pass-limit", display_name="Limited")
        self.app = build_app(self.settings, self.engine_settings)
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.headers_a = self._login("user_a", "pass-a")
        self.headers_b = self._login("user_b", "pass-b")

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)
        self.tmp.cleanup()

    def _login(self, username: str, password: str) -> dict[str, str]:
        response = self.client.post(
            "/v1/auth/login",
            json={"username": username, "password": password},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    def _create_kb(self, headers: dict[str, str], name: str) -> str:
        response = self.client.post(
            "/v1/knowledge-bases",
            headers=headers,
            json={"name": name, "description": ""},
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["id"]

    def _upload(self, headers: dict[str, str], kb_id: str) -> dict:
        response = self.client.post(
            "/v1/documents",
            headers=headers,
            data={"kb_id": kb_id},
            files={"file": ("sample.md", SAMPLE_MD, "text/markdown")},
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def _parse(self, headers: dict[str, str], document_id: str) -> dict:
        response = self.client.post(
            f"/v1/documents/{document_id}/parse", headers=headers
        )
        self.assertEqual(response.status_code, 202, response.text)
        return response.json()

    def test_engine_data_routes_closed_by_default(self) -> None:
        for path in ("/v1/jobs", "/v1/batches", "/v1/recipes"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 404, f"{path}: {response.text}")
        response = self.client.get("/v1/business-dictionary")
        self.assertEqual(response.status_code, 401, response.text)

    def test_engine_routes_require_token_when_exposed(self) -> None:
        exposed = build_app(
            self.settings,
            self.engine_settings,
            engine_internal_token="engine-test-token",
        )
        with TestClient(exposed) as client:
            self.assertEqual(client.get("/v1/jobs").status_code, 401)
            self.assertEqual(
                client.get(
                    "/v1/jobs", headers={"X-Engine-Token": "wrong"}
                ).status_code,
                401,
            )
            self.assertEqual(
                client.get(
                    "/v1/jobs", headers={"X-Engine-Token": "engine-test-token"}
                ).status_code,
                200,
            )
            self.assertEqual(client.get("/v1/business-dictionary").status_code, 401)

    def test_security_headers_on_success_and_auth_errors(self) -> None:
        for response in (
            self.client.get("/health"),
            self.client.get("/v1/knowledge-bases"),
        ):
            self.assertEqual(response.headers.get("X-Content-Type-Options"), "nosniff")
            self.assertEqual(response.headers.get("X-Frame-Options"), "DENY")
            self.assertEqual(response.headers.get("Referrer-Policy"), "no-referrer")

    def test_problem_json_error_envelope(self) -> None:
        unauthorized = self.client.get("/v1/knowledge-bases")
        self.assertEqual(unauthorized.status_code, 401)
        self.assertEqual(
            unauthorized.headers.get("Content-Type"), "application/problem+json"
        )
        body = unauthorized.json()
        self.assertEqual(body["status"], 401)
        self.assertIn("title", body)
        self.assertIn("detail", body)
        self.assertEqual(body["instance"], "/v1/knowledge-bases")

        invalid = self.client.post("/v1/auth/login", json={"username": "user_a"})
        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(
            invalid.headers.get("Content-Type"), "application/problem+json"
        )
        self.assertIsInstance(invalid.json()["detail"], list)

    def test_expired_and_tampered_access_tokens(self) -> None:
        me = self.client.get("/v1/auth/me", headers=self.headers_a).json()
        user_id = me["user"]["id"]
        expired = create_access_token(self.settings.secret_key, user_id, -1)
        self.assertEqual(
            self.client.get(
                "/v1/knowledge-bases",
                headers={"Authorization": f"Bearer {expired}"},
            ).status_code,
            401,
        )
        valid = self.headers_a["Authorization"].split(" ", 1)[1]
        tampered = valid[:-1] + ("A" if valid[-1] != "A" else "B")
        self.assertEqual(
            self.client.get(
                "/v1/knowledge-bases",
                headers={"Authorization": f"Bearer {tampered}"},
            ).status_code,
            401,
        )

    def test_login_rate_limit_and_recovery(self) -> None:
        for _ in range(2):
            response = self.client.post(
                "/v1/auth/login",
                json={"username": "limited", "password": "wrong"},
            )
            self.assertEqual(response.status_code, 401, response.text)
        third = self.client.post(
            "/v1/auth/login",
            json={"username": "limited", "password": "wrong"},
        )
        self.assertEqual(third.status_code, 429, third.text)
        self.assertIn("Retry-After", third.headers)
        blocked = self.client.post(
            "/v1/auth/login",
            json={"username": "limited", "password": "pass-limit"},
        )
        self.assertEqual(blocked.status_code, 429, blocked.text)
        time.sleep(1.2)
        recovered = self.client.post(
            "/v1/auth/login",
            json={"username": "limited", "password": "pass-limit"},
        )
        self.assertEqual(recovered.status_code, 200, recovered.text)

    def test_api_key_read_scope_cannot_write(self) -> None:
        kb_id = self._create_kb(self.headers_a, "key-kb")
        document = self._upload(self.headers_a, kb_id)
        key_response = self.client.post(
            "/v1/api-keys",
            headers=self.headers_a,
            json={"name": "read-only", "scopes": ["documents:read"]},
        )
        self.assertEqual(key_response.status_code, 201, key_response.text)
        read_headers = {"X-API-Key": key_response.json()["key"]}
        self.assertEqual(
            self.client.get(
                f"/v1/documents?kb_id={kb_id}", headers=read_headers
            ).status_code,
            200,
        )
        denied = self.client.post(
            f"/v1/documents/{document['id']}/parse", headers=read_headers
        )
        self.assertEqual(denied.status_code, 403, denied.text)

    def test_cross_kb_document_task_and_evidence_forbidden(self) -> None:
        kb_id = self._create_kb(self.headers_a, "A 知识库")
        document = self._upload(self.headers_a, kb_id)
        task = self._parse(self.headers_a, document["id"])
        self.assertEqual(
            self.client.get(
                f"/v1/documents/{document['id']}", headers=self.headers_b
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.get(
                f"/v1/documents/{document['id']}/evidence", headers=self.headers_b
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                f"/v1/documents/{document['id']}/share", headers=self.headers_b
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.get(
                f"/v1/tasks/{task['job_id']}", headers=self.headers_b
            ).status_code,
            403,
        )
        self.assertEqual(
            len(self.client.get("/v1/tasks", headers=self.headers_b).json()), 0
        )

    def test_share_token_tampered_and_expired(self) -> None:
        kb_id = self._create_kb(self.headers_a, "share-kb")
        document = self._upload(self.headers_a, kb_id)
        token, _ = create_share_token(self.settings.secret_key, document["id"], 5)
        self.assertEqual(
            self.client.get(f"/v1/share/{token}").status_code, 200
        )
        tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
        self.assertEqual(
            self.client.get(f"/v1/share/{tampered}").status_code, 401
        )
        expired, _ = create_share_token(self.settings.secret_key, document["id"], -1)
        self.assertEqual(
            self.client.get(f"/v1/share/{expired}").status_code, 401
        )

    def test_dictionary_requires_authentication(self) -> None:
        self.assertEqual(self.client.get("/v1/business-dictionary").status_code, 401)
        response = self.client.get(
            "/v1/business-dictionary?type=category&limit=5",
            headers=self.headers_a,
        )
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertIn("counts", payload)
        self.assertLessEqual(len(payload["entries"]), 5)


if __name__ == "__main__":
    unittest.main()
