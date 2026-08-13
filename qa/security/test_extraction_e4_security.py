"""L5 安全：E4 抽取端点权限与隔离。"""

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


async def test_viewer_readonly(client, super_token):
    """L5E4-01：viewer 可读列表，启动/删除被拒。"""
    owner = await _mk_user(client, super_token, "e4own")
    viewer = await _mk_user(client, super_token, "e4view")
    owner_token = await _login(client, owner)
    kb = (await client.post("/api/v1/kb", headers={H: f"Bearer {owner_token}"},
                            json={"name": "E4权限", "domain_code": "general"})).json()["data"]
    viewer_token = await _invite(client, owner_token, kb["id"], viewer, "viewer")
    r = await client.get(f"/api/v1/kb/{kb['id']}/extraction/documents", headers={H: f"Bearer {viewer_token}"})
    assert r.status_code == 200
    r = await client.post(f"/api/v1/kb/{kb['id']}/extraction/{uuid.uuid4()}", headers={H: f"Bearer {viewer_token}"})
    assert r.status_code in (400, 403)
    r = await client.delete(f"/api/v1/kb/{kb['id']}/extraction/{uuid.uuid4()}/result", headers={H: f"Bearer {viewer_token}"})
    assert r.status_code in (400, 403)


async def test_outsider_403(client, super_token):
    """L5E4-02：非成员拒绝。"""
    out = await _mk_user(client, super_token, "e4out")
    out_token = await _login(client, out)
    kb = await create_kb_via_api(client, super_token, "E4非成员")
    r = await client.get(f"/api/v1/kb/{kb['id']}/extraction/documents", headers={H: f"Bearer {out_token}"})
    assert r.status_code == 403


async def test_cross_kb_result_not_visible(client, super_token):
    """L5E4-03：A 文档结果在 B KB 查询返回 None（服务级 kb 过滤）。"""
    await create_kb_via_api(client, super_token, "E4隔离A")
    b = await create_kb_via_api(client, super_token, "E4隔离B")
    doc_id = uuid.uuid4()
    r = await client.get(f"/api/v1/kb/{b['id']}/extraction/{doc_id}/result", headers={H: f"Bearer {super_token}"})
    assert r.status_code == 200 and r.json()["data"] is None
