"""L5 安全：M34 全局配置（viewer 只读 / 非成员 403 / 跨 KB）。"""

import uuid

from qa.fixtures.indexing_helpers import create_kb_via_api

H = "Authorization"


async def _mk_user(client, super_token, prefix):
    username = f"{prefix}_{uuid.uuid4().hex[:8]}"
    r = await client.post("/api/v1/users", headers={H: f"Bearer {super_token}"},
                          json={"username": username, "password": "Test@1234", "role_codes": ["member"]})
    assert r.status_code == 200, r.text
    return username


async def _login(client, username):
    r = await client.post("/api/v1/auth/login", json={"username": username, "password": "Test@1234"})
    assert r.status_code == 200
    return r.json()["data"]["access_token"]


async def _invite(client, owner_token, kb_id, username, role):
    inv = (await client.post(
        f"/api/v1/kb/{kb_id}/invitations", headers={H: f"Bearer {owner_token}"},
        json={"username": username, "role": role},
    )).json()["data"]
    token = await _login(client, username)
    await client.post(f"/api/v1/kb/invitations/{inv['token']}/accept", headers={H: f"Bearer {token}"})
    return token


async def test_viewer_readonly_editor_write(client, super_token):
    """L5G-01：viewer 可读不可写，editor 可写。"""
    owner = await _mk_user(client, super_token, "g10own")
    viewer = await _mk_user(client, super_token, "g10view")
    editor = await _mk_user(client, super_token, "g10edit")
    owner_token = await _login(client, owner)
    kb = (await client.post("/api/v1/kb", headers={H: f"Bearer {owner_token}"},
                            json={"name": "G10权限", "domain_code": "general"})).json()["data"]
    viewer_token = await _invite(client, owner_token, kb["id"], viewer, "viewer")
    editor_token = await _invite(client, owner_token, kb["id"], editor, "editor")

    r = await client.get(f"/api/v1/kb/{kb['id']}/extraction-config/global", headers={H: f"Bearer {viewer_token}"})
    assert r.status_code == 200

    r = await client.put(f"/api/v1/kb/{kb['id']}/extraction-config/global", headers={H: f"Bearer {viewer_token}"},
                         json={"enabled": True, "content": {}})
    assert r.status_code in (400, 403)

    r = await client.put(f"/api/v1/kb/{kb['id']}/extraction-config/global", headers={H: f"Bearer {editor_token}"},
                         json={"enabled": True, "content": {"retrieval": {"top_k": 25}}})
    assert r.status_code == 200, r.text


async def test_outsider_403(client, super_token):
    """L5G-02：非成员全部拒绝。"""
    out = await _mk_user(client, super_token, "g10out")
    out_token = await _login(client, out)
    kb = await create_kb_via_api(client, super_token, "G10非成员")
    r = await client.get(f"/api/v1/kb/{kb['id']}/extraction-config/global", headers={H: f"Bearer {out_token}"})
    assert r.status_code == 403
