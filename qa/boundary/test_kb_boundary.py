"""L4 边界异常：知识库邀请过期/并发/参数边界（M10/M11/M12）。"""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone


async def _unique(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


async def _make_user(client, super_token):
    username = await _unique("kbb")
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
    assert resp.status_code == 200
    return resp.json()["data"]["access_token"]


async def _kb(client, token, name):
    resp = await client.post(
        "/api/v1/kb",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": name, "domain_code": "general"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


async def _invite(client, token, kb_id, username, role="viewer", expires_at=None):
    body = {"username": username, "role": role}
    if expires_at:
        body["expires_at"] = expires_at.isoformat()
    return await client.post(
        f"/api/v1/kb/{kb_id}/invitations",
        headers={"Authorization": f"Bearer {token}"},
        json=body,
    )


async def test_expired_invitation_rejected(client, super_token):
    owner = await _make_user(client, super_token)
    invitee = await _make_user(client, super_token)
    owner_token = await _login(client, owner[0])
    kb = await _kb(client, owner_token, "过期邀请")
    resp = await _invite(
        client,
        owner_token,
        kb["id"],
        invitee[0],
        expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    assert resp.status_code == 200
    token_str = resp.json()["data"]["token"]
    invitee_token = await _login(client, invitee[0])
    accept = await client.post(
        f"/api/v1/kb/invitations/{token_str}/accept",
        headers={"Authorization": f"Bearer {invitee_token}"},
    )
    assert accept.status_code == 400
    assert "过期" in accept.json()["message"]


async def test_wrong_and_foreign_token_rejected(client, super_token):
    owner = await _make_user(client, super_token)
    invitee = await _make_user(client, super_token)
    stranger = await _make_user(client, super_token)
    owner_token = await _login(client, owner[0])
    kb = await _kb(client, owner_token, "令牌校验")
    resp = await _invite(client, owner_token, kb["id"], invitee[0])
    token_str = resp.json()["data"]["token"]
    stranger_token = await _login(client, stranger[0])
    foreign = await client.post(
        f"/api/v1/kb/invitations/{token_str}/accept",
        headers={"Authorization": f"Bearer {stranger_token}"},
    )
    assert foreign.status_code == 403
    bad = await client.post(
        "/api/v1/kb/invitations/not-a-real-token/accept",
        headers={"Authorization": f"Bearer {stranger_token}"},
    )
    assert bad.status_code == 400


async def test_duplicate_invite_rejected(client, super_token):
    owner = await _make_user(client, super_token)
    invitee = await _make_user(client, super_token)
    owner_token = await _login(client, owner[0])
    kb = await _kb(client, owner_token, "重复邀请")
    first = await _invite(client, owner_token, kb["id"], invitee[0])
    second = await _invite(client, owner_token, kb["id"], invitee[0], role="editor")
    assert first.status_code == 200
    assert second.status_code == 400


async def test_transfer_to_non_member_rejected(client, super_token):
    owner = await _make_user(client, super_token)
    stranger = await _make_user(client, super_token)
    owner_token = await _login(client, owner[0])
    kb = await _kb(client, owner_token, "转移校验")
    resp = await client.post(
        f"/api/v1/kb/{kb['id']}/transfer",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"target_user_id": stranger[1]},
    )
    assert resp.status_code == 400


async def test_concurrent_invite_same_user(client, super_token):
    """并发用例：同一用户并发邀请，仅一个成功且无 500。"""
    owner = await _make_user(client, super_token)
    invitee = await _make_user(client, super_token)
    owner_token = await _login(client, owner[0])
    kb = await _kb(client, owner_token, "并发邀请")

    async def _do():
        return await _invite(client, owner_token, kb["id"], invitee[0], role="viewer")

    results = await asyncio.gather(*[_do() for _ in range(4)])
    statuses = [r.status_code for r in results]
    assert statuses.count(200) == 1
    assert all(s in (200, 400) for s in statuses)


async def test_concurrent_accept_same_token(client, super_token):
    """并发用例：同一邀请并发接受，仅一个成功且无 500。"""
    owner = await _make_user(client, super_token)
    invitee = await _make_user(client, super_token)
    owner_token = await _login(client, owner[0])
    kb = await _kb(client, owner_token, "并发接受")
    resp = await _invite(client, owner_token, kb["id"], invitee[0])
    token_str = resp.json()["data"]["token"]
    invitee_token = await _login(client, invitee[0])

    async def _accept():
        return await client.post(
            f"/api/v1/kb/invitations/{token_str}/accept",
            headers={"Authorization": f"Bearer {invitee_token}"},
        )

    results = await asyncio.gather(*[_accept() for _ in range(4)])
    statuses = [r.status_code for r in results]
    assert statuses.count(200) == 1
    assert all(s in (200, 400) for s in statuses)


async def test_kb_pagination_bounds(client, super_token):
    h = {"Authorization": f"Bearer {super_token}"}
    assert (await client.get("/api/v1/kb?page=0", headers=h)).status_code == 400
    assert (await client.get("/api/v1/kb?page_size=101", headers=h)).status_code == 400
    assert (await client.get("/api/v1/kb?page=1&page_size=100", headers=h)).status_code == 200


async def test_create_kb_members_duplicate_and_self(client, super_token):
    """创建时初始成员含重复/自己：KB 仍创建成功，失败项被收集，无 500。"""
    h = {"Authorization": f"Bearer {super_token}"}
    me = (await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {super_token}"})).json()["data"]
    other = (await _make_user(client, super_token))[0]
    resp = await client.post(
        "/api/v1/kb",
        headers=h,
        json={
            "name": "成员异常库",
            "domain_code": "general",
            "members": [
                {"username": other, "role": "viewer"},
                {"username": other, "role": "editor"},
                {"username": me["username"], "role": "viewer"},
            ],
        },
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert other in data["invited"]  # 去重后仅邀请一次
    assert len(data["failed_invites"]) == 1
    assert data["failed_invites"][0]["username"] == me["username"]


async def test_create_kb_members_invalid_role(client, super_token):
    resp = await client.post(
        "/api/v1/kb",
        headers={"Authorization": f"Bearer {super_token}"},
        json={
            "name": "非法角色库",
            "domain_code": "general",
            "members": [{"username": "admin", "role": "owner"}],
        },
    )
    assert resp.status_code == 400
