"""L2 集成链路：认证登录模块（M1）。"""

import uuid

from qa.conftest import api_login


async def _unique(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


async def test_login_success_returns_token_pair(client):
    resp = await client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "admin123"}
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["access_token"]
    assert data["refresh_token"]
    assert data["token_type"] == "bearer"
    assert data["expires_in"] > 0


async def test_login_wrong_password_rejected(client):
    resp = await client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "wrong-pass"}
    )
    assert resp.status_code == 401
    assert resp.json()["code"] == 20001


async def test_me_returns_roles_and_permissions(client, super_token):
    resp = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {super_token}"}
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["username"] == "admin"
    assert [r["code"] for r in data["roles"]] == ["super_admin"]
    assert "user.manage" in data["permissions"]
    assert "role.manage" in data["permissions"]
    assert len(data["permissions"]) == 11


async def test_refresh_flow(client, super_token):
    login = await client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "admin123"}
    )
    refresh_token = login.json()["data"]["refresh_token"]
    resp = await client.post(
        "/api/v1/auth/refresh",
        headers={"Authorization": f"Bearer {refresh_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["access_token"]


async def test_access_token_cannot_refresh(client, super_token):
    resp = await client.post(
        "/api/v1/auth/refresh",
        headers={"Authorization": f"Bearer {super_token}"},
    )
    assert resp.status_code == 401


async def test_register_assigns_member_role(client):
    username = await _unique("reg")
    resp = await client.post(
        "/api/v1/auth/register",
        json={"username": username, "password": "Test@1234", "full_name": "注册用户"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert [r["code"] for r in data["roles"]] == ["member"]
    assert data["permissions"] == []


async def test_register_duplicate_rejected(client):
    username = await _unique("regdup")
    payload = {"username": username, "password": "Test@1234"}
    first = await client.post("/api/v1/auth/register", json=payload)
    second = await client.post("/api/v1/auth/register", json=payload)
    assert first.status_code == 200
    assert second.status_code == 400
    assert second.json()["code"] == 30010


async def test_disabled_user_cannot_login(client, super_token):
    username = await _unique("disabled")
    create = await client.post(
        "/api/v1/users",
        headers={"Authorization": f"Bearer {super_token}"},
        json={"username": username, "password": "Test@1234", "role_codes": ["member"]},
    )
    uid = create.json()["data"]["id"]
    await client.patch(
        f"/api/v1/users/{uid}/active",
        headers={"Authorization": f"Bearer {super_token}"},
        json={"is_active": False},
    )
    resp = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": "Test@1234"}
    )
    assert resp.status_code == 401
