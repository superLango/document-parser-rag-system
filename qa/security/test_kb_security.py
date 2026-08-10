"""L5 安全渗透：知识库 ACL 越权、注入、令牌强度、审计留痕。"""

import uuid


async def _unique(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


async def _make_user(client, super_token):
    username = await _unique("kbs")
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


async def _kb(client, token, name):
    resp = await client.post(
        "/api/v1/kb",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": name, "domain_code": "general"},
    )
    return resp.json()["data"]


async def test_non_member_cannot_access(client, super_token):
    owner = await _make_user(client, super_token)
    stranger = await _make_user(client, super_token)
    owner_token = await _login(client, owner[0])
    stranger_token = await _login(client, stranger[0])
    kb = await _kb(client, owner_token, "越权访问")
    h = {"Authorization": f"Bearer {stranger_token}"}
    assert (await client.get(f"/api/v1/kb/{kb['id']}", headers=h)).status_code == 403
    assert (await client.get(f"/api/v1/kb/{kb['id']}/members", headers=h)).status_code == 403
    assert (
        await client.put(f"/api/v1/kb/{kb['id']}", headers=h, json={"name": "x"})
    ).status_code == 403
    assert (
        await client.post(
            f"/api/v1/kb/{kb['id']}/transfer",
            headers=h,
            json={"target_user_id": owner[1]},
        )
    ).status_code == 403


async def test_viewer_cannot_escalate_role(client, super_token):
    owner = await _make_user(client, super_token)
    viewer = await _make_user(client, super_token)
    owner_token = await _login(client, owner[0])
    viewer_token = await _login(client, viewer[0])
    kb = await _kb(client, owner_token, "提权尝试")
    inv = (
        await client.post(
            f"/api/v1/kb/{kb['id']}/invitations",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"username": viewer[0], "role": "viewer"},
        )
    ).json()["data"]
    await client.post(
        f"/api/v1/kb/invitations/{inv['token']}/accept",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    resp = await client.put(
        f"/api/v1/kb/{kb['id']}/members/{viewer[1]}",
        headers={"Authorization": f"Bearer {viewer_token}"},
        json={"role": "owner"},
    )
    assert resp.status_code == 403
    # 管理员也不能直接把自己改成 owner（只能转移）
    resp2 = await client.put(
        f"/api/v1/kb/{kb['id']}/members/{viewer[1]}",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"role": "owner"},
    )
    assert resp2.status_code == 400


async def test_invitation_token_strength_and_uniqueness(client, super_token):
    owner = await _make_user(client, super_token)
    invitee1 = await _make_user(client, super_token)
    invitee2 = await _make_user(client, super_token)
    owner_token = await _login(client, owner[0])
    kb = await _kb(client, owner_token, "令牌强度")
    t1 = (
        await client.post(
            f"/api/v1/kb/{kb['id']}/invitations",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"username": invitee1[0], "role": "viewer"},
        )
    ).json()["data"]["token"]
    t2 = (
        await client.post(
            f"/api/v1/kb/{kb['id']}/invitations",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"username": invitee2[0], "role": "viewer"},
        )
    ).json()["data"]["token"]
    assert len(t1) >= 43 and len(t2) >= 43
    assert t1 != t2


async def test_kb_search_injection_safe(client, super_token):
    resp = await client.get(
        "/api/v1/kb?keyword=' OR 1=1 --",
        headers={"Authorization": f"Bearer {super_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["total"] == 0


async def test_kb_name_xss_stored_contract(client, super_token):
    payload = "<script>alert('kb-xss')</script>"
    resp = await client.post(
        "/api/v1/kb",
        headers={"Authorization": f"Bearer {super_token}"},
        json={"name": payload, "domain_code": "general"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["name"] == payload


async def test_pending_user_restricted_from_kb_and_dashboard(client, super_token):
    from app.core.config import settings

    original = settings.REGISTRATION_DEFAULT_PENDING
    settings.REGISTRATION_DEFAULT_PENDING = True
    try:
        username = await _unique("pendingsec")
        reg = await client.post(
            "/api/v1/auth/register",
            json={"username": username, "password": "Test@1234"},
        )
        assert reg.status_code == 200
        token = await _login(client, username)
        h = {"Authorization": f"Bearer {token}"}
        assert (await client.get("/api/v1/kb", headers=h)).status_code == 403
        assert (await client.get("/api/v1/dashboard/overview", headers=h)).status_code == 403
        assert (await client.get("/api/v1/auth/me", headers=h)).status_code == 200
    finally:
        settings.REGISTRATION_DEFAULT_PENDING = original


async def test_kb_actions_audited(client, super_token):
    import time

    owner = await _make_user(client, super_token)
    invitee = await _make_user(client, super_token)
    owner_token = await _login(client, owner[0])
    kb = await _kb(client, owner_token, "审计知识库")
    await client.post(
        f"/api/v1/kb/{kb['id']}/invitations",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"username": invitee[0], "role": "viewer"},
    )
    deadline = time.monotonic() + 4
    found = False
    while time.monotonic() < deadline:
        logs = (
            await client.get(
                "/api/v1/audit-logs?page=1&page_size=50",
                headers={"Authorization": f"Bearer {super_token}"},
            )
        ).json()["data"]["items"]
        actions = {item["action"] for item in logs}
        if {"kb.create", "kb.invite"}.issubset(actions):
            found = True
            break
        import asyncio

        await asyncio.sleep(0.2)
    assert found, "kb.create / kb.invite 应出现在审计日志"


async def test_pending_user_search_denied(client, super_token):
    from app.core.config import settings

    original = settings.REGISTRATION_DEFAULT_PENDING
    settings.REGISTRATION_DEFAULT_PENDING = True
    try:
        username = await _unique("pendingsearch")
        await client.post(
            "/api/v1/auth/register", json={"username": username, "password": "Test@1234"}
        )
        token = await _login(client, username)
        resp = await client.get(
            "/api/v1/users/search?keyword=admin",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403
    finally:
        settings.REGISTRATION_DEFAULT_PENDING = original


async def test_non_member_external_denied(client, super_token):
    owner_name, _ = await _make_user(client, super_token)
    stranger_name, _ = await _make_user(client, super_token)
    owner_token = await _login(client, owner_name)
    stranger_token = await _login(client, stranger_name)
    kb = await _kb(client, owner_token, "外部联动安全")
    h = {"Authorization": f"Bearer {stranger_token}"}
    assert (await client.get(f"/api/v1/kb/{kb['id']}/external", headers=h)).status_code == 403
    assert (
        await client.put(f"/api/v1/kb/{kb['id']}/external", headers=h, json={"enabled": True})
    ).status_code == 403
