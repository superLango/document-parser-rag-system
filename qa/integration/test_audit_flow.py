"""L2 集成链路：审计日志模块（M6，含异步落库与脱敏）。"""

import asyncio
import time
import uuid


async def _unique(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


async def _wait_for(predicate, timeout: float = 4.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if await predicate():
            return True
        await asyncio.sleep(0.15)
    return False


async def test_audit_logs_record_actions(client, super_token):
    h = {"Authorization": f"Bearer {super_token}"}
    username = await _unique("audituser")
    await client.post(
        "/api/v1/users",
        headers=h,
        json={"username": username, "password": "Test@1234", "role_codes": ["member"]},
    )

    async def _found():
        resp = await client.get(
            "/api/v1/audit-logs?action=user.create&page=1&page_size=20",
            headers=h,
        )
        if resp.status_code != 200:
            return False
        items = resp.json()["data"]["items"]
        return any(item["username"] == "admin" and item["action"] == "user.create" for item in items)

    assert await _wait_for(_found), "审计日志应在 4s 内异步落库"


async def test_audit_filter_by_action_and_resource(client, super_token):
    h = {"Authorization": f"Bearer {super_token}"}
    resp = await client.get("/api/v1/audit-logs?action=user.create&page=1&page_size=20", headers=h)
    assert resp.status_code == 200
    for item in resp.json()["data"]["items"]:
        assert item["action"] == "user.create"

    actions = await client.get("/api/v1/audit-logs/actions", headers=h)
    assert actions.status_code == 200
    assert "user.create" in actions.json()["data"]


async def test_audit_stats(client, super_token):
    h = {"Authorization": f"Bearer {super_token}"}
    resp = await client.get("/api/v1/audit-logs/stats?days=7", headers=h)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total"] > 0
    assert data["by_action"].get("user.create", 0) >= 1


async def test_audit_denied_for_member(client, member_user):
    token, _, _ = member_user
    for path in ("/api/v1/audit-logs", "/api/v1/audit-logs/actions", "/api/v1/audit-logs/stats"):
        resp = await client.get(path, headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 403


async def test_audit_masks_sensitive_fields(client):
    """注册接口捕获 body，审计 details 中的 password 必须脱敏。"""
    username = await _unique("mask")
    await client.post(
        "/api/v1/auth/register",
        json={"username": username, "password": "SuperSecret@99", "full_name": "脱敏用户"},
    )

    async def _found():
        resp = await client.post(
            "/api/v1/auth/login", json={"username": "admin", "password": "admin123"}
        )
        token = resp.json()["data"]["access_token"]
        logs = (
            await client.get(
                "/api/v1/audit-logs?action=auth.register&page=1&page_size=20",
                headers={"Authorization": f"Bearer {token}"},
            )
        ).json()["data"]["items"]
        return any(item["details"] and "SuperSecret@99" not in str(item["details"]) for item in logs)

    assert await _wait_for(_found)
