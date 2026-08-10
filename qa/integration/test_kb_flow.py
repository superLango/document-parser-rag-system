"""L2 集成链路：知识库资源 ACL、邀请审批、待审批账号（M10/M11/M12）。"""

import uuid


async def _unique(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


async def _make_user(client, super_token, role_codes=("member",)):
    username = await _unique("kbuser")
    resp = await client.post(
        "/api/v1/users",
        headers={"Authorization": f"Bearer {super_token}"},
        json={
            "username": username,
            "password": "Test@1234",
            "role_codes": list(role_codes),
        },
    )
    assert resp.status_code == 200, resp.text
    return username, resp.json()["data"]["id"]


async def _login(client, username):
    resp = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": "Test@1234"}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["access_token"]


async def _create_kb(client, token, name):
    resp = await client.post(
        "/api/v1/kb",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": name, "description": "集成", "domain_code": "general"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


async def test_kb_lifecycle_api(client, super_token):
    token = super_token
    kb = await _create_kb(client, token, "集成知识库A")
    assert kb["my_role"] == "owner"
    assert kb["member_count"] == 1

    listed = await client.get("/api/v1/kb?keyword=集成知识库A", headers={"Authorization": f"Bearer {token}"})
    assert listed.status_code == 200
    assert listed.json()["data"]["total"] == 1

    detail = await client.get(f"/api/v1/kb/{kb['id']}", headers={"Authorization": f"Bearer {token}"})
    assert detail.status_code == 200
    assert detail.json()["data"]["name"] == "集成知识库A"

    updated = await client.put(
        f"/api/v1/kb/{kb['id']}",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "集成知识库A2", "description": "改"},
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["name"] == "集成知识库A2"

    deleted = await client.delete(f"/api/v1/kb/{kb['id']}", headers={"Authorization": f"Bearer {token}"})
    assert deleted.status_code == 200
    detail2 = await client.get(f"/api/v1/kb/{kb['id']}", headers={"Authorization": f"Bearer {token}"})
    assert detail2.status_code == 400


async def test_member_visibility_isolation(client, super_token):
    owner_name, _ = await _make_user(client, super_token)
    other_name, _ = await _make_user(client, super_token)
    owner_token = await _login(client, owner_name)
    other_token = await _login(client, other_name)
    await _create_kb(client, owner_token, "隔离知识库")
    listed = await client.get("/api/v1/kb", headers={"Authorization": f"Bearer {other_token}"})
    assert listed.status_code == 200
    assert listed.json()["data"]["total"] == 0


async def test_invite_accept_role_remove_transfer_flow(client, super_token):
    owner_name, _ = await _make_user(client, super_token)
    invitee_name, invitee_id = await _make_user(client, super_token)
    owner_token = await _login(client, owner_name)
    invitee_token = await _login(client, invitee_name)
    kb = await _create_kb(client, owner_token, "协作知识库")

    invited = await client.post(
        f"/api/v1/kb/{kb['id']}/invitations",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"username": invitee_name, "role": "viewer"},
    )
    assert invited.status_code == 200, invited.text
    token_str = invited.json()["data"]["token"]

    mine = await client.get(
        "/api/v1/kb/invitations/mine", headers={"Authorization": f"Bearer {invitee_token}"}
    )
    assert mine.status_code == 200
    assert mine.json()["data"][0]["kb_name"] == "协作知识库"

    accepted = await client.post(
        f"/api/v1/kb/invitations/{token_str}/accept",
        headers={"Authorization": f"Bearer {invitee_token}"},
    )
    assert accepted.status_code == 200
    assert accepted.json()["data"]["status"] == "accepted"

    members = await client.get(
        f"/api/v1/kb/{kb['id']}/members", headers={"Authorization": f"Bearer {owner_token}"}
    )
    assert members.status_code == 200
    active = [m for m in members.json()["data"] if m["user_id"] == invitee_id]
    assert active[0]["status"] == "active"
    assert active[0]["role"] == "viewer"

    role = await client.put(
        f"/api/v1/kb/{kb['id']}/members/{invitee_id}",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"role": "editor"},
    )
    assert role.status_code == 200

    transferred = await client.post(
        f"/api/v1/kb/{kb['id']}/transfer",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"target_user_id": invitee_id},
    )
    assert transferred.status_code == 200
    detail = await client.get(
        f"/api/v1/kb/{kb['id']}", headers={"Authorization": f"Bearer {owner_token}"}
    )
    assert detail.json()["data"]["owner_id"] == invitee_id
    assert detail.json()["data"]["my_role"] == "admin"

    removed = await client.delete(
        f"/api/v1/kb/{kb['id']}/members/{invitee_id}",
        headers={"Authorization": f"Bearer {invitee_token}"},
    )
    # 新 owner 不能移除自己；由原 owner(admin) 移除
    assert removed.status_code == 400


async def test_viewer_cannot_manage(client, super_token):
    owner_name, _ = await _make_user(client, super_token)
    viewer_name, viewer_id = await _make_user(client, super_token)
    owner_token = await _login(client, owner_name)
    viewer_token = await _login(client, viewer_name)
    kb = await _create_kb(client, owner_token, "权限知识库")
    await client.post(
        f"/api/v1/kb/{kb['id']}/invitations",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"username": viewer_name, "role": "viewer"},
    )
    mine = (await client.get("/api/v1/kb/invitations/mine", headers={"Authorization": f"Bearer {viewer_token}"})).json()["data"]
    await client.post(
        f"/api/v1/kb/invitations/{mine[0]['token']}/accept",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    h = {"Authorization": f"Bearer {viewer_token}"}
    assert (
        await client.put(f"/api/v1/kb/{kb['id']}", headers=h, json={"name": "越权改名"})
    ).status_code == 403
    assert (
        await client.delete(f"/api/v1/kb/{kb['id']}", headers=h)
    ).status_code == 403
    assert (
        await client.post(
            f"/api/v1/kb/{kb['id']}/invitations",
            headers=h,
            json={"username": owner_name, "role": "viewer"},
        )
    ).status_code == 403
    assert (
        await client.put(
            f"/api/v1/kb/{kb['id']}/members/{viewer_id}",
            headers=h,
            json={"role": "admin"},
        )
    ).status_code == 403


async def test_revoke_invitation(client, super_token):
    owner_name, _ = await _make_user(client, super_token)
    invitee_name, _ = await _make_user(client, super_token)
    owner_token = await _login(client, owner_name)
    kb = await _create_kb(client, owner_token, "撤销知识库")
    invited = (
        await client.post(
            f"/api/v1/kb/{kb['id']}/invitations",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"username": invitee_name, "role": "viewer"},
        )
    ).json()["data"]
    revoked = await client.delete(
        f"/api/v1/kb/{kb['id']}/invitations/{invited['id']}",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert revoked.status_code == 200
    invitee_token = await _login(client, invitee_name)
    mine = await client.get(
        "/api/v1/kb/invitations/mine", headers={"Authorization": f"Bearer {invitee_token}"}
    )
    assert mine.json()["data"] == []


async def test_pending_registration_and_approval(client, super_token):
    """M11/M12：注册默认 pending，工作台/知识库被拦截，审批后恢复。"""
    from app.core.config import settings

    original = settings.REGISTRATION_DEFAULT_PENDING
    settings.REGISTRATION_DEFAULT_PENDING = True
    try:
        username = await _unique("pending")
        reg = await client.post(
            "/api/v1/auth/register",
            json={"username": username, "password": "Test@1234"},
        )
        assert reg.status_code == 200
        assert [r["code"] for r in reg.json()["data"]["roles"]] == ["pending"]

        token = await _login(client, username)
        me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me.status_code == 200
        assert me.json()["data"]["roles"][0]["code"] == "pending"
        assert (
            await client.get("/api/v1/dashboard/overview", headers={"Authorization": f"Bearer {token}"})
        ).status_code == 403
        assert (
            await client.get("/api/v1/kb", headers={"Authorization": f"Bearer {token}"})
        ).status_code == 403

        users = (
            await client.get(
                f"/api/v1/users?keyword={username}",
                headers={"Authorization": f"Bearer {super_token}"},
            )
        ).json()["data"]["items"]
        uid = users[0]["id"]
        approved = await client.post(
            f"/api/v1/users/{uid}/approve",
            headers={"Authorization": f"Bearer {super_token}"},
        )
        assert approved.status_code == 200
        assert approved.json()["data"]["roles"][0]["code"] == "member"
        overview = await client.get(
            "/api/v1/dashboard/overview", headers={"Authorization": f"Bearer {token}"}
        )
        assert overview.status_code == 200
        kbs = await client.get("/api/v1/kb", headers={"Authorization": f"Bearer {token}"})
        assert kbs.status_code == 200
    finally:
        settings.REGISTRATION_DEFAULT_PENDING = original


async def test_create_kb_with_members_api(client, super_token):
    """创建知识库时批量邀请初始成员，失败项收集不阻断创建。"""
    h = {"Authorization": f"Bearer {super_token}"}
    member_name, member_id = await _make_user(client, super_token)
    created = await client.post(
        "/api/v1/kb",
        headers=h,
        json={
            "name": "创建即邀请",
            "domain_code": "general",
            "members": [
                {"username": member_name, "role": "editor"},
                {"username": "ghost_user_zzz", "role": "viewer"},
            ],
        },
    )
    assert created.status_code == 200, created.text
    data = created.json()["data"]
    assert member_name in data["invited"]
    assert any(f["username"] == "ghost_user_zzz" for f in data["failed_invites"])

    members = (
        await client.get(f"/api/v1/kb/{data['id']}/members", headers=h)
    ).json()["data"]
    invited = [m for m in members if m["user_id"] == member_id]
    assert invited and invited[0]["status"] == "invited"

    member_token = await _login(client, member_name)
    mine = (
        await client.get("/api/v1/kb/invitations/mine", headers={"Authorization": f"Bearer {member_token}"})
    ).json()["data"]
    assert any(inv["kb_id"] == data["id"] for inv in mine)
    await client.post(
        f"/api/v1/kb/invitations/{mine[0]['token']}/accept",
        headers={"Authorization": f"Bearer {member_token}"},
    )
    detail = await client.get(f"/api/v1/kb/{data['id']}", headers=h)
    assert detail.json()["data"]["member_count"] == 2
