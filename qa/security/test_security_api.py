"""L5 安全渗透：越权、注入、暴力锁定、敏感信息、算法混淆。"""

import asyncio
import time
import uuid

from app.core.security import create_access_token, create_refresh_token


async def _unique(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


async def test_member_cannot_access_admin_endpoints(client, member_user):
    token, _, _ = member_user
    h = {"Authorization": f"Bearer {token}"}
    for path in (
        "/api/v1/users",
        "/api/v1/roles",
        "/api/v1/audit-logs",
        "/api/v1/dashboard/stats",
        "/api/v1/dashboard/trends",
    ):
        resp = await client.get(path, headers=h)
        assert resp.status_code == 403, f"{path} 应拒绝：{resp.status_code}"


async def test_member_cannot_mutate_admin_resources(client, member_user, super_token):
    token, _, _ = member_user
    h = {"Authorization": f"Bearer {token}"}
    admin_id = (await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {super_token}"})).json()["data"]["id"]
    resp = await client.put(
        f"/api/v1/users/{admin_id}",
        headers=h,
        json={"full_name": "越权改名"},
    )
    assert resp.status_code == 403
    resp2 = await client.delete(f"/api/v1/users/{admin_id}", headers=h)
    assert resp2.status_code == 403


async def test_no_token_rejected_on_all_protected(client):
    for path in ("/api/v1/users", "/api/v1/roles", "/api/v1/audit-logs", "/api/v1/dashboard/stats"):
        resp = await client.get(path)
        assert resp.status_code == 401


async def test_sql_injection_keyword_safe(client, super_token):
    h = {"Authorization": f"Bearer {super_token}"}
    payload = "' OR 1=1 --"
    resp = await client.get(f"/api/v1/users?keyword={payload}", headers=h)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total"] == 0


async def test_brute_force_lock(client, super_token):
    """5 次失败后锁定，正确密码也会被拒绝（锁定提示）。"""
    h = {"Authorization": f"Bearer {super_token}"}
    username = await _unique("brute")
    await client.post(
        "/api/v1/users",
        headers=h,
        json={"username": username, "password": "Test@1234", "role_codes": ["member"]},
    )
    for _ in range(5):
        resp = await client.post(
            "/api/v1/auth/login", json={"username": username, "password": "Wrong@123"}
        )
        assert resp.status_code == 401
    locked = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": "Test@1234"}
    )
    assert locked.status_code == 400
    assert "锁定" in locked.json()["message"]


async def test_xss_stored_in_profile_escaped_by_frontend_contract(client, member_user):
    """后端按原样存储，前端负责转义；此处校验存储与回读契约。"""
    token, _, _ = member_user
    payload = "<script>alert('xss')</script>"
    resp = await client.put(
        "/api/v1/auth/profile",
        headers={"Authorization": f"Bearer {token}"},
        json={"full_name": payload},
    )
    assert resp.status_code == 200
    me = (
        await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    ).json()["data"]
    assert me["full_name"] == payload


async def test_audit_details_never_contain_plaintext_password(client):
    username = await _unique("leak")
    await client.post(
        "/api/v1/auth/register",
        json={"username": username, "password": "P@ssw0rdLeak99", "full_name": "泄露检测"},
    )

    async def _check():
        login = await client.post(
            "/api/v1/auth/login", json={"username": "admin", "password": "admin123"}
        )
        token = login.json()["data"]["access_token"]
        logs = (
            await client.get(
                "/api/v1/audit-logs?page=1&page_size=50",
                headers={"Authorization": f"Bearer {token}"},
            )
        ).json()["data"]["items"]
        body_text = " ".join(str(item.get("details")) for item in logs)
        return "P@ssw0rdLeak99" not in body_text

    deadline = time.monotonic() + 4
    ok = False
    while time.monotonic() < deadline:
        if await _check():
            ok = True
            break
        await asyncio.sleep(0.2)
    assert ok, "审计日志中不应出现明文密码"


def _none_alg_token() -> str:
    import base64
    import json

    def b64(obj) -> str:
        raw = json.dumps(obj, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    return f"{b64({'alg': 'none', 'typ': 'JWT'})}.{b64({'sub': 'admin', 'exp': 9999999999})}."


async def test_alg_none_token_rejected(client):
    resp = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {_none_alg_token()}"}
    )
    assert resp.status_code == 401


async def test_wrong_secret_token_rejected(client):
    from jose import jwt

    token = jwt.encode(
        {"sub": "admin", "exp": 9999999999},
        "attacker_secret_key_that_is_long_enough_xx",
        algorithm="HS256",
    )
    resp = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 401


async def test_access_token_cannot_be_used_as_refresh(client, super_token):
    resp = await client.post(
        "/api/v1/auth/refresh",
        headers={"Authorization": f"Bearer {super_token}"},
    )
    assert resp.status_code == 401


async def test_super_admin_matrix_immutable_via_api(client, super_token):
    h = {"Authorization": f"Bearer {super_token}"}
    roles = (await client.get("/api/v1/roles", headers=h)).json()["data"]
    super_role = next(r for r in roles if r["code"] == "super_admin")
    resp = await client.put(
        f"/api/v1/roles/{super_role['id']}/permissions",
        headers=h,
        json={"permission_codes": ["user.view"]},
    )
    assert resp.status_code == 400
    resp2 = await client.delete(f"/api/v1/roles/{super_role['id']}", headers=h)
    assert resp2.status_code == 400


async def test_register_sql_injection_username(client, db_session):
    from sqlalchemy import text as sa_text

    resp = await client.post(
        "/api/v1/auth/register",
        json={"username": "'; DROP TABLE users; --", "password": "Test@1234"},
    )
    # 参数化查询：200（按原样创建）或 400（校验失败）均可，绝不允许 500/注入生效
    assert resp.status_code in (200, 400)
    table = (
        await db_session.execute(sa_text("SELECT to_regclass('public.users')"))
    ).scalar_one()
    assert table is not None
