"""功能模块化测试：模块自动创建、按模块隔离、模块词典。"""

from __future__ import annotations

import shutil
import sys
import tempfile
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


class ModuleApiTests(unittest.TestCase):
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
            secret_key="module-test-secret-0123456789abcdef",
            upload_dir=root / "platform" / "uploads",
            engine_data_dir=root / "engine",
            engine_root=engine_root,
            inline_jobs=False,
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

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)
        self.tmp.cleanup()

    def test_modules_list_and_auto_create(self) -> None:
        first = self.client.get("/v1/modules", headers=self.headers)
        self.assertEqual(first.status_code, 200, first.text)
        modules = {item["key"]: item for item in first.json()}
        self.assertEqual(
            list(modules),
            [
                "standard_split",
                "order_parse",
                "certificate_parse",
                "outsource_report",
            ],
        )
        standard = modules["standard_split"]
        self.assertEqual(standard["status"], "active")
        self.assertEqual(standard["name"], "标准拆分")
        self.assertTrue(standard["kb_id"])
        self.assertEqual(modules["order_parse"]["status"], "planned")
        self.assertIsNone(modules["order_parse"]["kb_id"])

        second = self.client.get("/v1/modules", headers=self.headers)
        self.assertEqual(second.status_code, 200, second.text)
        again = {item["key"]: item for item in second.json()}
        self.assertEqual(again["standard_split"]["kb_id"], standard["kb_id"])

    def test_documents_are_scoped_to_module(self) -> None:
        upload = self.client.post(
            "/v1/documents",
            data={"module": "standard_split"},
            files={"file": ("sample.md", SAMPLE_MD.encode(), "text/markdown")},
            headers=self.headers,
        )
        self.assertEqual(upload.status_code, 201, upload.text)
        document_id = upload.json()["id"]

        listed = self.client.get(
            "/v1/documents",
            params={"module": "standard_split"},
            headers=self.headers,
        )
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual([item["id"] for item in listed.json()], [document_id])

        # 其他知识库不包含该文档
        created = self.client.post(
            "/v1/knowledge-bases",
            json={"name": "旧知识库"},
            headers=self.headers,
        )
        self.assertEqual(created.status_code, 201, created.text)
        other = self.client.get(
            "/v1/documents",
            params={"kb_id": created.json()["id"]},
            headers=self.headers,
        )
        self.assertEqual(other.status_code, 200, other.text)
        self.assertEqual(other.json(), [])

        # 规划中的模块拒绝上传
        blocked = self.client.post(
            "/v1/documents",
            data={"module": "order_parse"},
            files={"file": ("sample.md", SAMPLE_MD.encode(), "text/markdown")},
            headers=self.headers,
        )
        self.assertEqual(blocked.status_code, 409, blocked.text)

    def test_task_list_accepts_module(self) -> None:
        response = self.client.get(
            "/v1/tasks", params={"module": "standard_split"}, headers=self.headers
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), [])

        blocked = self.client.get(
            "/v1/tasks", params={"module": "order_parse"}, headers=self.headers
        )
        self.assertEqual(blocked.status_code, 409, blocked.text)

    def test_module_dictionary_and_alias(self) -> None:
        payload = self.client.get(
            "/v1/modules/standard_split/dictionary", headers=self.headers
        )
        self.assertEqual(payload.status_code, 200, payload.text)
        body = payload.json()
        self.assertEqual(body["module"], "standard_split")
        self.assertGreater(body["total"], 0)
        entry = body["entries"][0]

        added = self.client.post(
            "/v1/modules/standard_split/dictionary/aliases",
            json={
                "type": entry["type"],
                "business_code": entry["business_code"],
                "alias": "模块测试别名",
            },
            headers=self.headers,
        )
        self.assertEqual(added.status_code, 200, added.text)
        self.assertEqual(added.json()["module"], "standard_split")
        self.assertIn("模块测试别名", added.json()["aliases"])

        refreshed = self.client.get(
            "/v1/modules/standard_split/dictionary",
            params={"q": "模块测试别名"},
            headers=self.headers,
        )
        self.assertEqual(refreshed.status_code, 200, refreshed.text)
        self.assertGreaterEqual(refreshed.json()["total"], 1)

        blocked = self.client.get(
            "/v1/modules/order_parse/dictionary", headers=self.headers
        )
        self.assertEqual(blocked.status_code, 409, blocked.text)

    def test_split_dictionaries_and_entry_crud(self) -> None:
        for dictionary_type, entry_type in (
            ("categories", "category"),
            ("items", "item"),
            ("methods", "method"),
        ):
            response = self.client.get(
                f"/v1/modules/standard_split/dictionaries/{dictionary_type}",
                headers=self.headers,
            )
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["type"], entry_type)
            self.assertGreater(response.json()["total"], 0)

        coverage = self.client.get(
            "/v1/modules/standard_split/dictionaries/coverage",
            headers=self.headers,
        )
        self.assertEqual(coverage.status_code, 200, coverage.text)
        self.assertEqual(
            set(coverage.json()["versions"]), {"category", "item", "method"}
        )

        categories = self.client.get(
            "/v1/modules/standard_split/dictionaries/categories",
            headers=self.headers,
        ).json()["entries"]
        category_code = categories[0]["business_code"]

        missing_category = self.client.post(
            "/v1/modules/standard_split/dictionaries/items/entries",
            json={"business_name": "无大类小项"},
            headers=self.headers,
        )
        self.assertEqual(missing_category.status_code, 422, missing_category.text)

        created = self.client.post(
            "/v1/modules/standard_split/dictionaries/items/entries",
            json={
                "business_name": "测试小项",
                "aliases": ["测试别名"],
                "category_code": category_code,
            },
            headers=self.headers,
        )
        self.assertEqual(created.status_code, 201, created.text)
        item = created.json()["entry"]
        self.assertEqual(item["type"], "item")
        self.assertTrue(item["business_code"].startswith("ITEM:"))
        self.assertEqual(item["category_code"], category_code)

        missing_standard = self.client.post(
            "/v1/modules/standard_split/dictionaries/methods/entries",
            json={"business_name": "无标准号方法"},
            headers=self.headers,
        )
        self.assertEqual(missing_standard.status_code, 422, missing_standard.text)

        updated = self.client.patch(
            f"/v1/modules/standard_split/dictionaries/items/entries/{item['business_code']}",
            json={"status": "inactive"},
            headers=self.headers,
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["entry"]["status"], "inactive")


if __name__ == "__main__":
    unittest.main()
