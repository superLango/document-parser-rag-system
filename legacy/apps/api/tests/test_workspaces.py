"""R3 multi-tenant tests: workspace, invitation, KB roles, users, API keys."""

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


class MultiTenantTests(unittest.TestCase):
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
            secret_key="multi-tenant-test-secret-0123456789abcdef",
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
        create_user(self.settings, "root", "root-pass", display_name="Root", role="admin")
        create_user(self.settings, "alice", "alice-pass", display_name="Alice", role="user")
        create_user(self.settings, "bob", "bob-pass", display_name="Bob", role="user")
        self.app = build_app(self.settings, self.engine_settings)
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.root = self._login("root", "root-pass")
        self.alice = self._login("alice", "alice-pass")
        self.bob = self._login("bob", "bob-pass")

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)
        self.tmp.cleanup()

    def _login(self, username: str, password: str) -> dict[str, str]:
        response = self.client.post(
            "/v1/auth/login", json={"username": username, "password": password}
        )
        self.assertEqual(response.status_code, 200, response.text)
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    def _workspace(self, headers: dict[str, str], name: str) -> dict:
        response = self.client.post(
            "/v1/workspaces", headers=headers, json={"name": name}
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def _kb(self, headers: dict[str, str], workspace_id: str, name: str) -> dict:
        response = self.client.post(
            "/v1/knowledge-bases",
            headers=headers,
            json={"name": name, "workspace_id": workspace_id},
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

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

    def test_workspace_members_and_roles(self) -> None:
        workspace = self._workspace(self.alice, "Alice WS")
        self.assertEqual(workspace["role"], "owner")
        response = self.client.get("/v1/workspaces", headers=self.alice)
        self.assertEqual(len(response.json()), 1)
        response = self.client.post(
            f"/v1/workspaces/{workspace['id']}/members",
            headers=self.alice,
            json={"username": "bob", "role": "member"},
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(
            self.client.get("/v1/workspaces", headers=self.bob).json()[0]["role"],
            "member",
        )
        denied = self.client.patch(
            f"/v1/workspaces/{workspace['id']}",
            headers=self.bob,
            json={"name": "hijack"},
        )
        self.assertEqual(denied.status_code, 403, denied.text)
        renamed = self.client.patch(
            f"/v1/workspaces/{workspace['id']}",
            headers=self.alice,
            json={"name": "Alice WS 2"},
        )
        self.assertEqual(renamed.status_code, 200, renamed.text)
        # Last owner cannot be removed.
        removed = self.client.delete(
            f"/v1/workspaces/{workspace['id']}/members/{workspace['owner_id']}",
            headers=self.alice,
        )
        self.assertEqual(removed.status_code, 409, removed.text)

        members = self.client.get(
            f"/v1/workspaces/{workspace['id']}/members", headers=self.alice
        ).json()
        bob_id = next(m["user_id"] for m in members if m["username"] == "bob")
        promoted = self.client.patch(
            f"/v1/workspaces/{workspace['id']}/members/{bob_id}",
            headers=self.alice,
            json={"role": "admin"},
        )
        self.assertEqual(promoted.status_code, 200, promoted.text)
        self.assertEqual(
            self.client.patch(
                f"/v1/workspaces/{workspace['id']}",
                headers=self.bob,
                json={"description": "bob edit"},
            ).status_code,
            200,
        )
        demoted = self.client.patch(
            f"/v1/workspaces/{workspace['id']}/members/{bob_id}",
            headers=self.alice,
            json={"role": "member"},
        )
        self.assertEqual(demoted.status_code, 200, demoted.text)
        removed_bob = self.client.delete(
            f"/v1/workspaces/{workspace['id']}/members/{bob_id}",
            headers=self.alice,
        )
        self.assertEqual(removed_bob.status_code, 204, removed_bob.text)
        self.assertIn(
            self.client.get(
                f"/v1/workspaces/{workspace['id']}", headers=self.bob
            ).status_code,
            (403, 404),
        )
        self.assertEqual(
            self.client.get("/v1/workspaces", headers=self.bob).json(), []
        )

    def test_invitation_accept_once_and_revoke(self) -> None:
        workspace = self._workspace(self.alice, "Invite WS")
        created = self.client.post(
            f"/v1/workspaces/{workspace['id']}/invitations",
            headers=self.alice,
            json={"role": "member", "note": "bob"},
        )
        self.assertEqual(created.status_code, 201, created.text)
        token = created.json()["token"]
        accepted = self.client.post(
            f"/v1/invitations/{token}/accept", headers=self.bob
        )
        self.assertEqual(accepted.status_code, 200, accepted.text)
        self.assertEqual(accepted.json()["workspace_id"], workspace["id"])
        again = self.client.post(
            f"/v1/invitations/{token}/accept", headers=self.bob
        )
        self.assertEqual(again.status_code, 409, again.text)
        created2 = self.client.post(
            f"/v1/workspaces/{workspace['id']}/invitations",
            headers=self.alice,
            json={"role": "member"},
        )
        invitation_id = created2.json()["id"]
        revoked = self.client.delete(
            f"/v1/workspaces/{workspace['id']}/invitations/{invitation_id}",
            headers=self.alice,
        )
        self.assertEqual(revoked.status_code, 204, revoked.text)
        used_revoked = self.client.post(
            f"/v1/invitations/{created2.json()['token']}/accept",
            headers=self.bob,
        )
        self.assertEqual(used_revoked.status_code, 409, used_revoked.text)

    def test_kb_roles_enforced(self) -> None:
        workspace = self._workspace(self.alice, "KB WS")
        self.client.post(
            f"/v1/workspaces/{workspace['id']}/members",
            headers=self.alice,
            json={"username": "bob", "role": "member"},
        )
        kb = self._kb(self.alice, workspace["id"], "KB")
        denied = self.client.get(f"/v1/knowledge-bases/{kb['id']}", headers=self.bob)
        self.assertEqual(denied.status_code, 403, denied.text)
        viewer = self.client.post(
            f"/v1/knowledge-bases/{kb['id']}/members",
            headers=self.alice,
            json={"username": "bob", "role": "viewer"},
        )
        self.assertEqual(viewer.status_code, 201, viewer.text)
        self.assertEqual(
            self.client.get(f"/v1/knowledge-bases/{kb['id']}", headers=self.bob).status_code,
            200,
        )
        document = self._upload(self.alice, kb["id"])
        self.assertEqual(
            self.client.get(
                f"/v1/documents/{document['id']}", headers=self.bob
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.post(
                f"/v1/documents/{document['id']}/parse", headers=self.bob
            ).status_code,
            403,
        )
        viewer_key = self.client.post(
            "/v1/api-keys",
            headers=self.bob,
            json={
                "name": "viewer-write",
                "scopes": ["documents:read", "documents:write"],
                "workspace_id": workspace["id"],
                "kb_ids": [kb["id"]],
            },
        )
        self.assertEqual(viewer_key.status_code, 201, viewer_key.text)
        viewer_headers = {"X-API-Key": viewer_key.json()["key"]}
        self.assertEqual(
            self.client.post(
                f"/v1/documents/{document['id']}/parse", headers=viewer_headers
            ).status_code,
            403,
        )
        promoted = self.client.patch(
            f"/v1/knowledge-bases/{kb['id']}/members/{self._user_id('bob')}",
            headers=self.alice,
            json={"role": "editor"},
        )
        self.assertEqual(promoted.status_code, 200, promoted.text)
        parsed = self.client.post(
            f"/v1/documents/{document['id']}/parse", headers=self.bob
        )
        self.assertEqual(parsed.status_code, 202, parsed.text)
        manage = self.client.post(
            f"/v1/knowledge-bases/{kb['id']}/members",
            headers=self.bob,
            json={"username": "root", "role": "viewer"},
        )
        self.assertEqual(manage.status_code, 403, manage.text)

    def _user_id(self, username: str) -> str:
        response = self.client.get(f"/v1/users?q={username}", headers=self.root)
        self.assertEqual(response.status_code, 200, response.text)
        for row in response.json():
            if row["username"] == username:
                return row["id"]
        self.fail(f"user not found: {username}")

    def test_user_management(self) -> None:
        created = self.client.post(
            "/v1/users",
            headers=self.root,
            json={
                "username": "carol",
                "password": "carol-pass",
                "display_name": "Carol",
                "role": "user",
            },
        )
        self.assertEqual(created.status_code, 201, created.text)
        carol_id = created.json()["id"]
        self.assertEqual(
            self.client.get("/v1/users", headers=self.alice).status_code, 403
        )
        deactivated = self.client.patch(
            f"/v1/users/{carol_id}",
            headers=self.root,
            json={"is_active": False},
        )
        self.assertEqual(deactivated.status_code, 200, deactivated.text)
        self.assertEqual(
            self.client.post(
                "/v1/auth/login",
                json={"username": "carol", "password": "carol-pass"},
            ).status_code,
            401,
        )
        self.client.patch(
            f"/v1/users/{carol_id}", headers=self.root, json={"is_active": True}
        )
        reset = self.client.patch(
            f"/v1/users/{carol_id}",
            headers=self.root,
            json={"password": "carol-pass-2"},
        )
        self.assertEqual(reset.status_code, 200, reset.text)
        self.assertEqual(
            self.client.post(
                "/v1/auth/login",
                json={"username": "carol", "password": "carol-pass"},
            ).status_code,
            401,
        )
        self.assertEqual(
            self.client.post(
                "/v1/auth/login",
                json={"username": "carol", "password": "carol-pass-2"},
            ).status_code,
            200,
        )

    def test_cross_workspace_document_and_task_denied(self) -> None:
        alice_ws = self._workspace(self.alice, "Alice Isolation")
        alice_kb = self._kb(self.alice, alice_ws["id"], "Alice KB")
        alice_doc = self._upload(self.alice, alice_kb["id"])
        alice_task = self._parse(self.alice, alice_doc["id"])
        bob_ws = self._workspace(self.bob, "Bob Isolation")
        bob_kb = self._kb(self.bob, bob_ws["id"], "Bob KB")

        for path in (
            f"/v1/documents/{alice_doc['id']}",
            f"/v1/tasks/{alice_task['job_id']}",
            f"/v1/documents/{alice_doc['id']}/items",
            f"/v1/documents?kb_id={alice_kb['id']}",
        ):
            self.assertEqual(
                self.client.get(path, headers=self.bob).status_code,
                403,
                path,
            )
        self.assertIn(
            self.client.get(
                f"/v1/audit-logs?workspace_id={alice_ws['id']}",
                headers=self.bob,
            ).status_code,
            (403, 404),
        )
        self.assertIn(
            self.client.get(
                f"/v1/knowledge-bases?workspace_id={alice_ws['id']}",
                headers=self.bob,
            ).status_code,
            (403, 404),
        )
        bob_doc = self._upload(self.bob, bob_kb["id"])
        key = self.client.post(
            "/v1/api-keys",
            headers=self.alice,
            json={
                "name": "alice-key",
                "scopes": ["documents:read"],
                "workspace_id": alice_ws["id"],
                "kb_ids": [alice_kb["id"]],
            },
        )
        self.assertEqual(key.status_code, 201, key.text)
        key_headers = {"X-API-Key": key.json()["key"]}
        self.assertEqual(
            self.client.get(
                f"/v1/documents/{bob_doc['id']}", headers=key_headers
            ).status_code,
            403,
        )

    def test_api_key_workspace_and_kb_whitelist(self) -> None:
        workspace = self._workspace(self.alice, "Key WS")
        kb1 = self._kb(self.alice, workspace["id"], "KB1")
        kb2 = self._kb(self.alice, workspace["id"], "KB2")
        document = self._upload(self.alice, kb1["id"])
        key = self.client.post(
            "/v1/api-keys",
            headers=self.alice,
            json={
                "name": "read-kb1",
                "scopes": ["documents:read"],
                "workspace_id": workspace["id"],
                "kb_ids": [kb1["id"]],
            },
        )
        self.assertEqual(key.status_code, 201, key.text)
        payload = key.json()
        self.assertEqual(payload["workspace_id"], workspace["id"])
        self.assertEqual(payload["kb_ids"], [kb1["id"]])
        key_headers = {"X-API-Key": payload["key"]}
        self.assertEqual(
            self.client.get(
                f"/v1/documents/{document['id']}", headers=key_headers
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(
                f"/v1/documents?kb_id={kb2['id']}", headers=key_headers
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                f"/v1/documents/{document['id']}/parse", headers=key_headers
            ).status_code,
            403,
        )
        other_ws = self._workspace(self.bob, "Other WS")
        other_kb = self._kb(self.bob, other_ws["id"], "Other KB")
        mismatch = self.client.post(
            "/v1/api-keys",
            headers=self.alice,
            json={
                "name": "bad",
                "scopes": ["documents:read"],
                "workspace_id": workspace["id"],
                "kb_ids": [other_kb["id"]],
            },
        )
        self.assertIn(mismatch.status_code, (403, 404), mismatch.text)

    def test_cancel_and_delete_document(self) -> None:
        workspace = self._workspace(self.alice, "Task WS")
        kb = self._kb(self.alice, workspace["id"], "Task KB")
        document = self._upload(self.alice, kb["id"])
        task = self._parse(self.alice, document["id"])
        cancelled = self.client.post(
            f"/v1/tasks/{task['job_id']}/cancel", headers=self.alice
        )
        self.assertEqual(cancelled.status_code, 202, cancelled.text)
        self.assertEqual(cancelled.json()["status"], "failed")
        self.assertEqual(
            self.client.delete(
                f"/v1/documents/{document['id']}", headers=self.alice
            ).status_code,
            204,
        )
        self.assertEqual(
            self.client.get(
                f"/v1/documents/{document['id']}", headers=self.alice
            ).status_code,
            404,
        )

    def test_dictionary_sync_and_alias(self) -> None:
        sync = self.client.post(
            "/v1/business-dictionary/sync", headers=self.root, json={"source": "snapshot"}
        )
        self.assertEqual(sync.status_code, 200, sync.text)
        self.assertEqual(
            self.client.post(
                "/v1/business-dictionary/sync", headers=self.alice
            ).status_code,
            403,
        )
        entries = self.client.get(
            "/v1/business-dictionary?type=category&limit=1", headers=self.root
        ).json()["entries"]
        self.assertTrue(entries)
        code = entries[0]["business_code"]
        alias = "R3别名"
        added = self.client.post(
            "/v1/business-dictionary/aliases",
            headers=self.root,
            json={"type": "category", "business_code": code, "alias": alias},
        )
        self.assertEqual(added.status_code, 200, added.text)
        found = self.client.get(
            f"/v1/business-dictionary?type=category&q={alias}", headers=self.root
        ).json()
        self.assertGreaterEqual(found["total"], 1)
        pending = self.client.get(
            "/v1/business-dictionary/pending", headers=self.root
        )
        self.assertEqual(pending.status_code, 200, pending.text)
        self.assertIn("items", pending.json())
        self.assertEqual(
            self.client.get(
                "/v1/business-dictionary/pending", headers=self.alice
            ).status_code,
            403,
        )

    def test_audit_scope(self) -> None:
        workspace = self._workspace(self.alice, "Audit WS")
        kb = self._kb(self.alice, workspace["id"], "Audit KB")
        own = self.client.get(
            f"/v1/audit-logs?workspace_id={workspace['id']}", headers=self.alice
        )
        self.assertEqual(own.status_code, 200, own.text)
        self.assertTrue(
            any(row["action"] == "kb.create" for row in own.json()), own.json()
        )
        foreign = self.client.get(
            f"/v1/audit-logs?workspace_id={workspace['id']}", headers=self.bob
        )
        self.assertIn(foreign.status_code, (403, 404), foreign.text)
        global_view = self.client.get("/v1/audit-logs", headers=self.root)
        self.assertEqual(global_view.status_code, 200, global_view.text)
        self.assertTrue(
            any(row["workspace_id"] == workspace["id"] for row in global_view.json())
        )


if __name__ == "__main__":
    unittest.main()
