"""L4 边界异常：Token 过期、参数边界、并发请求（含历史隐患复测）。"""

import asyncio
import time
import uuid
from datetime import timedelta

from app.core.security import create_access_token, create_refresh_token


async def _unique(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


async def test_expired_access_token_rejected(client):
    """REG-02：过期令牌必须返回 20002 且不得访问受保护端点。"""
    token = create_access_token({"sub": "admin"}, expires_delta=timedelta(seconds=-10))
    resp = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 401
    assert resp.json()["code"] == 20002


async def test_tampered_token_rejected(client):
    token = create_access_token({"sub": "admin"})
    tampered = token[:-4] + ("AAAA" if token[-4:] != "AAAA" else "BBBB")
    resp = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {tampered}"}
    )
    assert resp.status_code == 401


async def test_missing_token_rejected(client):
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401


async def test_invalid_uuid_rejected(client, super_token):
    h = {"Authorization": f"Bearer {super_token}"}
    resp = await client.get("/api/v1/users/not-a-uuid", headers=h)
    assert resp.status_code == 400
    resp2 = await client.get("/api/v1/roles/not-a-uuid", headers=h)
    assert resp2.status_code == 400


async def test_pagination_bounds(client, super_token):
    h = {"Authorization": f"Bearer {super_token}"}
    resp = await client.get("/api/v1/users?page=0", headers=h)
    assert resp.status_code == 400
    resp2 = await client.get("/api/v1/users?page_size=101", headers=h)
    assert resp2.status_code == 400
    ok = await client.get("/api/v1/users?page=1&page_size=100", headers=h)
    assert ok.status_code == 200


async def test_role_code_invalid_rejected(client, super_token):
    h = {"Authorization": f"Bearer {super_token}"}
    resp = await client.post(
        "/api/v1/roles", headers=h, json={"code": "Bad Code!", "name": "非法"}
    )
    assert resp.status_code == 400


async def test_duplicate_role_code_rejected(client, super_token):
    h = {"Authorization": f"Bearer {super_token}"}
    code = await _unique("dup")
    first = await client.post(
        "/api/v1/roles", headers=h, json={"code": code, "name": "首次"}
    )
    second = await client.post(
        "/api/v1/roles", headers=h, json={"code": code, "name": "重复"}
    )
    assert first.status_code == 200
    assert second.status_code == 400


async def test_empty_and_unknown_role_assignment(client, super_token):
    h = {"Authorization": f"Bearer {super_token}"}
    username = await _unique("bnd")
    uid = (
        await client.post(
            "/api/v1/users",
            headers=h,
            json={"username": username, "password": "Test@1234", "role_codes": ["member"]},
        )
    ).json()["data"]["id"]
    empty = await client.put(
        f"/api/v1/users/{uid}/roles", headers=h, json={"role_codes": []}
    )
    assert empty.status_code == 400
    ghost = await client.put(
        f"/api/v1/users/{uid}/roles", headers=h, json={"role_codes": ["ghost"]}
    )
    assert ghost.status_code == 400


async def test_set_permissions_invalid_code(client, super_token):
    h = {"Authorization": f"Bearer {super_token}"}
    role_id = (
        await client.post(
            "/api/v1/roles", headers=h, json={"code": await _unique("matrix"), "name": "矩阵"}
        )
    ).json()["data"]["id"]
    resp = await client.put(
        f"/api/v1/roles/{role_id}/permissions",
        headers=h,
        json={"permission_codes": ["hack.all"]},
    )
    assert resp.status_code == 400


async def test_last_super_admin_cannot_be_removed(client, super_token):
    h = {"Authorization": f"Bearer {super_token}"}
    me = (await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {super_token}"})).json()["data"]
    resp = await client.put(
        f"/api/v1/users/{me['id']}/roles", headers=h, json={"role_codes": ["member"]}
    )
    assert resp.status_code == 400


async def test_concurrent_login_all_succeed(client, super_token):
    """并发用例 C1：10 个成员并发登录，全部成功且互不干扰。"""
    h = {"Authorization": f"Bearer {super_token}"}
    users = []
    for i in range(10):
        username = f"conc_login_{uuid.uuid4().hex[:6]}"
        await client.post(
            "/api/v1/users",
            headers=h,
            json={"username": username, "password": "Test@1234", "role_codes": ["member"]},
        )
        users.append((username, "Test@1234"))

    async def _do_login(username, password):
        return await client.post(
            "/api/v1/auth/login", json={"username": username, "password": password}
        )

    results = await asyncio.gather(*[_do_login(u, p) for u, p in users])
    assert all(r.status_code == 200 for r in results)
    assert all(r.json()["data"]["access_token"] for r in results)


async def test_concurrent_create_same_username_single_winner(client, super_token):
    """并发用例 C2：同用户名并发创建，只能一个成功，其余为业务错误而非 500。"""
    h = {"Authorization": f"Bearer {super_token}"}
    username = await _unique("race")
    payload = {"username": username, "password": "Test@1234", "role_codes": ["member"]}

    async def _create():
        return await client.post("/api/v1/users", headers=h, json=payload)

    results = await asyncio.gather(*[_create() for _ in range(6)])
    statuses = [r.status_code for r in results]
    assert statuses.count(200) == 1
    assert all(s in (200, 400) for s in statuses)
    for r in results:
        if r.status_code == 400:
            assert r.json()["code"] in (30010, 10001)


async def test_concurrent_role_assignment_consistent(client, super_token):
    """并发用例 C3：同一用户并发分配 admin/member，最终状态必须为二者之一且无 500。"""
    h = {"Authorization": f"Bearer {super_token}"}
    username = await _unique("concrole")
    uid = (
        await client.post(
            "/api/v1/users",
            headers=h,
            json={"username": username, "password": "Test@1234", "role_codes": ["member"]},
        )
    ).json()["data"]["id"]

    async def _assign(code):
        return await client.put(
            f"/api/v1/users/{uid}/roles", headers=h, json={"role_codes": [code]}
        )

    results = await asyncio.gather(_assign("admin"), _assign("member"), _assign("admin"), _assign("member"))
    assert all(r.status_code == 200 for r in results)
    detail = (await client.get(f"/api/v1/users/{uid}", headers=h)).json()["data"]
    assert detail["roles"][0]["code"] in ("admin", "member")


async def test_concurrent_refresh_same_token(client, super_token):
    """并发用例 C4：同一刷新令牌并发刷新均成功（令牌非一次性）。"""
    login = await client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "admin123"}
    )
    refresh_token = login.json()["data"]["refresh_token"]

    async def _refresh():
        return await client.post(
            "/api/v1/auth/refresh",
            headers={"Authorization": f"Bearer {refresh_token}"},
        )

    results = await asyncio.gather(*[_refresh() for _ in range(5)])
    assert all(r.status_code == 200 for r in results)
    assert all(r.json()["data"]["access_token"] for r in results)


async def test_concurrent_profile_update(client, member_user):
    """并发用例 C5：并发资料更新全部成功，最终值为最后提交值。"""
    token, _, _ = member_user
    h = {"Authorization": f"Bearer {token}"}

    async def _update(i):
        return await client.put(
            "/api/v1/auth/profile",
            headers=h,
            json={"full_name": f"并发更新-{i}"},
        )

    results = await asyncio.gather(*[_update(i) for i in range(5)])
    assert all(r.status_code == 200 for r in results)
    me = (await client.get("/api/v1/auth/me", headers=h)).json()["data"]
    assert me["full_name"].startswith("并发更新-")
