"""P0 platform API tests: auth, KB, documents, tasks, share links, API keys."""

from __future__ import annotations

import base64
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

PROJECT = Path(__file__).resolve().parents[3]
API_DIR = Path(__file__).resolve().parents[1]
ENGINE_DIR = PROJECT / "metal-doc-agent"
for path in (str(API_DIR), str(ENGINE_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)

from hanson_api.app import restrict_engine_routes  # noqa: E402
from hanson_api.bootstrap import create_user  # noqa: E402
from hanson_api.config import PlatformSettings  # noqa: E402
from hanson_api.db import build_session_factory  # noqa: E402
from hanson_api.models import (  # noqa: E402
    DocumentClause,
    DocumentItem,
    DocumentRecord,
    EvidenceIndex,
)
from hanson_api.router import create_platform_router  # noqa: E402
from hanson_api.security import create_share_token  # noqa: E402
from metal_doc_agent.api import create_app  # noqa: E402
from metal_doc_agent.canonicalize import JsonDictionaryAdapter  # noqa: E402
from metal_doc_agent.canonicalize.review import reapply_alignment  # noqa: E402
from metal_doc_agent.settings import Settings  # noqa: E402

SAMPLE_MD = """# Page 1

表1 室温力学性能

<table>
<tr><td>牌号</td><td>抗拉强度Rm/MPa(不小于)</td><td>断后伸长率A/%(不小于)</td></tr>
<tr><td>2A14</td><td>430</td><td>10</td></tr>
</table>
"""


class PlatformApiTests(unittest.TestCase):
    def setUp(self) -> None:
        # Windows keeps the SQLite file locked until the last pooled connection
        # is garbage collected; the assertions still run, so only skip the
        # cleanup failure instead of turning a passing test into an error.
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
        self.engine_root = engine_root
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
        app = create_app(self.engine_settings)
        restrict_engine_routes(app, expose_engine=False)
        self.platform_router = create_platform_router(
            self.settings, self.engine_settings, app=app
        )
        app.include_router(self.platform_router)
        self.client = TestClient(app)
        self.client.__enter__()
        login = self.client.post(
            "/v1/auth/login",
            json={"username": "tester", "password": "secret123"},
        )
        self.assertEqual(login.status_code, 200, login.text)
        self.token = login.json()["access_token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)
        engine = getattr(self.platform_router, "_platform_engine", None)
        if engine is not None:
            engine.dispose()
        self.tmp.cleanup()

    def test_requires_authentication(self) -> None:
        response = self.client.get("/v1/knowledge-bases")
        self.assertEqual(response.status_code, 401)
        bad = self.client.get(
            "/v1/knowledge-bases",
            headers={"Authorization": "Bearer not-a-token"},
        )
        self.assertEqual(bad.status_code, 401)

    def test_selfheal_feedback_is_disabled_by_default(self) -> None:
        features = self.client.get("/v1/system/features", headers=self.headers)
        self.assertEqual(features.status_code, 200, features.text)
        self.assertEqual(features.json(), {"selfheal": False})

    def test_request_logging_and_error_metrics(self) -> None:
        from hanson_api.app import build_app

        app = build_app(self.settings, self.engine_settings)
        client = TestClient(app, raise_server_exceptions=False)
        login = client.post(
            "/v1/auth/login",
            json={"username": "tester", "password": "secret123"},
        )
        self.assertEqual(login.status_code, 200, login.text)
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        headers["X-Request-ID"] = "r5-request-1"

        with self.assertLogs("hanson.access", level="INFO") as access_logs:
            response = client.get("/v1/knowledge-bases", headers=headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["X-Request-ID"], "r5-request-1")
        payload = json.loads(access_logs.records[-1].getMessage())
        self.assertEqual(payload["request_id"], "r5-request-1")
        self.assertEqual(payload["status"], 200)
        self.assertIn("duration_ms", payload)

        with self.assertLogs("hanson.error", level="WARNING") as error_logs:
            missing = client.get("/v1/tasks/not-a-real-job", headers=headers)
        self.assertEqual(missing.status_code, 404, missing.text)
        self.assertEqual(missing.headers["X-Request-ID"], "r5-request-1")
        error_payload = json.loads(error_logs.records[-1].getMessage())
        self.assertEqual(error_payload["job_id"], "not-a-real-job")
        self.assertEqual(error_payload["status"], 404)

        metrics = client.get("/platform/metrics", headers=headers)
        self.assertEqual(metrics.status_code, 200, metrics.text)
        self.assertIn(
            'platform_errors_total{route="v1/tasks",status="404"}', metrics.text
        )

    def test_database_errors_return_503_problem(self) -> None:
        from hanson_api.app import build_app

        app = build_app(self.settings, self.engine_settings)

        @app.get("/_test/db-error")
        def db_error():
            raise OperationalError("SELECT 1", {}, Exception("connection refused"))

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/_test/db-error")
        self.assertEqual(response.status_code, 503, response.text)
        self.assertEqual(
            response.headers["content-type"], "application/problem+json"
        )
        self.assertEqual(response.json()["detail"], "database unavailable")

    def test_knowledge_base_lifecycle(self) -> None:
        created = self.client.post(
            "/v1/knowledge-bases",
            json={"name": "金属材料", "description": "P0 测试"},
            headers=self.headers,
        )
        self.assertEqual(created.status_code, 201, created.text)
        kb = created.json()
        self.assertEqual(kb["name"], "金属材料")

        listing = self.client.get("/v1/knowledge-bases", headers=self.headers)
        self.assertEqual(listing.status_code, 200)
        self.assertEqual([item["id"] for item in listing.json()], [kb["id"]])

        detail = self.client.get(
            f"/v1/knowledge-bases/{kb['id']}", headers=self.headers
        )
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["document_count"], 0)

    def test_knowledge_base_dictionary_is_isolated(self) -> None:
        kb_a = self._create_kb()
        created_b = self.client.post(
            "/v1/knowledge-bases",
            json={"name": "标准库 B"},
            headers=self.headers,
        )
        self.assertEqual(created_b.status_code, 201, created_b.text)
        kb_b = created_b.json()["id"]

        payload = self.client.get(
            f"/v1/knowledge-bases/{kb_a}/dictionary", headers=self.headers
        )
        self.assertEqual(payload.status_code, 200, payload.text)
        entry = payload.json()["entries"][0]

        added = self.client.post(
            f"/v1/knowledge-bases/{kb_a}/dictionary/aliases",
            json={
                "type": entry["type"],
                "business_code": entry["business_code"],
                "alias": "隔离测试别名",
            },
            headers=self.headers,
        )
        self.assertEqual(added.status_code, 200, added.text)

        kb_b_payload = self.client.get(
            f"/v1/knowledge-bases/{kb_b}/dictionary",
            params={"q": "隔离测试别名"},
            headers=self.headers,
        )
        self.assertEqual(kb_b_payload.status_code, 200, kb_b_payload.text)
        self.assertEqual(kb_b_payload.json()["total"], 0)

        kb_a_payload = self.client.get(
            f"/v1/knowledge-bases/{kb_a}/dictionary",
            params={"q": "隔离测试别名"},
            headers=self.headers,
        )
        self.assertEqual(kb_a_payload.json()["total"], 1)

    def test_parse_job_uses_kb_dictionary(self) -> None:
        kb_id = self._create_kb()
        payload = self.client.get(
            f"/v1/knowledge-bases/{kb_id}/dictionary", headers=self.headers
        )
        entry = payload.json()["entries"][0]
        added = self.client.post(
            f"/v1/knowledge-bases/{kb_id}/dictionary/aliases",
            json={
                "type": entry["type"],
                "business_code": entry["business_code"],
                "alias": "解析词典验证",
            },
            headers=self.headers,
        )
        self.assertEqual(added.status_code, 200, added.text)
        kb_version = added.json()["version"]
        self.assertNotEqual(kb_version, payload.json()["version"])

        document = self._upload(kb_id)
        _, out_dir = self._parse(document)
        alignment = json.loads(
            (out_dir / "alignment.json").read_text(encoding="utf-8")
        )
        self.assertEqual(alignment["dictionary_version"], kb_version)

    def _create_kb(self) -> str:
        response = self.client.post(
            "/v1/knowledge-bases",
            json={"name": "标准库"},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["id"]

    def _upload(self, kb_id: str) -> dict:
        response = self.client.post(
            "/v1/documents",
            data={"kb_id": kb_id},
            files={"file": ("Q-Du 302-2015.md", SAMPLE_MD.encode("utf-8"), "text/markdown")},
            headers=self.headers,
        )
        self.assertEqual(response.status_code in {200, 201}, True, response.text)
        return response.json()

    def test_upload_sanitizes_filenames(self) -> None:
        kb_id = self._create_kb()
        traversal = self.client.post(
            "/v1/documents",
            data={"kb_id": kb_id},
            files={
                "file": (
                    "../../evil.pdf",
                    b"%PDF-1.4\n%%EOF\n",
                    "application/pdf",
                )
            },
            headers=self.headers,
        )
        self.assertEqual(traversal.status_code, 201, traversal.text)
        document = traversal.json()
        self.assertEqual(document["file_name"], "evil.pdf")
        stored = (
            self.settings.upload_dir
            / kb_id
            / f"{document['id']}-evil.pdf"
        )
        self.assertTrue(stored.exists(), stored)

        cjk = self.client.post(
            "/v1/documents",
            data={"kb_id": kb_id},
            files={
                "file": (
                    "中文 标准.pdf",
                    b"%PDF-1.4\n%cjk\n%%EOF\n",
                    "application/pdf",
                )
            },
            headers=self.headers,
        )
        self.assertEqual(cjk.status_code, 201, cjk.text)
        self.assertEqual(cjk.json()["file_name"], "中文 标准.pdf")
        self.assertTrue(
            (
                self.settings.upload_dir
                / kb_id
                / f"{cjk.json()['id']}-中文 标准.pdf"
            ).exists()
        )

    def test_duplicate_parse_is_idempotent(self) -> None:
        kb_id = self._create_kb()
        document = self._upload(kb_id)
        first = self.client.post(
            f"/v1/documents/{document['id']}/parse", headers=self.headers
        )
        self.assertIn(first.status_code, {200, 202}, first.text)
        second = self.client.post(
            f"/v1/documents/{document['id']}/parse", headers=self.headers
        )
        self.assertIn(second.status_code, {200, 202}, second.text)
        self.assertEqual(second.json()["job_id"], first.json()["job_id"])

    def test_duplicate_evidence_ids_are_deduped(self) -> None:
        kb_id = self._create_kb()
        document = self._upload(kb_id)
        _, out_dir = self._parse(document)
        path = out_dir / "evidence.jsonl"
        lines = [
            line
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertTrue(lines, "mock parse produced no evidence")
        duplicated = lines + [lines[0]]
        path.write_text("\n".join(duplicated) + "\n", encoding="utf-8")
        items = self.client.get(
            f"/v1/documents/{document['id']}/items", headers=self.headers
        )
        self.assertEqual(items.status_code, 200, items.text)
        evidence = self.client.get(
            f"/v1/documents/{document['id']}/evidence", headers=self.headers
        )
        self.assertEqual(evidence.status_code, 200, evidence.text)
        ids = [row["evidence_id"] for row in evidence.json()]
        self.assertEqual(len(ids), len(set(ids)))

    def test_document_upload_parse_and_results(self) -> None:
        kb_id = self._create_kb()
        document = self._upload(kb_id)
        self.assertEqual(document["status"], "uploaded")

        replay = self._upload(kb_id)
        self.assertEqual(replay["id"], document["id"])

        parsed = self.client.post(
            f"/v1/documents/{document['id']}/parse", headers=self.headers
        )
        self.assertEqual(parsed.status_code in {200, 202}, True, parsed.text)
        job_id = parsed.json()["job_id"]

        task = self.client.get(f"/v1/tasks/{job_id}", headers=self.headers)
        self.assertEqual(task.status_code, 200, task.text)
        self.assertIn(task.json()["status"], {"queued", "running", "succeeded", "review"})

        detail = self.client.get(
            f"/v1/documents/{document['id']}", headers=self.headers
        )
        self.assertEqual(detail.status_code, 200)
        self.assertIn(detail.json()["status"], {"queued", "running", "succeeded", "review"})

        tasks = self.client.get(
            f"/v1/tasks?kb_id={kb_id}", headers=self.headers
        )
        self.assertEqual(tasks.status_code, 200)
        self.assertEqual(len(tasks.json()), 1)

        task_status = tasks.json()[0]["status"]
        filtered = self.client.get(
            f"/v1/tasks?kb_id={kb_id}&status={task_status}&limit=1&offset=0",
            headers=self.headers,
        )
        self.assertEqual(filtered.status_code, 200, filtered.text)
        self.assertEqual(len(filtered.json()), 1)
        missing = self.client.get(
            f"/v1/tasks?kb_id={kb_id}&status=failed&limit=1",
            headers=self.headers,
        )
        self.assertEqual(missing.json(), [])
        past_end = self.client.get(
            f"/v1/tasks?kb_id={kb_id}&limit=1&offset=1",
            headers=self.headers,
        )
        self.assertEqual(past_end.json(), [])

        document_status = detail.json()["status"]
        filtered_docs = self.client.get(
            f"/v1/documents?kb_id={kb_id}&status={document_status}",
            headers=self.headers,
        )
        self.assertEqual(filtered_docs.status_code, 200, filtered_docs.text)
        self.assertIn(
            document["id"],
            {row["id"] for row in filtered_docs.json()},
        )

        all_tasks = self.client.get("/v1/tasks", headers=self.headers)
        self.assertEqual(all_tasks.status_code, 200)
        self.assertEqual(len(all_tasks.json()), 1)
        self.assertEqual(all_tasks.json()[0]["kb_id"], kb_id)
        self.assertEqual(all_tasks.json()[0]["document_id"], document["id"])

        items = self.client.get(
            f"/v1/documents/{document['id']}/items", headers=self.headers
        )
        self.assertEqual(items.status_code, 200, items.text)
        self.assertTrue(items.json()["items"])

        records = self.client.get(
            f"/v1/documents/{document['id']}/result", headers=self.headers
        )
        self.assertEqual(records.status_code, 200)
        self.assertTrue(records.json()["records"])

    def test_preview_endpoints(self) -> None:
        kb_id = self._create_kb()
        document = self._upload(kb_id)
        parsed = self.client.post(
            f"/v1/documents/{document['id']}/parse", headers=self.headers
        )
        job_id = parsed.json()["job_id"]

        out_dir = self.engine_settings.data_dir / "jobs" / job_id
        pages = out_dir / "pages"
        pages.mkdir(parents=True, exist_ok=True)
        (pages / "page-0001.png").write_bytes(
            base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8"
                "/x8AAusB9Y9Zl1sAAAAASUVORK5CYII="
            )
        )
        (pages / "layout-0001.json").write_text(
            json.dumps(
                {
                    "page_no": 1,
                    "width": 1000,
                    "height": 2000,
                    "blocks": [
                        {
                            "type": "text",
                            "bbox": [100, 200, 500, 400],
                            "order": 1,
                            "confidence": 0.9,
                            "text": "示例文本",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        preview = self.client.get(
            f"/v1/documents/{document['id']}/preview", headers=self.headers
        )
        self.assertEqual(preview.status_code, 200, preview.text)
        page = preview.json()["pages"][0]
        self.assertIsNotNone(page["image_url"])
        self.assertIsNotNone(page["layout_url"])

        image = self.client.get(page["image_url"], headers=self.headers)
        self.assertEqual(image.status_code, 200)
        self.assertTrue(image.headers["content-type"].startswith("image/png"))

        layout = self.client.get(page["layout_url"], headers=self.headers)
        self.assertEqual(layout.status_code, 200)
        self.assertEqual(
            layout.json()["blocks"][0]["bbox"], [0.1, 0.1, 0.5, 0.2]
        )

    def _parse(self, document: dict) -> tuple[str, Path]:
        parsed = self.client.post(
            f"/v1/documents/{document['id']}/parse", headers=self.headers
        )
        self.assertEqual(parsed.status_code in {200, 202}, True, parsed.text)
        job_id = parsed.json()["job_id"]
        return job_id, self.engine_settings.data_dir / "jobs" / job_id

    def _inject_property(self, out_dir: Path, prop: str) -> None:
        inventory_path = out_dir / "item_inventory.json"
        inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
        target = next(
            (
                item
                for item in inventory["items"]
                if item.get("item_family") == "tensile"
            ),
            None,
        )
        if target is None:
            target = {
                "item_raw": "室温拉伸",
                "item_canonical": "室温拉伸",
                "item_family": "tensile",
                "facets": {"temperature": "室温"},
                "properties": [],
                "source": "manual",
                "status": "probable",
                "evidence": ["ev:test"],
            }
            inventory["items"].append(target)
        if prop not in target.get("properties", []):
            target.setdefault("properties", []).append(prop)
        inventory_path.write_text(
            json.dumps(inventory, ensure_ascii=False), encoding="utf-8"
        )
        dictionary = JsonDictionaryAdapter(
            self.engine_root / "configs" / "business_dictionary.hanson.json",
            self.engine_root / "configs" / "business_dictionary.local.json",
        ).load()
        reapply_alignment(out_dir, dictionary)

    def _category_code(self, name: str) -> str:
        dictionary = JsonDictionaryAdapter(
            self.engine_root / "configs" / "business_dictionary.hanson.json"
        ).load()
        entry = next(
            item
            for item in dictionary.entries
            if item.type == "category" and item.business_name == name
        )
        return entry.business_code

    def test_new_term_review_accept_and_reject(self) -> None:
        kb_id = self._create_kb()
        document = self._upload(kb_id)
        _, out_dir = self._parse(document)
        category_code = self._category_code("室温拉伸")
        self._inject_property(out_dir, "自定义指标")

        terms = self.client.get(
            f"/v1/documents/{document['id']}/new-terms", headers=self.headers
        )
        self.assertEqual(terms.status_code, 200)
        self.assertIn("自定义指标", [term["raw"] for term in terms.json()["terms"]])
        synced_items = self.client.get(
            f"/v1/documents/{document['id']}/items", headers=self.headers
        )
        self.assertEqual(synced_items.status_code, 200, synced_items.text)

        accepted = self.client.post(
            f"/v1/documents/{document['id']}/new-terms/review",
            json={
                "type": "item",
                "raw": "自定义指标",
                "action": "accept",
                "business_code": "LOCAL:PROP",
                "business_name": "自定义指标",
                "category_code": category_code,
                "category_name": "室温拉伸",
            },
            headers=self.headers,
        )
        self.assertEqual(accepted.status_code, 200, accepted.text)
        self.assertEqual(accepted.json()["applied_code"], "LOCAL:PROP")
        self.assertTrue(accepted.json()["matched"])
        self.assertNotIn(
            "自定义指标",
            [term["raw"] for term in accepted.json()["new_terms"]["terms"]],
        )
        detail = self.client.get(
            f"/v1/documents/{document['id']}", headers=self.headers
        )
        self.assertIsNone(detail.json()["results_job_id"])

        override_path = (
            self.settings.engine_data_dir / "dictionaries" / kb_id / "items.json"
        )
        override = json.loads(override_path.read_text(encoding="utf-8"))
        self.assertTrue(
            any(item["business_code"] == "LOCAL:PROP" for item in override["entries"])
        )
        alignment = json.loads(
            (out_dir / "alignment.json").read_text(encoding="utf-8")
        )
        self.assertTrue(
            any(
                match["canonical_id"] == "LOCAL:PROP"
                for match in alignment["property_matches"]
            )
        )

        self._inject_property(out_dir, "自定义指标二号")
        rejected = self.client.post(
            f"/v1/documents/{document['id']}/new-terms/review",
            json={
                "type": "item",
                "raw": "自定义指标二号",
                "action": "reject",
                "reason": "不需要",
            },
            headers=self.headers,
        )
        self.assertEqual(rejected.status_code, 200, rejected.text)
        statuses = {
            term["raw"]: term["status"]
            for term in rejected.json()["new_terms"]["terms"]
        }
        self.assertEqual(statuses["自定义指标二号"], "rejected")

        reviews = self.client.get(
            f"/v1/documents/{document['id']}/reviews", headers=self.headers
        )
        self.assertEqual(reviews.status_code, 200)
        self.assertEqual(
            [event["action"] for event in reviews.json()][:2],
            ["reject", "accept"],
        )

    def test_new_term_review_map(self) -> None:
        kb_id = self._create_kb()
        document = self._upload(kb_id)
        _, out_dir = self._parse(document)
        self._inject_property(out_dir, "发货检验三号")

        from metal_doc_agent.canonicalize.dictionary import load_dictionary_path

        dictionary = load_dictionary_path(
            Path(self.settings.engine_root) / "configs" / "dictionaries"
        )
        target_code = next(
            entry.business_code
            for entry in dictionary.entries
            if entry.type == "item" and entry.status == "active"
        )

        mapped = self.client.post(
            f"/v1/documents/{document['id']}/new-terms/review",
            json={
                "type": "item",
                "raw": "发货检验三号",
                "action": "map",
                "target_code": target_code,
            },
            headers=self.headers,
        )
        self.assertEqual(mapped.status_code, 200, mapped.text)
        self.assertEqual(mapped.json()["applied_code"], target_code)
        self.assertTrue(mapped.json()["matched"])

        override = json.loads(
            (
                self.settings.engine_data_dir / "dictionaries" / kb_id / "items.json"
            ).read_text(encoding="utf-8")
        )
        entry = next(
            item for item in override["entries"]
            if item["business_code"] == target_code
        )
        self.assertIn("发货检验三号", entry["aliases"])

    def test_document_review_flow(self) -> None:
        kb_id = self._create_kb()
        document = self._upload(kb_id)

        early = self.client.post(
            f"/v1/documents/{document['id']}/review",
            json={"action": "submit"},
            headers=self.headers,
        )
        self.assertEqual(early.status_code, 409, early.text)

        job_id, _ = self._parse(document)
        detail = self.client.get(
            f"/v1/documents/{document['id']}", headers=self.headers
        )
        self.assertEqual(detail.json()["review_status"], "draft")
        self.assertEqual(detail.json()["review_version"], 1)

        not_submitted = self.client.post(
            f"/v1/documents/{document['id']}/review",
            json={"action": "confirm"},
            headers=self.headers,
        )
        self.assertEqual(not_submitted.status_code, 409, not_submitted.text)

        submitted = self.client.post(
            f"/v1/documents/{document['id']}/review",
            json={"action": "submit"},
            headers=self.headers,
        )
        self.assertEqual(submitted.status_code, 200, submitted.text)
        self.assertEqual(submitted.json()["review_status"], "review")

        terms = self.client.get(
            f"/v1/documents/{document['id']}/new-terms", headers=self.headers
        ).json()["terms"]
        pending = [term for term in terms if term["status"] == "pending"]
        if pending:
            blocked = self.client.post(
                f"/v1/documents/{document['id']}/review",
                json={"action": "confirm"},
                headers=self.headers,
            )
            self.assertEqual(blocked.status_code, 409, blocked.text)
            for term in pending:
                rejected = self.client.post(
                    f"/v1/documents/{document['id']}/new-terms/review",
                    json={
                        "type": term["type"],
                        "raw": term["raw"],
                        "action": "reject",
                    },
                    headers=self.headers,
                )
                self.assertEqual(rejected.status_code, 200, rejected.text)

        confirmed = self.client.post(
            f"/v1/documents/{document['id']}/review",
            json={"action": "confirm", "reason": "整体复核通过"},
            headers=self.headers,
        )
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        self.assertEqual(confirmed.json()["review_status"], "confirmed")
        self.assertEqual(confirmed.json()["confirmed_job_id"], job_id)
        self.assertEqual(confirmed.json()["pending_new_terms"], 0)

        task = self.client.get(f"/v1/tasks/{job_id}", headers=self.headers)
        self.assertEqual(task.status_code, 200, task.text)
        self.assertTrue(task.json()["locked"])
        locked_retry = self.client.post(
            f"/v1/tasks/{job_id}/retry", headers=self.headers
        )
        self.assertEqual(locked_retry.status_code, 409, locked_retry.text)

        locked = self.client.post(
            f"/v1/documents/{document['id']}/new-terms/review",
            json={"type": "item", "raw": "任意新词", "action": "reject"},
            headers=self.headers,
        )
        self.assertEqual(locked.status_code, 409, locked.text)

        again = self.client.post(
            f"/v1/documents/{document['id']}/review",
            json={"action": "submit"},
            headers=self.headers,
        )
        self.assertEqual(again.status_code, 409, again.text)

        reparse = self.client.post(
            f"/v1/documents/{document['id']}/parse", headers=self.headers
        )
        self.assertEqual(reparse.status_code == 202, True, reparse.text)
        self.assertNotEqual(reparse.json()["job_id"], job_id)
        self.assertEqual(reparse.json()["version"], 2)

        detail = self.client.get(
            f"/v1/documents/{document['id']}", headers=self.headers
        )
        self.assertEqual(detail.json()["review_status"], "draft")
        self.assertEqual(detail.json()["review_version"], 2)
        self.assertEqual(detail.json()["confirmed_job_id"], job_id)

        tasks = self.client.get(f"/v1/tasks?kb_id={kb_id}", headers=self.headers)
        versions = {task["job_id"]: task["version"] for task in tasks.json()}
        self.assertEqual(versions[job_id], 1)
        self.assertEqual(versions[reparse.json()["job_id"]], 2)
        new_task = self.client.get(
            f"/v1/tasks/{reparse.json()['job_id']}", headers=self.headers
        )
        self.assertFalse(new_task.json()["locked"])

    def test_force_reparse_draft_document(self) -> None:
        kb_id = self._create_kb()
        document = self._upload(kb_id)
        job_id, _ = self._parse(document)

        forced = self.client.post(
            f"/v1/documents/{document['id']}/parse?force=true",
            headers=self.headers,
        )
        self.assertEqual(forced.status_code, 202, forced.text)
        self.assertNotEqual(forced.json()["job_id"], job_id)
        self.assertEqual(forced.json()["version"], 2)

    def test_evidence_item_lookup(self) -> None:
        kb_id = self._create_kb()
        document = self._upload(kb_id)
        self._parse(document)

        listing = self.client.get(
            f"/v1/documents/{document['id']}/evidence?limit=50",
            headers=self.headers,
        )
        self.assertEqual(listing.status_code, 200, listing.text)
        self.assertTrue(listing.json())
        evidence = listing.json()[0]

        item = self.client.get(
            f"/v1/documents/{document['id']}/evidence/{evidence['evidence_id']}",
            headers=self.headers,
        )
        self.assertEqual(item.status_code, 200, item.text)
        self.assertEqual(item.json()["page_no"], evidence["page_no"])

        missing = self.client.get(
            f"/v1/documents/{document['id']}/evidence/ev:missing",
            headers=self.headers,
        )
        self.assertEqual(missing.status_code, 404)

    def test_results_persisted_and_synced(self) -> None:
        kb_id = self._create_kb()
        document = self._upload(kb_id)
        job_id, _ = self._parse(document)
        base = f"/v1/documents/{document['id']}"

        detail = self.client.get(base, headers=self.headers)
        self.assertIsNone(detail.json()["results_job_id"])

        items = self.client.get(f"{base}/items", headers=self.headers)
        self.assertEqual(items.status_code, 200, items.text)
        records = self.client.get(f"{base}/records", headers=self.headers)
        self.assertEqual(records.status_code, 200, records.text)
        clauses = self.client.get(f"{base}/clauses", headers=self.headers)
        self.assertEqual(clauses.status_code, 200, clauses.text)
        evidence = self.client.get(f"{base}/evidence?limit=5000", headers=self.headers)
        self.assertEqual(evidence.status_code, 200, evidence.text)

        job_records = self.client.get(
            f"/v1/jobs/{job_id}/records", headers=self.headers
        )
        self.assertEqual(len(records.json()), len(job_records.json()))

        detail = self.client.get(base, headers=self.headers)
        self.assertEqual(detail.json()["results_job_id"], job_id)
        self.assertIsNotNone(detail.json()["results_synced_at"])

        synced = self.client.post(f"{base}/results/sync", headers=self.headers)
        self.assertEqual(synced.status_code, 202, synced.text)
        self.assertEqual(synced.json()["job_id"], job_id)
        self.assertGreaterEqual(synced.json()["items"], 1)

        factory = build_session_factory(self.platform_router._platform_engine)
        with factory() as db:
            db_items = db.scalar(
                select(func.count())
                .select_from(DocumentItem)
                .where(DocumentItem.document_id == document["id"])
            )
            db_records = db.scalar(
                select(func.count())
                .select_from(DocumentRecord)
                .where(DocumentRecord.document_id == document["id"])
            )
            db_clauses = db.scalar(
                select(func.count())
                .select_from(DocumentClause)
                .where(DocumentClause.document_id == document["id"])
            )
            db_evidence = db.scalar(
                select(func.count())
                .select_from(EvidenceIndex)
                .where(EvidenceIndex.document_id == document["id"])
            )
        self.assertEqual(db_items, len(items.json()["items"]))
        self.assertEqual(db_records, len(records.json()))
        self.assertEqual(db_clauses, len(clauses.json()))
        self.assertEqual(db_evidence, len(evidence.json()))

    def test_share_token(self) -> None:
        kb_id = self._create_kb()
        document = self._upload(kb_id)
        self.client.post(
            f"/v1/documents/{document['id']}/parse", headers=self.headers
        )

        shared = self.client.post(
            f"/v1/documents/{document['id']}/share", headers=self.headers
        )
        self.assertEqual(shared.status_code, 200, shared.text)
        token = shared.json()["token"]

        public = self.client.get(f"/v1/share/{token}")
        self.assertEqual(public.status_code, 200, public.text)
        bundle = public.json()
        self.assertEqual(bundle["document"]["id"], document["id"])
        self.assertIsInstance(bundle["records"], list)
        self.assertIsInstance(bundle["clauses"], list)
        self.assertIsInstance(bundle["evidence"], list)
        self.assertTrue(bundle["evidence"])

        invalid = self.client.get("/v1/share/not-a-token")
        self.assertEqual(invalid.status_code, 401)

    def test_api_key_auth_and_revoke(self) -> None:
        kb_id = self._create_kb()
        created = self.client.post(
            "/v1/api-keys",
            json={"name": "外部对接"},
            headers=self.headers,
        )
        self.assertEqual(created.status_code, 201, created.text)
        raw_key = created.json()["key"]
        key_id = created.json()["id"]

        listing = self.client.get(
            "/v1/knowledge-bases", headers={"X-API-Key": raw_key}
        )
        self.assertEqual(listing.status_code, 200, listing.text)
        self.assertEqual(listing.json()[0]["id"], kb_id)

        read_only = self.client.post(
            "/v1/api-keys",
            json={"name": "只读", "scopes": ["documents:read"]},
            headers=self.headers,
        )
        self.assertEqual(read_only.status_code, 201, read_only.text)
        read_key = read_only.json()["key"]
        blocked = self.client.post(
            "/v1/documents",
            data={"kb_id": kb_id},
            files={"file": ("readonly.md", SAMPLE_MD.encode(), "text/markdown")},
            headers={"X-API-Key": read_key},
        )
        self.assertEqual(blocked.status_code, 403, blocked.text)

        revoked = self.client.delete(
            f"/v1/api-keys/{key_id}", headers=self.headers
        )
        self.assertEqual(revoked.status_code, 204)
        after = self.client.get(
            "/v1/knowledge-bases", headers={"X-API-Key": raw_key}
        )
        self.assertEqual(after.status_code, 401)

    def test_knowledge_base_isolation(self) -> None:
        create_user(
            self.settings,
            "outsider",
            "secret123",
            display_name="外部用户",
            role="user",
        )
        login = self.client.post(
            "/v1/auth/login",
            json={"username": "outsider", "password": "secret123"},
        )
        self.assertEqual(login.status_code, 200, login.text)
        outsider_headers = {
            "Authorization": f"Bearer {login.json()['access_token']}"
        }

        kb = self.client.post(
            "/v1/knowledge-bases",
            json={"name": "外部知识库"},
            headers=outsider_headers,
        )
        self.assertEqual(kb.status_code, 201, kb.text)
        kb_id = kb.json()["id"]
        upload = self.client.post(
            "/v1/documents",
            data={"kb_id": kb_id},
            files={"file": ("outsider.md", SAMPLE_MD.encode(), "text/markdown")},
            headers=outsider_headers,
        )
        self.assertEqual(upload.status_code, 201, upload.text)
        document_id = upload.json()["id"]
        parsed = self.client.post(
            f"/v1/documents/{document_id}/parse", headers=outsider_headers
        )
        self.assertEqual(parsed.status_code in {200, 202}, True, parsed.text)

        for path in (
            f"/v1/knowledge-bases/{kb_id}",
            f"/v1/documents?kb_id={kb_id}",
            f"/v1/tasks?kb_id={kb_id}",
            f"/v1/documents/{document_id}",
            f"/v1/documents/{document_id}/items",
        ):
            response = self.client.get(path, headers=self.headers)
            self.assertIn(response.status_code, {403, 404}, path)
        blocked_upload = self.client.post(
            "/v1/documents",
            data={"kb_id": kb_id},
            files={"file": ("blocked.md", SAMPLE_MD.encode(), "text/markdown")},
            headers=self.headers,
        )
        self.assertEqual(blocked_upload.status_code, 403)

        own_tasks = self.client.get("/v1/tasks", headers=self.headers)
        self.assertEqual(own_tasks.status_code, 200)
        self.assertEqual(own_tasks.json(), [])
        outsider_tasks = self.client.get("/v1/tasks", headers=outsider_headers)
        self.assertEqual(outsider_tasks.status_code, 200)
        self.assertIn(document_id, [item["document_id"] for item in outsider_tasks.json()])

        audit = self.client.get("/v1/audit-logs", headers=outsider_headers)
        self.assertEqual(audit.status_code, 403, audit.text)

    def test_upload_filename_is_sanitized(self) -> None:
        kb_id = self._create_kb()
        response = self.client.post(
            "/v1/documents",
            data={"kb_id": kb_id},
            files={"file": ("../../evil.md", b"# evil\n", "text/markdown")},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 201, response.text)
        document = response.json()
        self.assertEqual(document["file_name"], "evil.md")

        files = list((self.settings.upload_dir / kb_id).iterdir())
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].parent.resolve(), (self.settings.upload_dir / kb_id).resolve())
        self.assertTrue(files[0].name.endswith("-evil.md"), files[0].name)

    def test_expired_share_token_is_rejected(self) -> None:
        token, _ = create_share_token(self.settings.secret_key, "doc", -1)
        response = self.client.get(f"/v1/share/{token}")
        self.assertEqual(response.status_code, 401)

    def test_metrics_and_ready(self) -> None:
        metrics = self.client.get("/platform/metrics")
        self.assertEqual(metrics.status_code, 200)
        self.assertIn("platform_documents", metrics.text)
        self.assertIn("engine_jobs", metrics.text)
        ready = self.client.get("/platform/ready")
        self.assertEqual(ready.status_code, 200, ready.text)
        self.assertEqual(ready.json()["status"], "ok")
        self.assertTrue(ready.json()["checks"]["database"])

    def test_audit_logs(self) -> None:
        kb_id = self._create_kb()
        document = self._upload(kb_id)
        self.client.post(
            f"/v1/documents/{document['id']}/parse", headers=self.headers
        )
        logs = self.client.get("/v1/audit-logs", headers=self.headers)
        self.assertEqual(logs.status_code, 200)
        actions = {item["action"] for item in logs.json()}
        self.assertTrue(
            {"auth.login", "kb.create", "document.upload", "document.parse"}
            <= actions,
            actions,
        )

    def _first_record(self, document: dict) -> dict:
        records = self.client.get(
            f"/v1/documents/{document['id']}/result", headers=self.headers
        )
        self.assertEqual(records.status_code, 200, records.text)
        return records.json()["records"][0]

    def test_field_review_edit_diff_and_feedback(self) -> None:
        kb_id = self._create_kb()
        document = self._upload(kb_id)
        self._parse(document)
        record = self._first_record(document)
        prop = next(iter(record["properties"]))
        old = record["properties"][prop]
        field_path = f"records.{record['record_id']}.properties.{prop}"

        risks = self.client.get(
            f"/v1/documents/{document['id']}/review-risks", headers=self.headers
        )
        self.assertEqual(risks.status_code, 200, risks.text)
        self.assertGreater(len(risks.json()["fields"]), 0)

        submitted = self.client.post(
            f"/v1/documents/{document['id']}/review",
            json={"action": "submit"},
            headers=self.headers,
        )
        self.assertEqual(submitted.status_code, 200, submitted.text)

        new_value = dict(old)
        if old.get("value") is not None:
            new_value["value"] = old["value"] + 5
        else:
            new_value["text"] = "复核后"
        created = self.client.post(
            f"/v1/documents/{document['id']}/field-reviews",
            json={
                "field_path": field_path,
                "action": "edit",
                "old_value": old,
                "new_value": new_value,
                "reason": "原文为更高值",
            },
            headers=self.headers,
        )
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(created.json()["action"], "edit")

        missing_reason = self.client.post(
            f"/v1/documents/{document['id']}/field-reviews",
            json={"field_path": field_path, "action": "reject"},
            headers=self.headers,
        )
        self.assertEqual(missing_reason.status_code, 422)

        events = self.client.get(
            f"/v1/documents/{document['id']}/field-reviews", headers=self.headers
        )
        self.assertEqual(events.status_code, 200)
        self.assertEqual(len(events.json()), 1)

        diff = self.client.get(
            f"/v1/documents/{document['id']}/field-diff", headers=self.headers
        )
        self.assertEqual(diff.status_code, 200, diff.text)
        self.assertEqual(diff.json()[0]["action"], "edit")
        self.assertEqual(diff.json()[0]["machine"]["value"], old.get("value"))

        effective = self.client.get(
            f"/v1/documents/{document['id']}/result", headers=self.headers
        ).json()["records"][0]["properties"][prop]
        self.assertEqual(effective["value"], new_value.get("value"))

        feedback = self.settings.engine_data_dir / "feedback" / "feedback.jsonl"
        self.assertTrue(feedback.exists())
        self.assertEqual(len(feedback.read_text(encoding="utf-8").splitlines()), 1)

        logs = self.client.get("/v1/audit-logs", headers=self.headers)
        self.assertIn("document.field_review.edit", {item["action"] for item in logs.json()})

    def test_high_risk_field_blocks_confirmation_until_reviewed(self) -> None:
        kb_id = self._create_kb()
        document = self._upload(kb_id)
        job_id, out_dir = self._parse(document)
        record = self._first_record(document)
        prop = next(iter(record["properties"]))
        field_path = f"records.{record['record_id']}.properties.{prop}"
        result_path = out_dir / "result.json"
        payload = json.loads(result_path.read_text(encoding="utf-8"))
        for item in payload["records"]:
            if item["record_id"] == record["record_id"]:
                item["properties"][prop]["evidence_id"] = ""
        result_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        submitted = self.client.post(
            f"/v1/documents/{document['id']}/review",
            json={"action": "submit"},
            headers=self.headers,
        )
        self.assertEqual(submitted.status_code, 200, submitted.text)
        blocked = self.client.post(
            f"/v1/documents/{document['id']}/review",
            json={"action": "confirm"},
            headers=self.headers,
        )
        self.assertEqual(blocked.status_code, 409, blocked.text)
        self.assertEqual(
            blocked.json()["detail"]["error"], "high_risk_fields_unreviewed"
        )

        accepted = self.client.post(
            f"/v1/documents/{document['id']}/field-reviews",
            json={"field_path": field_path, "action": "accept"},
            headers=self.headers,
        )
        self.assertEqual(accepted.status_code, 201, accepted.text)
        confirmed = self.client.post(
            f"/v1/documents/{document['id']}/review",
            json={"action": "confirm"},
            headers=self.headers,
        )
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        self.assertEqual(confirmed.json()["review_status"], "confirmed")

    def test_field_review_batch_accepts(self) -> None:
        kb_id = self._create_kb()
        document = self._upload(kb_id)
        self._parse(document)
        record = self._first_record(document)
        props = list(record["properties"].keys())[:2]
        events = [
            {
                "field_path": f"records.{record['record_id']}.properties.{prop}",
                "action": "accept",
            }
            for prop in props
        ]
        response = self.client.post(
            f"/v1/documents/{document['id']}/field-reviews/batch",
            json={"events": events},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(response.json()), len(events))

        bulk = events * 100
        self.assertEqual(len(bulk), 200)
        bulk_response = self.client.post(
            f"/v1/documents/{document['id']}/field-reviews/batch",
            json={"events": bulk},
            headers=self.headers,
        )
        self.assertEqual(bulk_response.status_code, 200, bulk_response.text)
        self.assertEqual(len(bulk_response.json()), 200)


if __name__ == "__main__":
    unittest.main()
