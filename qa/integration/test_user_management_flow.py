"""L2 集成链路：用户管理模块（M4）。"""

import uuid

from qa.conftest import api_login


async def _unique(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


async def test_create_list_get_user_with_roles(client, super_token):
    h = {"Authorization": f"Bearer {super_token}"}
    username = await _unique("user")
    created = await client.post(
        "/api/v1/users",
        headers=h,
        json={
            "username": username,
            "password": "Test@1234",
            "email": f"{username}@example.com",
            "full_name": "集成用户",
            "department": "研发部",
            "role_codes": ["member"],
        },
    )
    assert created.status_code == 200
    body = created.json()["data"]
    assert body["roles"][0]["code"] == "member"
    assert body["is_superuser"] is False

    listed = await client.get(
        f"/api/v1/users?keyword={username}", headers=h
    )
    assert listed.status_code == 200
    assert listed.json()["data"]["total"] == 1
    assert listed.json()["data"]["items"][0]["roles"][0]["code"] == "member"

    got = await client.get(f"/api/v1/users/{body['id']}", headers=h)
    assert got.status_code == 200
    assert got.json()["data"]["username"] == username


async def test_update_roles_and_profile(client, super_token):
    h = {"Authorization": f"Bearer {super_token}"}
    username = await _unique("upd")
    created = (
        await client.post(
            "/api/v1/users",
            headers=h,
            json={"username": username, "password": "Test@1234", "role_codes": ["member"]},
        )
    ).json()["data"]
    updated = await client.put(
        f"/api/v1/users/{created['id']}",
        headers=h,
        json={"full_name": "升级用户", "role_codes": ["admin"]},
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["roles"][0]["code"] == "admin"
    assert updated.json()["data"]["full_name"] == "升级用户"


async def test_toggle_active_and_login_blocked(client, super_token):
    h = {"Authorization": f"Bearer {super_token}"}
    username = await _unique("toggle")
    created = (
        await client.post(
            "/api/v1/users",
            headers=h,
            json={"username": username, "password": "Test@1234", "role_codes": ["member"]},
        )
    ).json()["data"]
    resp = await client.patch(
        f"/api/v1/users/{created['id']}/active", headers=h, json={"is_active": False}
    )
    assert resp.status_code == 200
    login = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": "Test@1234"}
    )
    assert login.status_code == 401
    resp2 = await client.patch(
        f"/api/v1/users/{created['id']}/active", headers=h, json={"is_active": True}
    )
    assert resp2.status_code == 200
    login2 = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": "Test@1234"}
    )
    assert login2.status_code == 200


async def test_toggle_superuser_syncs_role(client, super_token):
    h = {"Authorization": f"Bearer {super_token}"}
    username = await _unique("su")
    created = (
        await client.post(
            "/api/v1/users",
            headers=h,
            json={"username": username, "password": "Test@1234", "role_codes": ["member"]},
        )
    ).json()["data"]
    resp = await client.patch(
        f"/api/v1/users/{created['id']}/superuser", headers=h, json={"is_superuser": True}
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["is_superuser"] is True
    detail = (
        await client.get(f"/api/v1/users/{created['id']}", headers=h)
    ).json()["data"]
    assert detail["roles"][0]["code"] == "super_admin"
    resp2 = await client.patch(
        f"/api/v1/users/{created['id']}/superuser", headers=h, json={"is_superuser": False}
    )
    assert resp2.status_code == 200
    detail2 = (
        await client.get(f"/api/v1/users/{created['id']}", headers=h)
    ).json()["data"]
    assert detail2["roles"][0]["code"] == "member"


async def test_admin_reset_password_flow(client, super_token):
    h = {"Authorization": f"Bearer {super_token}"}
    username = await _unique("reset")
    created = (
        await client.post(
            "/api/v1/users",
            headers=h,
            json={"username": username, "password": "Test@1234", "role_codes": ["member"]},
        )
    ).json()["data"]
    resp = await client.post(
        f"/api/v1/users/{created['id']}/reset-password",
        headers=h,
        json={"new_password": "NewPass@5678"},
    )
    assert resp.status_code == 200
    old = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": "Test@1234"}
    )
    assert old.status_code == 401
    new_login = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": "NewPass@5678"}
    )
    assert new_login.status_code == 200


async def test_delete_user_blocks_login(client, super_token):
    h = {"Authorization": f"Bearer {super_token}"}
    username = await _unique("del")
    created = (
        await client.post(
            "/api/v1/users",
            headers=h,
            json={"username": username, "password": "Test@1234", "role_codes": ["member"]},
        )
    ).json()["data"]
    resp = await client.delete(f"/api/v1/users/{created['id']}", headers=h)
    assert resp.status_code == 200
    login = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": "Test@1234"}
    )
    assert login.status_code == 401


async def test_self_protection_rules(client, super_token):
    me = (await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {super_token}"})).json()["data"]
    uid = me["id"]
    h = {"Authorization": f"Bearer {super_token}"}
    assert (await client.patch(f"/api/v1/users/{uid}/active", headers=h, json={"is_active": False})).status_code == 400
    assert (await client.delete(f"/api/v1/users/{uid}", headers=h)).status_code == 400
    assert (await client.patch(f"/api/v1/users/{uid}/superuser", headers=h, json={"is_superuser": False})).status_code == 400
    assert (
        await client.put(f"/api/v1/users/{uid}/roles", headers=h, json={"role_codes": ["member"]})
    ).status_code == 400
