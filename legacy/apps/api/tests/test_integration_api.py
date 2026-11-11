"""hansonDoc_RAG 一站式对接兼容接口测试（mock 引擎，不启动真实模型）。"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

PROJECT = Path(__file__).resolve().parents[3]
API_DIR = Path(__file__).resolve().parents[1]
ENGINE_DIR = PROJECT / "metal-doc-agent"
for path in (str(API_DIR), str(ENGINE_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)

from hanson_api.app import build_app  # noqa: E402
from hanson_api.bootstrap import create_user  # noqa: E402
from hanson_api.config import PlatformSettings  # noqa: E402
from hanson_api.db import build_session_factory  # noqa: E402
from hanson_api.models import (  # noqa: E402
    Document,
    DocumentTask,
    IntegrationTask,
    User,
    new_id,
)
from hanson_api.router import create_platform_router  # noqa: E402
from metal_doc_agent.jobs import JobStore  # noqa: E402
from metal_doc_agent.settings import Settings  # noqa: E402

PROMPT_ID = "326d7916-7a5f-48cb-93f6-669b69744b7d"
SCHEMA_TEMPLATE_ID = "6e2ad0d7-f92a-4663-b5cf-ae01c2378fa7"


class IntegrationApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(self.tmp.name)
        data_dir = root / "platform"
        engine_data = root / "engine"
        engine_root = root / "engine_root"
        (engine_root / "configs").mkdir(parents=True, exist_ok=True)
        shutil.copyfile(
            ENGINE_DIR / "configs" / "business_dictionary.hanson.json",
            engine_root / "configs" / "business_dictionary.hanson.json",
        )
        template_dir = engine_root / "configs" / "schema_templates"
        template_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(
            ENGINE_DIR / "configs" / "schema_templates" / "product_standard.json",
            template_dir / "product_standard.json",
        )
        self.settings = PlatformSettings(
            data_dir=data_dir,
            database_url=f"sqlite:///{(data_dir / 'platform.db').as_posix()}",
            secret_key="test-secret-key",
            upload_dir=data_dir / "uploads",
            engine_data_dir=engine_data,
            engine_root=engine_root,
            require_auth=True,
        )
        self.engine_settings = Settings(
            project_root=ENGINE_DIR,
            data_dir=engine_data,
            ocr_backend="mock",
            extractor_backend="mock",
            glm_ocr_base_url=None,
            glm_ocr_model="GLM-OCR",
            qwen_base_url=None,
            qwen_model="Qwen3.5-9B",
            api_key=None,
            request_timeout=10.0,
        )
        create_user(self.settings, "tester", "secret123", display_name="测试用户")
        self.app = build_app(self.settings, self.engine_settings)
        self.client = TestClient(self.app)
        self.client.__enter__()
        login = self.client.post(
            "/v1/auth/login",
            json={"username": "tester", "password": "secret123"},
        )
        self.assertEqual(login.status_code, 200, login.text)
        self.headers = {
            "Authorization": f"Bearer {login.json()['access_token']}"
        }
        self.kb_id = self._create_kb()

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)
        engine = getattr(
            self.app.state.platform_router, "_platform_engine", None
        )
        if engine is not None:
            engine.dispose()
        self.tmp.cleanup()

    def _create_kb(self) -> str:
        response = self.client.post(
            "/v1/knowledge-bases",
            json={"name": "对接测试库"},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["id"]

    def _seed_completed_task(self) -> str:
        """Create a completed job artifact set + integration task in SQLite."""

        data_dir = Path(self.engine_settings.data_dir)
        store = JobStore(data_dir / "jobs")
        pdf = data_dir / "demo.pdf"
        pdf.parent.mkdir(parents=True, exist_ok=True)
        pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
        state, _ = store.reserve(
            job_id="intjob000001",
            idempotency_key="integration-test",
            source_name="demo.pdf",
            source_sha256="a" * 64,
            doc_path=str(pdf),
            options={},
        )
        out_dir = Path(state.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "result.json").write_text(
            json.dumps(
                {
                    "document": {
                        "doc_id": "integration-doc",
                        "source_path": str(pdf),
                        "file_name": "demo.pdf",
                        "standard_no": "GB/T 1220-2007",
                        "title": "不锈钢棒",
                    },
                    "records": [],
                    "inspection_items": [],
                    "classification_items": [],
                    "clauses": [],
                    "tables": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (out_dir / "item_inventory_aligned.json").write_text(
            json.dumps({"doc_id": "integration-doc", "items": []}),
            encoding="utf-8",
        )
        (out_dir / "trace.json").write_text(
            json.dumps({"elapsed_ms": 1234}), encoding="utf-8"
        )
        state.status = "review"
        state.stage = "done"
        state.progress = 100
        store.save(state)

        factory = build_session_factory(
            self.app.state.platform_router._platform_engine
        )
        with factory() as db:
            user = db.scalar(select(User).where(User.username == "tester"))
            document = Document(
                id=new_id(),
                kb_id=self.kb_id,
                file_name="demo.pdf",
                source_path=str(pdf),
                sha256="a" * 64,
                status="review",
                job_id=state.job_id,
                created_by=user.id,
            )
            db.add(document)
            db.flush()
            db.add(
                DocumentTask(
                    document_id=document.id,
                    job_id=state.job_id,
                    version=3,
                )
            )
            task = IntegrationTask(
                task_id=str(uuid.uuid4()),
                kb_id=self.kb_id,
                document_id=document.id,
                prompt_id=PROMPT_ID,
                schema_template_id=SCHEMA_TEMPLATE_ID,
                filename="demo.pdf",
                ocr_status="processing",
                extract_status="pending",
                created_by=user.id,
            )
            db.add(task)
            db.commit()
            return task.task_id

    def test_upload_keeps_legacy_path_and_envelope(self) -> None:
        response = self.client.post(
            "/api/v1/integration/upload",
            params={
                "kb_id": str(uuid.UUID(self.kb_id)),
                "prompt_id": PROMPT_ID,
            },
            files={
                "file": (
                    "demo.pdf",
                    b"%PDF-1.4\n%%EOF\n",
                    "application/pdf",
                )
            },
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["code"], 0)
        self.assertTrue(body["trace_id"])
        data = body["data"]
        self.assertTrue(data["task_id"])
        self.assertEqual(data["schema_template_id"], SCHEMA_TEMPLATE_ID)
        self.assertEqual(data["prompt_id"], PROMPT_ID)
        # 兼容旧 UUID 形态，同时保留平台内部 32 位 ID 可用性。
        self.assertIn("-", data["kb_id"])
        self.assertIn("-", data["document_id"])
        self.assertEqual(data["filename"], "demo.pdf")
        self.assertIn(data["ocr_status"], {"pending", "processing", "completed"})
        self.assertIn(data["extract_status"], {"pending", "queued", "failed"})

        status = self.client.get(
            f"/api/v1/integration/tasks/{data['task_id']}/status"
        )
        self.assertEqual(status.status_code, 200, status.text)
        self.assertEqual(status.json()["code"], 0)
        self.assertEqual(status.json()["data"]["task_id"], data["task_id"])

    def test_upload_requires_auth_and_pdf(self) -> None:
        unauth = self.client.post(
            "/api/v1/integration/upload",
            params={"kb_id": self.kb_id, "prompt_id": PROMPT_ID},
            files={"file": ("demo.pdf", b"%PDF-1.4\n", "application/pdf")},
        )
        self.assertEqual(unauth.status_code, 401, unauth.text)
        self.assertEqual(unauth.json()["code"], 20001)

        not_pdf = self.client.post(
            "/api/v1/integration/upload",
            params={"kb_id": self.kb_id, "prompt_id": PROMPT_ID},
            files={"file": ("demo.txt", b"hello", "text/plain")},
            headers=self.headers,
        )
        self.assertEqual(not_pdf.status_code, 400, not_pdf.text)
        self.assertEqual(not_pdf.json()["code"], 10001)
        self.assertEqual(not_pdf.json()["message"], "仅支持 PDF 文件")

        missing = self.client.post(
            "/api/v1/integration/upload",
            params={"kb_id": self.kb_id},
            files={"file": ("demo.pdf", b"%PDF-1.4\n", "application/pdf")},
            headers=self.headers,
        )
        self.assertEqual(missing.status_code, 400, missing.text)
        self.assertEqual(missing.json()["code"], 10001)

    def test_status_and_result_for_completed_task(self) -> None:
        task_id = self._seed_completed_task()

        status = self.client.get(
            f"/api/v1/integration/tasks/{task_id}/status"
        )
        self.assertEqual(status.status_code, 200, status.text)
        payload = status.json()
        self.assertEqual(payload["code"], 0)
        data = payload["data"]
        self.assertEqual(data["ocr_status"], "completed")
        self.assertEqual(data["extract_status"], "completed")
        self.assertEqual(data["ocr_progress"], 100)
        self.assertEqual(data["extract_progress"], 100)
        self.assertEqual(data["result_version"], 3)

        result = self.client.get(
            f"/api/v1/integration/tasks/{task_id}/result"
        )
        self.assertEqual(result.status_code, 200, result.text)
        body = result.json()
        self.assertEqual(body["code"], 0)
        result_data = body["data"]
        self.assertEqual(result_data["status"], "completed")
        self.assertEqual(result_data["schema_template_id"], SCHEMA_TEMPLATE_ID)
        self.assertEqual(result_data["schema_name"], "产品标准抽取模板")
        self.assertEqual(result_data["version"], 3)
        self.assertGreaterEqual(len(result_data["categories"]), 1)
        self.assertIn("total_records", result_data["summary"])
        self.assertEqual(result_data["timing"]["total_sec"], 1.23)
        self.assertIsNone(result_data["error"])

    def test_session_token_and_unknown_task(self) -> None:
        task_id = self._seed_completed_task()
        token = self.client.get(
            f"/api/v1/integration/tasks/{task_id}/session-token"
        )
        self.assertEqual(token.status_code, 200, token.text)
        data = token.json()["data"]
        self.assertEqual(data["task_id"], task_id)
        self.assertTrue(data["token"])
        self.assertTrue(data["path"].startswith("/share/"))
        self.assertIn("-", data["document_id"])

        missing = self.client.get(
            f"/api/v1/integration/tasks/{uuid.uuid4()}/status"
        )
        self.assertEqual(missing.status_code, 404, missing.text)
        self.assertEqual(missing.json()["code"], 30017)
        self.assertEqual(missing.json()["message"], "对接任务不存在")

    def test_retrigger_requires_auth(self) -> None:
        task_id = self._seed_completed_task()
        unauth = self.client.post(
            f"/api/v1/integration/tasks/{task_id}/retrigger"
        )
        self.assertEqual(unauth.status_code, 401, unauth.text)
        self.assertEqual(unauth.json()["code"], 20001)

    def test_legacy_response_shapes(self) -> None:
        """上传/状态/结果字段与 hansonDoc_RAG 旧契约保持一致。"""

        upload = self.client.post(
            "/api/v1/integration/upload",
            params={
                "kb_id": str(uuid.UUID(self.kb_id)),
                "prompt_id": PROMPT_ID,
            },
            files={"file": ("demo.pdf", b"%PDF-1.4\n%%EOF\n", "application/pdf")},
            headers=self.headers,
        )
        self.assertEqual(upload.status_code, 200, upload.text)
        upload_data = upload.json()["data"]
        self.assertEqual(
            set(upload_data),
            {
                "task_id",
                "kb_id",
                "document_id",
                "prompt_id",
                "schema_template_id",
                "filename",
                "ocr_status",
                "ocr_progress",
                "extract_status",
                "extract_progress",
                "error",
                "result_version",
                "created_at",
                "updated_at",
            },
        )

        task_id = self._seed_completed_task()
        status_data = self.client.get(
            f"/api/v1/integration/tasks/{task_id}/status"
        ).json()["data"]
        for field in (
            "task_id",
            "document_id",
            "filename",
            "ocr_status",
            "ocr_progress",
            "extract_status",
            "extract_progress",
            "error",
            "result_version",
        ):
            self.assertIn(field, status_data)

        result_data = self.client.get(
            f"/api/v1/integration/tasks/{task_id}/result"
        ).json()["data"]
        self.assertEqual(
            set(result_data),
            {
                "schema_template_id",
                "schema_name",
                "status",
                "progress",
                "categories",
                "summary",
                "timing",
                "version",
                "error",
                "updated_at",
            },
        )
        self.assertIn("total_records", result_data["summary"])
        self.assertIn("kept_categories", result_data["summary"])
        for category in result_data["categories"]:
            self.assertEqual(
                set(category),
                {"feature", "records", "rejected", "missing_fields", "hit_count"},
            )
            self.assertIsInstance(category["records"], list)
            self.assertIsInstance(category["rejected"], list)
            self.assertIsInstance(category["missing_fields"], list)
            self.assertEqual(category["hit_count"], len(category["records"]))

    def test_retrigger_reuses_task_id_with_auth(self) -> None:
        task_id = self._seed_completed_task()
        response = self.client.post(
            f"/api/v1/integration/tasks/{task_id}/retrigger",
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["code"], 0)
        self.assertEqual(body["data"]["task_id"], task_id)
        self.assertIn(
            body["data"]["ocr_status"],
            {"pending", "processing", "completed"},
        )
        self.assertIn(
            body["data"]["extract_status"],
            {"pending", "queued", "running", "completed", "failed"},
        )

    def test_task_errors_keep_legacy_codes(self) -> None:
        for path in ("status", "result", "session-token"):
            response = self.client.get(
                f"/api/v1/integration/tasks/{uuid.uuid4()}/{path}"
            )
            self.assertEqual(response.status_code, 404, response.text)
            self.assertEqual(response.json()["code"], 30017)
            self.assertEqual(response.json()["message"], "对接任务不存在")

        invalid = self.client.get(
            "/api/v1/integration/tasks/not-a-uuid/status"
        )
        self.assertEqual(invalid.status_code, 400, invalid.text)
        self.assertEqual(invalid.json()["code"], 10001)

    def test_session_token_supports_result_page_export(self) -> None:
        """对接页「导出」使用只读分享令牌，不依赖登录态。"""

        task_id = self._seed_completed_task()
        token_data = self.client.get(
            f"/api/v1/integration/tasks/{task_id}/session-token"
        ).json()["data"]
        token = token_data["token"]

        bundle = self.client.get(f"/v1/share/{token}")
        self.assertEqual(bundle.status_code, 200, bundle.text)
        self.assertEqual(bundle.json()["document"]["file_name"], "demo.pdf")

        exported = self.client.get(f"/v1/share/{token}/export?format=json")
        self.assertEqual(exported.status_code, 200, exported.text)
        self.assertGreater(len(exported.content), 10)

    def test_no_auth_mode_disables_all_checks(self) -> None:
        """``HANSON_REQUIRE_AUTH=false`` 时所有接口不做鉴权/授权。"""

        from dataclasses import replace

        settings = replace(self.settings, require_auth=False)
        app = build_app(settings, self.engine_settings)
        client = TestClient(app)
        client.__enter__()
        try:
            # 无效凭证也不应触发 401；统一按内嵌访客处理。
            bad_headers = {
                "Authorization": "Bearer broken-token",
                "X-API-Key": "not-a-real-key",
            }

            workspaces = client.get("/v1/workspaces", headers=bad_headers)
            self.assertEqual(workspaces.status_code, 200, workspaces.text)
            self.assertTrue(workspaces.json())

            kbs = client.get("/v1/knowledge-bases", headers=bad_headers)
            self.assertEqual(kbs.status_code, 200, kbs.text)
            self.assertIn(self.kb_id, [row["id"] for row in kbs.json()])

            created = client.post(
                "/v1/knowledge-bases",
                json={"name": "免登录知识库"},
                headers=bad_headers,
            )
            self.assertEqual(created.status_code, 201, created.text)
            self.assertEqual(created.json()["role"], "owner")

            users = client.get("/v1/users", headers=bad_headers)
            self.assertEqual(users.status_code, 200, users.text)

            keys = client.get("/v1/api-keys", headers=bad_headers)
            self.assertEqual(keys.status_code, 200, keys.text)

            upload = client.post(
                "/api/v1/integration/upload",
                params={
                    "kb_id": str(uuid.UUID(self.kb_id)),
                    "prompt_id": PROMPT_ID,
                },
                files={
                    "file": (
                        "anonymous.pdf",
                        b"%PDF-1.4\n%%EOF\n",
                        "application/pdf",
                    )
                },
                headers=bad_headers,
            )
            self.assertEqual(upload.status_code, 200, upload.text)
            task_id = upload.json()["data"]["task_id"]

            retrigger = client.post(
                f"/api/v1/integration/tasks/{task_id}/retrigger",
                headers=bad_headers,
            )
            self.assertEqual(retrigger.status_code, 200, retrigger.text)
        finally:
            client.__exit__(None, None, None)
            engine = getattr(
                app.state.platform_router, "_platform_engine", None
            )
            if engine is not None:
                engine.dispose()


if __name__ == "__main__":
    unittest.main()
