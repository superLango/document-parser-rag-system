"""L2 集成链路：工作空间、群组并集授权、API Key、审计导出（M13-M16）。"""

import csv
import io
import uuid


async def _unique(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


async def _make_user(client, super_token, role_codes=("member",)):
    username = await _unique("p2u")
    resp = await client.post(
        "/api/v1/users",
        headers={"Authorization": f"Bearer {super_token}"},
        json={
            "username": username,
            "password": "Test@1234",
            "role_codes": list(role_codes),
        },
    )
    assert resp.status_code == 200, resp.text
    return username, resp.json()["data"]["id"]


async def _login(client, username):
    resp = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": "Test@1234"}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["access_token"]


async def test_workspace_api_lifecycle(client, super_token):
    h = {"Authorization": f"Bearer {super_token}"}
    code = await _unique("ws")
    created = await client.post(
        "/api/v1/workspaces",
        headers=h,
        json={"name": "集成工作空间", "code": code, "description": "P2"},
    )
    assert created.status_code == 200
    ws = created.json()["data"]
    assert ws["my_role"] == "owner"
    assert ws["member_count"] == 1

    listed = await client.get("/api/v1/workspaces?keyword=%E9%9B%86%E6%88%90%E5%B7%A5%E4%BD%9C%E7%A9%BA%E9%97%B4", headers=h)
    assert listed.status_code == 200
    assert listed.json()["data"]["total"] >= 1
    assert any(item["code"] == code for item in listed.json()["data"]["items"])

    detail = await client.get(f"/api/v1/workspaces/{ws['id']}", headers=h)
    assert detail.status_code == 200
    updated = await client.put(
        f"/api/v1/workspaces/{ws['id']}",
        headers=h,
        json={"name": "集成工作空间V2"},
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["name"] == "集成工作空间V2"

    deleted = await client.delete(f"/api/v1/workspaces/{ws['id']}", headers=h)
    assert deleted.status_code == 200
    assert (await client.get(f"/api/v1/workspaces/{ws['id']}", headers=h)).status_code == 400


async def test_workspace_members_api(client, super_token):
    h = {"Authorization": f"Bearer {super_token}"}
    owner_name, _ = await _make_user(client, super_token)
    member_name, member_id = await _make_user(client, super_token)
    owner_token = await _login(client, owner_name)
    ws = (
        await client.post(
            "/api/v1/workspaces",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"name": "成员工作空间", "code": await _unique("wsm")},
        )
    ).json()["data"]
    added = await client.post(
        f"/api/v1/workspaces/{ws['id']}/members",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"username": member_name, "role": "viewer"},
    )
    assert added.status_code == 200
    role = await client.put(
        f"/api/v1/workspaces/{ws['id']}/members/{member_id}",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"role": "admin"},
    )
    assert role.status_code == 200
    transferred = await client.post(
        f"/api/v1/workspaces/{ws['id']}/transfer",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"target_user_id": member_id},
    )
    assert transferred.status_code == 200
    detail = await client.get(
        f"/api/v1/workspaces/{ws['id']}",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert detail.json()["data"]["owner_id"] == member_id
    assert detail.json()["data"]["my_role"] == "admin"
    removed = await client.delete(
        f"/api/v1/workspaces/{ws['id']}/members/{member_id}",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert removed.status_code == 400  # 新 owner 不能移除自己


async def test_group_kb_grant_union_via_api(client, super_token):
    """M14：群组授权并集在 API 层生效。"""
    h = {"Authorization": f"Bearer {super_token}"}
    owner_name, _ = await _make_user(client, super_token)
    member_name, _ = await _make_user(client, super_token)
    owner_token = await _login(client, owner_name)
    member_token = await _login(client, member_name)

    ws = (
        await client.post(
            "/api/v1/workspaces",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"name": "群组工作空间", "code": await _unique("wsg")},
        )
    ).json()["data"]
    group = (
        await client.post(
            f"/api/v1/workspaces/{ws['id']}/groups",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"name": "研发组", "code": await _unique("grp")},
        )
    ).json()["data"]
    assert (
        await client.post(
            f"/api/v1/workspaces/{ws['id']}/groups/{group['id']}/members",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"username": member_name},
        )
    ).status_code == 200

    kb = (
        await client.post(
            "/api/v1/kb",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"name": "群组知识库", "domain_code": "general"},
        )
    ).json()["data"]
    granted = await client.post(
        f"/api/v1/kb/{kb['id']}/groups",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"group_id": group["id"], "role": "editor"},
    )
    assert granted.status_code == 200

    listed = await client.get(
        "/api/v1/kb?keyword=群组知识库", headers={"Authorization": f"Bearer {member_token}"}
    )
    assert listed.status_code == 200
    items = listed.json()["data"]["items"]
    assert len(items) == 1
    assert items[0]["my_role"] == "editor"

    update = await client.put(
        f"/api/v1/kb/{kb['id']}",
        headers={"Authorization": f"Bearer {member_token}"},
        json={"name": "越权改名"},
    )
    assert update.status_code == 403  # editor 不能管理

    revoked = await client.delete(
        f"/api/v1/kb/{kb['id']}/groups/{group['id']}",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert revoked.status_code == 200
    listed2 = await client.get(
        "/api/v1/kb?keyword=群组知识库", headers={"Authorization": f"Bearer {member_token}"}
    )
    assert listed2.json()["data"]["total"] == 0


async def test_api_key_lifecycle_api(client, super_token):
    h = {"Authorization": f"Bearer {super_token}"}
    created = await client.post(
        "/api/v1/api-keys",
        headers=h,
        json={"name": "集成密钥", "scopes": ["user.view"]},
    )
    assert created.status_code == 200
    secret = created.json()["data"]["secret"]
    assert secret.startswith("hd_")
    key_id = created.json()["data"]["id"]

    listed = await client.get("/api/v1/api-keys", headers=h)
    assert listed.status_code == 200
    assert all("secret" not in item for item in listed.json()["data"])

    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {secret}"})
    assert me.status_code == 200
    assert me.json()["data"]["username"] == "admin"
    scoped = await client.get("/api/v1/roles", headers={"Authorization": f"Bearer {secret}"})
    assert scoped.status_code == 403  # scopes 仅 user.view

    revoked = await client.delete(f"/api/v1/api-keys/{key_id}", headers=h)
    assert revoked.status_code == 200
    after = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {secret}"})
    assert after.status_code == 401


async def test_audit_export_csv(client, super_token):
    h = {"Authorization": f"Bearer {super_token}"}
    resp = await client.get("/api/v1/audit-logs/export", headers=h)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "attachment" in resp.headers.get("content-disposition", "")
    rows = list(csv.DictReader(io.StringIO(resp.text)))
    assert len(rows) > 0
    assert "action" in rows[0]


async def test_audit_export_denied_for_admin(client, super_token):
    username, _ = await _make_user(client, super_token, role_codes=("admin",))
    admin_token = await _login(client, username)
    resp = await client.get(
        "/api/v1/audit-logs/export",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 403
