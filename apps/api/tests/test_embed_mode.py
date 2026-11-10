"""嵌入式免登录模式测试：默认不要求登录，并返回固定访客身份。"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

PROJECT = Path(__file__).resolve().parents[3]
API_DIR = Path(__file__).resolve().parents[1]
ENGINE_DIR = PROJECT / "metal-doc-agent"
for path in (str(API_DIR), str(ENGINE_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)

from hanson_api.access import default_workspace  # noqa: E402
from hanson_api.app import build_app  # noqa: E402
from hanson_api.bootstrap import create_user  # noqa: E402
from hanson_api.config import PlatformSettings  # noqa: E402
from hanson_api.db import build_session_factory  # noqa: E402
from hanson_api.models import Document, KnowledgeBase, User, new_id  # noqa: E402
from metal_doc_agent.settings import Settings  # noqa: E402


class EmbedModeTests(unittest.TestCase):
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
        self.settings = PlatformSettings(
            data_dir=data_dir,
            database_url=f"sqlite:///{(data_dir / 'platform.db').as_posix()}",
            secret_key="test-secret-key",
            upload_dir=data_dir / "uploads",
            engine_data_dir=engine_data,
            engine_root=engine_root,
            require_auth=False,
            allow_embed=True,
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
        self.app = build_app(self.settings, self.engine_settings)
        self.client = TestClient(self.app)
        self.client.__enter__()

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)
        engine = getattr(
            self.app.state.platform_router, "_platform_engine", None
        )
        if engine is not None:
            engine.dispose()
        self.tmp.cleanup()

    def test_public_config_and_anonymous_principal(self) -> None:
        config = self.client.get("/v1/auth/config")
        self.assertEqual(config.status_code, 200, config.text)
        payload = config.json()
        self.assertFalse(payload["require_auth"])
        self.assertTrue(payload["anonymous"])
        self.assertEqual(payload["anonymous_username"], "embed_guest")

        me = self.client.get("/v1/auth/me")
        self.assertEqual(me.status_code, 200, me.text)
        body = me.json()
        self.assertEqual(body["actor_type"], "user")
        self.assertEqual(body["user"]["username"], "embed_guest")
        self.assertEqual(body["user"]["role"], "editor")

        # 浏览器里残留的过期 token 不应把嵌入页面逼回登录页。
        stale = self.client.get(
            "/v1/auth/me",
            headers={"Authorization": "Bearer expired-token"},
        )
        self.assertEqual(stale.status_code, 200, stale.text)
        self.assertEqual(stale.json()["user"]["username"], "embed_guest")

    def test_anonymous_can_use_business_api(self) -> None:
        listed = self.client.get("/v1/knowledge-bases")
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(listed.json(), [])

        created = self.client.post(
            "/v1/knowledge-bases",
            json={"name": "嵌入式知识库"},
        )
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(created.json()["name"], "嵌入式知识库")

        listed = self.client.get("/v1/knowledge-bases")
        self.assertEqual(len(listed.json()), 1)

    def test_anonymous_can_access_document_from_other_user_kb(self) -> None:
        create_user(self.settings, "owner", "secret123")
        factory = build_session_factory(
            self.app.state.platform_router._platform_engine
        )
        with factory() as db:
            owner = db.scalar(select(User).where(User.username == "owner"))
            workspace = default_workspace(db, owner)
            db.flush()
            kb = KnowledgeBase(
                workspace_id=workspace.id,
                name="外部系统知识库",
                owner_id=owner.id,
            )
            db.add(kb)
            db.flush()
            document = Document(
                id=new_id(),
                kb_id=kb.id,
                file_name="external.pdf",
                source_path=str(Path(self.tmp.name) / "external.pdf"),
                sha256="b" * 64,
                created_by=owner.id,
            )
            db.add(document)
            db.commit()
            document_id = document.id

        response = self.client.get(f"/v1/documents/{document_id}")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["file_name"], "external.pdf")

    def test_embed_headers_allow_iframe(self) -> None:
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn("x-frame-options", response.headers)


if __name__ == "__main__":
    unittest.main()
