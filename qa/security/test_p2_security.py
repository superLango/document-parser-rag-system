"""L5 安全渗透：工作空间/群组/API Key/导出（M13-M16）。"""

import uuid


async def _unique(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


async def _make_user(client, super_token):
    username = await _unique("p2s")
    resp = await client.post(
        "/api/v1/users",
        headers={"Authorization": f"Bearer {super_token}"},
        json={"username": username, "password": "Test@1234", "role_codes": ["member"]},
    )
    return username, resp.json()["data"]["id"]


async def _login(client, username):
    resp = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": "Test@1234"}
    )
    return resp.json()["data"]["access_token"]


async def test_non_member_workspace_access(client, super_token):
    owner_name, _ = await _make_user(client, super_token)
    stranger_name, _ = await _make_user(client, super_token)
    owner_token = await _login(client, owner_name)
    stranger_token = await _login(client, stranger_name)
    ws = (
        await client.post(
            "/api/v1/workspaces",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"name": "安全工作空间", "code": await _unique("secws")},
        )
    ).json()["data"]
    h = {"Authorization": f"Bearer {stranger_token}"}
    assert (await client.get(f"/api/v1/workspaces/{ws['id']}", headers=h)).status_code == 403
    assert (await client.get(f"/api/v1/workspaces/{ws['id']}/members", headers=h)).status_code == 403
    assert (
        await client.put(f"/api/v1/workspaces/{ws['id']}", headers=h, json={"name": "x"})
    ).status_code == 403


async def test_viewer_cannot_grant_kb_to_group(client, super_token):
    owner_name, _ = await _make_user(client, super_token)
    viewer_name, _ = await _make_user(client, super_token)
    owner_token = await _login(client, owner_name)
    viewer_token = await _login(client, viewer_name)
    ws = (
        await client.post(
            "/api/v1/workspaces",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"name": "授权安全", "code": await _unique("secg")},
        )
    ).json()["data"]
    group = (
        await client.post(
            f"/api/v1/workspaces/{ws['id']}/groups",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"name": "组", "code": await _unique("grp")},
        )
    ).json()["data"]
    kb = (
        await client.post(
            "/api/v1/kb",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"name": "授权安全库", "domain_code": "general"},
        )
    ).json()["data"]
    inv = (
        await client.post(
            f"/api/v1/kb/{kb['id']}/invitations",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"username": viewer_name, "role": "viewer"},
        )
    ).json()["data"]
    await client.post(
        f"/api/v1/kb/invitations/{inv['token']}/accept",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    resp = await client.post(
        f"/api/v1/kb/{kb['id']}/groups",
        headers={"Authorization": f"Bearer {viewer_token}"},
        json={"group_id": group["id"], "role": "admin"},
    )
    assert resp.status_code == 403


async def test_api_key_scopes_cannot_bypass(client, super_token):
    h = {"Authorization": f"Bearer {super_token}"}
    secret = (
        await client.post(
            "/api/v1/api-keys", headers=h, json={"name": "受限", "scopes": ["user.view"]}
        )
    ).json()["data"]["secret"]
    assert (
        await client.get("/api/v1/users", headers={"Authorization": f"Bearer {secret}"})
    ).status_code == 200
    assert (
        await client.post(
            "/api/v1/users",
            headers={"Authorization": f"Bearer {secret}"},
            json={"username": "evil", "password": "Test@1234"},
        )
    ).status_code == 403
    assert (
        await client.get("/api/v1/roles", headers={"Authorization": f"Bearer {secret}"})
    ).status_code == 403


async def test_api_key_secret_not_exposed_again(client, super_token):
    h = {"Authorization": f"Bearer {super_token}"}
    created = (
        await client.post("/api/v1/api-keys", headers=h, json={"name": "一次性"})
    ).json()["data"]
    assert created["secret"]
    listed = (
        await client.get("/api/v1/api-keys", headers=h)
    ).json()["data"]
    match = [k for k in listed if k["id"] == created["id"]]
    assert match and "secret" not in match[0]


async def test_member_export_denied(client, member_user):
    token, _, _ = member_user
    resp = await client.get(
        "/api/v1/audit-logs/export", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 403


async def test_pending_workspace_and_api_keys_denied(client, super_token):
    from app.core.config import settings

    original = settings.REGISTRATION_DEFAULT_PENDING
    settings.REGISTRATION_DEFAULT_PENDING = True
    try:
        username = await _unique("pendingp2")
        await client.post(
            "/api/v1/auth/register", json={"username": username, "password": "Test@1234"}
        )
        token = await _login(client, username)
        h = {"Authorization": f"Bearer {token}"}
        assert (await client.get("/api/v1/workspaces", headers=h)).status_code == 403
        assert (await client.get("/api/v1/api-keys", headers=h)).status_code == 200
    finally:
        settings.REGISTRATION_DEFAULT_PENDING = original
