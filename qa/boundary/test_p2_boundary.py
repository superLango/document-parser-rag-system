"""L4 边界异常：工作空间、群组、API Key、审计导出（M13-M16）。"""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone


async def _unique(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


async def _make_user(client, super_token):
    username = await _unique("p2b")
    resp = await client.post(
        "/api/v1/users",
        headers={"Authorization": f"Bearer {super_token}"},
        json={"username": username, "password": "Test@1234", "role_codes": ["member"]},
    )
    assert resp.status_code == 200
    return username, resp.json()["data"]["id"]


async def _login(client, username):
    resp = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": "Test@1234"}
    )
    return resp.json()["data"]["access_token"]


async def _ws(client, token, code=None):
    resp = await client.post(
        "/api/v1/workspaces",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "边界工作空间", "code": code or await _unique("bws")},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


async def test_duplicate_workspace_code(client, super_token):
    h = {"Authorization": f"Bearer {super_token}"}
    code = await _unique("dupws")
    assert (await client.post("/api/v1/workspaces", headers=h, json={"name": "A", "code": code})).status_code == 200
    assert (await client.post("/api/v1/workspaces", headers=h, json={"name": "B", "code": code})).status_code == 400


async def test_workspace_pagination_bounds(client, super_token):
    h = {"Authorization": f"Bearer {super_token}"}
    assert (await client.get("/api/v1/workspaces?page=0", headers=h)).status_code == 400
    assert (await client.get("/api/v1/workspaces?page_size=101", headers=h)).status_code == 400
    assert (await client.get("/api/v1/workspaces?page=1&page_size=100", headers=h)).status_code == 200


async def test_workspace_member_duplicate_and_self(client, super_token):
    owner_name, _ = await _make_user(client, super_token)
    member_name, _ = await _make_user(client, super_token)
    owner_token = await _login(client, owner_name)
    ws = await _ws(client, owner_token)
    h = {"Authorization": f"Bearer {owner_token}"}
    first = await client.post(
        f"/api/v1/workspaces/{ws['id']}/members", headers=h, json={"username": member_name, "role": "viewer"}
    )
    second = await client.post(
        f"/api/v1/workspaces/{ws['id']}/members", headers=h, json={"username": member_name, "role": "editor"}
    )
    self_add = await client.post(
        f"/api/v1/workspaces/{ws['id']}/members", headers=h, json={"username": owner_name, "role": "viewer"}
    )
    owner_role = await client.post(
        f"/api/v1/workspaces/{ws['id']}/members", headers=h, json={"username": member_name, "role": "owner"}
    )
    assert first.status_code == 200
    assert second.status_code == 400
    assert self_add.status_code == 400
    assert owner_role.status_code == 400


async def test_workspace_transfer_non_member(client, super_token):
    owner_name, _ = await _make_user(client, super_token)
    stranger_id = (await _make_user(client, super_token))[1]
    owner_token = await _login(client, owner_name)
    ws = await _ws(client, owner_token)
    resp = await client.post(
        f"/api/v1/workspaces/{ws['id']}/transfer",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"target_user_id": stranger_id},
    )
    assert resp.status_code == 400


async def test_group_duplicate_code_and_member(client, super_token):
    owner_name, _ = await _make_user(client, super_token)
    member_name, _ = await _make_user(client, super_token)
    owner_token = await _login(client, owner_name)
    ws = await _ws(client, owner_token)
    h = {"Authorization": f"Bearer {owner_token}"}
    code = await _unique("dupgrp")
    first = await client.post(
        f"/api/v1/workspaces/{ws['id']}/groups", headers=h, json={"name": "组A", "code": code}
    )
    second = await client.post(
        f"/api/v1/workspaces/{ws['id']}/groups", headers=h, json={"name": "组B", "code": code}
    )
    assert first.status_code == 200
    assert second.status_code == 400
    group_id = first.json()["data"]["id"]
    m1 = await client.post(
        f"/api/v1/workspaces/{ws['id']}/groups/{group_id}/members", headers=h, json={"username": member_name}
    )
    m2 = await client.post(
        f"/api/v1/workspaces/{ws['id']}/groups/{group_id}/members", headers=h, json={"username": member_name}
    )
    assert m1.status_code == 200
    assert m2.status_code == 400


async def test_grant_to_nonexistent_group(client, super_token):
    h = {"Authorization": f"Bearer {super_token}"}
    kb = (
        await client.post(
            "/api/v1/kb", headers=h, json={"name": "边界知识库", "domain_code": "general"}
        )
    ).json()["data"]
    resp = await client.post(
        f"/api/v1/kb/{kb['id']}/groups",
        headers=h,
        json={"group_id": str(uuid.uuid4()), "role": "viewer"},
    )
    assert resp.status_code == 400


async def test_api_key_revoked_and_expired(client, super_token):
    h = {"Authorization": f"Bearer {super_token}"}
    live = (
        await client.post("/api/v1/api-keys", headers=h, json={"name": "有效"})
    ).json()["data"]
    expired = (
        await client.post(
            "/api/v1/api-keys",
            headers=h,
            json={
                "name": "过期",
                "expires_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
            },
        )
    ).json()["data"]
    assert (
        await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {expired['secret']}"})
    ).status_code == 401
    await client.delete(f"/api/v1/api-keys/{live['id']}", headers=h)
    assert (
        await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {live['secret']}"})
    ).status_code == 401


async def test_concurrent_api_key_auth(client, super_token):
    """并发用例：同一 API Key 并发认证全部成功。"""
    h = {"Authorization": f"Bearer {super_token}"}
    secret = (
        await client.post("/api/v1/api-keys", headers=h, json={"name": "并发"})
    ).json()["data"]["secret"]

    async def _me():
        return await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {secret}"})

    results = await asyncio.gather(*[_me() for _ in range(8)])
    assert all(r.status_code == 200 for r in results)


async def test_concurrent_workspace_member_add(client, super_token):
    """并发用例：同一用户并发加入工作空间，仅一个成功且无 500。"""
    owner_name, _ = await _make_user(client, super_token)
    member_name, _ = await _make_user(client, super_token)
    owner_token = await _login(client, owner_name)
    ws = await _ws(client, owner_token)

    async def _add():
        return await client.post(
            f"/api/v1/workspaces/{ws['id']}/members",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"username": member_name, "role": "viewer"},
        )

    results = await asyncio.gather(*[_add() for _ in range(4)])
    statuses = [r.status_code for r in results]
    assert statuses.count(200) == 1
    assert all(s in (200, 400) for s in statuses)


async def test_audit_export_empty_filter(client, super_token):
    h = {"Authorization": f"Bearer {super_token}"}
    resp = await client.get(
        "/api/v1/audit-logs/export?action=no.such.action", headers=h
    )
    assert resp.status_code == 200
    assert "created_at" in resp.text
