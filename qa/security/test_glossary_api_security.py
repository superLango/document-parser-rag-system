"""L5 安全：M33-S2 术语集 API 权限/隔离/并发。"""

import asyncio
import uuid

from qa.fixtures.indexing_helpers import create_kb_via_api


async def _mk(client, super_token, prefix):
    username = f"{prefix}_{uuid.uuid4().hex[:8]}"
    r = await client.post(
        "/api/v1/users",
        headers={"Authorization": f"Bearer {super_token}"},
        json={"username": username, "password": "Test@1234", "role_codes": ["member"]},
    )
    assert r.status_code == 200, r.text
    return username


async def _login(client, username):
    r = await client.post("/api/v1/auth/login", json={"username": username, "password": "Test@1234"})
    assert r.status_code == 200
    return r.json()["data"]["access_token"]


async def _invite(client, owner_token, kb_id, username, role):
    inv = (await client.post(
        f"/api/v1/kb/{kb_id}/invitations",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"username": username, "role": role},
    )).json()["data"]
    token = await _login(client, username)
    await client.post(
        f"/api/v1/kb/invitations/{inv['token']}/accept",
        headers={"Authorization": f"Bearer {token}"},
    )
    return token


async def test_viewer_readonly_editor_write(client, super_token):
    """L5M33-S2-01：viewer 只读，editor 可写。"""
    owner = await _mk(client, super_token, "glown")
    viewer = await _mk(client, super_token, "glview")
    editor = await _mk(client, super_token, "gledit")
    owner_token = await _login(client, owner)
    kb = (await client.post(
        "/api/v1/kb",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"name": "S8权限", "domain_code": "general"},
    )).json()["data"]
    viewer_token = await _invite(client, owner_token, kb["id"], viewer, "viewer")
    editor_token = await _invite(client, owner_token, kb["id"], editor, "editor")

    lr = await client.get(f"/api/v1/kb/{kb['id']}/term-bases", headers={"Authorization": f"Bearer {viewer_token}"})
    assert lr.status_code == 200
    cr = await client.post(
        f"/api/v1/kb/{kb['id']}/term-bases",
        headers={"Authorization": f"Bearer {viewer_token}"},
        json={"name": "越权", "source_type": "manual"},
    )
    assert cr.status_code == 403
    ok = await client.post(
        f"/api/v1/kb/{kb['id']}/term-bases",
        headers={"Authorization": f"Bearer {editor_token}"},
        json={"name": "编辑建", "source_type": "manual"},
    )
    assert ok.status_code == 200


async def test_outsider_403(client, super_token):
    """L5M33-S2-02：非成员全部拒绝。"""
    out = await _mk(client, super_token, "glout")
    out_token = await _login(client, out)
    kb = await create_kb_via_api(client, super_token, "S8非成员")
    r = await client.get(f"/api/v1/kb/{kb['id']}/term-bases", headers={"Authorization": f"Bearer {out_token}"})
    assert r.status_code == 403


async def test_cross_kb_isolation(client, super_token):
    """L5M33-S2-03：A 成员无法看到/操作 B 术语集。"""
    owner = await _mk(client, super_token, "gliso")
    owner_token = await _login(client, owner)
    kb_a = (await client.post(
        "/api/v1/kb",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"name": "S8隔离A", "domain_code": "general"},
    )).json()["data"]
    kb_b = await create_kb_via_api(client, super_token, "S8隔离B")
    created = await client.post(
        f"/api/v1/kb/{kb_b['id']}/term-bases",
        headers={"Authorization": f"Bearer {super_token}"},
        json={"name": "B的术语", "source_type": "manual"},
    )
    base_id = created.json()["data"]["id"]
    # A 的 owner 不是 B 成员：访问 B 术语集被服务层拒绝
    r = await client.get(
        f"/api/v1/kb/{kb_b['id']}/term-bases/{base_id}",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert r.status_code == 403


async def test_concurrent_create_same_name(client, super_token, db_session):
    """L5M33-S2-04（并发）：并发创建同名词条仅一个成功。"""
    from app.services.glossary import term_base_service

    kb = await create_kb_via_api(client, super_token, "S8并发建")
    kb_id = uuid.UUID(kb["id"])

    async def _create():
        return await term_base_service.create_term_base(
            db_session, kb_id, None, {"name": "并发名词", "source_type": "manual"}
        )

    results = await asyncio.gather(*[_create() for _ in range(4)], return_exceptions=True)
    ok = [r for r in results if not isinstance(r, Exception)]
    assert len(ok) == 1
