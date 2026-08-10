"""L2 集成链路：个人中心模块（M7）。"""

import uuid


async def _unique(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


async def test_update_profile_fields(client, member_user):
    token, username, password = member_user
    h = {"Authorization": f"Bearer {token}"}
    resp = await client.put(
        "/api/v1/auth/profile",
        headers=h,
        json={
            "full_name": "个人中心用户",
            "email": f"{username}@example.com",
            "phone": "13800000000",
            "department": "测试部",
            "avatar": "https://example.com/avatar.png",
        },
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["full_name"] == "个人中心用户"
    assert data["email"] == f"{username}@example.com"
    assert data["phone"] == "13800000000"
    assert data["department"] == "测试部"
    assert data["avatar"] == "https://example.com/avatar.png"


async def test_change_password_wrong_old_rejected(client, member_user):
    token, _, _ = member_user
    resp = await client.post(
        "/api/v1/auth/change-password",
        headers={"Authorization": f"Bearer {token}"},
        json={"old_password": "Wrong@123", "new_password": "NewPass@1234"},
    )
    assert resp.status_code == 401


async def test_change_password_weak_rejected(client, member_user):
    token, _, _ = member_user
    resp = await client.post(
        "/api/v1/auth/change-password",
        headers={"Authorization": f"Bearer {token}"},
        json={"old_password": "Test@1234", "new_password": "weak"},
    )
    assert resp.status_code == 400


async def test_change_password_reuse_rejected(client, member_user):
    token, _, _ = member_user
    resp = await client.post(
        "/api/v1/auth/change-password",
        headers={"Authorization": f"Bearer {token}"},
        json={"old_password": "Test@1234", "new_password": "Test@1234"},
    )
    assert resp.status_code == 400


async def test_change_password_success_and_relogin(client, member_user):
    token, username, _ = member_user
    resp = await client.post(
        "/api/v1/auth/change-password",
        headers={"Authorization": f"Bearer {token}"},
        json={"old_password": "Test@1234", "new_password": "NewPass@5678"},
    )
    assert resp.status_code == 200
    old = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": "Test@1234"}
    )
    assert old.status_code == 401
    new = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": "NewPass@5678"}
    )
    assert new.status_code == 200
