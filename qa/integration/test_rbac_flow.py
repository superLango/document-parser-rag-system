"""L2 集成链路：RBAC 角色权限模块（M3）。"""

import uuid


async def _unique(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


async def test_admin_role_scope(client, super_token):
    """admin 可看角色/用户/审计，但不可管理角色。"""
    username = await _unique("adminrole")
    resp = await client.post(
        "/api/v1/users",
        headers={"Authorization": f"Bearer {super_token}"},
        json={
            "username": username,
            "password": "Test@1234",
            "role_codes": ["admin"],
        },
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["is_superuser"] is False
    admin_token = (
        await client.post(
            "/api/v1/auth/login", json={"username": username, "password": "Test@1234"}
        )
    ).json()["data"]["access_token"]
    h = {"Authorization": f"Bearer {admin_token}"}
    assert (await client.get("/api/v1/roles", headers=h)).status_code == 200
    assert (await client.get("/api/v1/users", headers=h)).status_code == 200
    assert (await client.get("/api/v1/audit-logs", headers=h)).status_code == 200
    role_id = (await client.get("/api/v1/roles", headers=h)).json()["data"][0]["id"]
    blocked = await client.post(
        "/api/v1/roles",
        headers=h,
        json={"code": "blocked_role", "name": "越权角色"},
    )
    assert blocked.status_code == 403
    blocked2 = await client.put(
        f"/api/v1/roles/{role_id}/permissions",
        headers=h,
        json={"permission_codes": ["audit.view"]},
    )
    assert blocked2.status_code == 403


async def test_custom_role_full_lifecycle(client, super_token):
    h = {"Authorization": f"Bearer {super_token}"}
    code = await _unique("customrole")
    created = await client.post(
        "/api/v1/roles", headers=h, json={"code": code, "name": "自定义角色", "description": "QA"}
    )
    assert created.status_code == 200
    role_id = created.json()["data"]["id"]

    matrix = await client.put(
        f"/api/v1/roles/{role_id}/permissions",
        headers=h,
        json={"permission_codes": ["user.view", "audit.view"]},
    )
    assert matrix.status_code == 200
    assert sorted(matrix.json()["data"]) == ["audit.view", "user.view"]

    detail = await client.get(f"/api/v1/roles/{role_id}", headers=h)
    assert detail.status_code == 200
    assert sorted(detail.json()["data"]["permissions"]) == ["audit.view", "user.view"]

    updated = await client.put(
        f"/api/v1/roles/{role_id}", headers=h, json={"name": "自定义角色V2"}
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["name"] == "自定义角色V2"

    username = await _unique("customuser")
    created_user = await client.post(
        "/api/v1/users",
        headers=h,
        json={"username": username, "password": "Test@1234", "role_codes": ["member"]},
    )
    uid = created_user.json()["data"]["id"]
    assigned = await client.put(
        f"/api/v1/users/{uid}/roles", headers=h, json={"role_codes": [code]}
    )
    assert assigned.status_code == 200
    assert assigned.json()["data"]["roles"][0]["code"] == code

    token = (
        await client.post(
            "/api/v1/auth/login", json={"username": username, "password": "Test@1234"}
        )
    ).json()["data"]["access_token"]
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert sorted(me.json()["data"]["permissions"]) == ["audit.view", "user.view"]

    deleted = await client.delete(f"/api/v1/roles/{role_id}", headers=h)
    assert deleted.status_code == 200
    me2 = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me2.json()["data"]["permissions"] == []


async def test_system_roles_visible_and_immutable_via_api(client, super_token):
    h = {"Authorization": f"Bearer {super_token}"}
    roles = (await client.get("/api/v1/roles", headers=h)).json()["data"]
    codes = {r["code"]: r for r in roles}
    assert {"super_admin", "admin", "member", "pending"} <= set(codes)
    admin_role = codes["admin"]
    resp = await client.delete(f"/api/v1/roles/{admin_role['id']}", headers=h)
    assert resp.status_code == 400
    resp2 = await client.put(
        f"/api/v1/roles/{admin_role['id']}/permissions",
        headers=h,
        json={"permission_codes": []},
    )
    assert resp2.status_code == 400


async def test_permissions_payload_supports_frontend_guards(client, super_token, member_user):
    """M8 L2：/auth/me 返回的权限点可作为前端路由/菜单守卫依据。"""
    admin_me = (
        await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {super_token}"})
    ).json()["data"]
    for code in ("user.view", "role.view", "audit.view", "system.stats"):
        assert code in admin_me["permissions"]
    member_token, _, _ = member_user
    member_me = (
        await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {member_token}"})
    ).json()["data"]
    for code in ("user.view", "role.view", "audit.view"):
        assert code not in member_me["permissions"]
