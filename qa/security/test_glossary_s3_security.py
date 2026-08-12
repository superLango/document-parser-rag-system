"""L5 安全：M33-S3 术语 API 权限/隔离/并发。"""

import asyncio
import uuid

from sqlalchemy import text as sa_text

from qa.fixtures.indexing_helpers import create_kb_via_api


async def _mk(client, super_token, prefix):
    username = f"{prefix}_{uuid.uuid4().hex[:8]}"
    r = await client.post(
        "/api/v1/users",
        headers={"Authorization": f"Bearer {super_token}"},
        json={"username": username, "password": "Test@1234", "role_codes": ["member"]},
    )
    return username


async def _login(client, username):
    r = await client.post("/api/v1/auth/login", json={"username": username, "password": "Test@1234"})
    return r.json()["data"]["access_token"]


async def _invite(client, owner_token, kb_id, username, role):
    inv = (await client.post(
        f"/api/v1/kb/{kb_id}/invitations",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"username": username, "role": role},
    )).json()["data"]
    token = await _login(client, username)
    await client.post(f"/api/v1/kb/invitations/{inv['token']}/accept", headers={"Authorization": f"Bearer {token}"})
    return token


async def test_viewer_readonly_editor_write(client, super_token):
    """L5M33-S3-01：viewer 只读、editor 可写术语。"""
    owner = await _mk(client, super_token, "s3own")
    viewer = await _mk(client, super_token, "s3view")
    editor = await _mk(client, super_token, "s3edit")
    owner_token = await _login(client, owner)
    kb = (await client.post(
        "/api/v1/kb",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"name": "S8术语权限", "domain_code": "general"},
    )).json()["data"]
    viewer_token = await _invite(client, owner_token, kb["id"], viewer, "viewer")
    editor_token = await _invite(client, owner_token, kb["id"], editor, "editor")

    base = (await client.post(
        f"/api/v1/kb/{kb['id']}/term-bases",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"name": "权限集", "source_type": "manual"},
    )).json()["data"]["id"]

    lr = await client.get(f"/api/v1/kb/{kb['id']}/terms", headers={"Authorization": f"Bearer {viewer_token}"})
    assert lr.status_code == 200
    cr = await client.post(
        f"/api/v1/kb/{kb['id']}/terms",
        headers={"Authorization": f"Bearer {viewer_token}"},
        json={"term": "越权", "term_base_id": base},
    )
    assert cr.status_code == 403
    ok = await client.post(
        f"/api/v1/kb/{kb['id']}/terms",
        headers={"Authorization": f"Bearer {editor_token}"},
        json={"term": "编辑词", "term_base_id": base},
    )
    assert ok.status_code == 200


async def test_outsider_403(client, super_token):
    """L5M33-S3-02：非成员不可访问术语。"""
    out = await _mk(client, super_token, "s3out")
    out_token = await _login(client, out)
    kb = await create_kb_via_api(client, super_token, "S8术语非成员")
    r = await client.get(f"/api/v1/kb/{kb['id']}/terms", headers={"Authorization": f"Bearer {out_token}"})
    assert r.status_code == 403


async def test_cross_kb_term_isolation(client, super_token):
    """L5M33-S3-03：A 成员不可访问 B 术语。"""
    owner = await _mk(client, super_token, "s3iso")
    owner_token = await _login(client, owner)
    kb_a = (await client.post(
        "/api/v1/kb",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"name": "S8术语隔离A", "domain_code": "general"},
    )).json()["data"]
    kb_b = await create_kb_via_api(client, super_token, "S8术语隔离B")
    base_b = (await client.post(
        f"/api/v1/kb/{kb_b['id']}/term-bases",
        headers={"Authorization": f"Bearer {super_token}"},
        json={"name": "B集", "source_type": "manual"},
    )).json()["data"]["id"]
    term_b = (await client.post(
        f"/api/v1/kb/{kb_b['id']}/terms",
        headers={"Authorization": f"Bearer {super_token}"},
        json={"term": "B词", "term_base_id": base_b},
    )).json()["data"]["id"]
    r = await client.get(
        f"/api/v1/kb/{kb_b['id']}/terms/{term_b}",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert r.status_code == 403


async def test_concurrent_batch_import(client, super_token, db_session):
    """L5M33-S3-04（并发）：并发批量导入同一批词条最终无重复。"""
    kb = await create_kb_via_api(client, super_token, "S8并发批量")
    kb_id = uuid.UUID(kb["id"])
    base = (await client.post(
        f"/api/v1/kb/{kb['id']}/term-bases",
        headers={"Authorization": f"Bearer {super_token}"},
        json={"name": "并发集", "source_type": "manual"},
    )).json()["data"]["id"]
    items = [{"term": f"C{i}", "term_base_id": base} for i in range(5)]

    from app.core.database import AsyncSessionLocal
    from app.services.glossary import term_service

    async def _import():
        async with AsyncSessionLocal() as db:
            await db.execute(sa_text("SELECT set_config('app.is_superuser', 'true', true)"))
            return await term_service.batch_import_terms(db, kb_id, uuid.UUID(base), None, items)

    results = await asyncio.gather(*[_import() for _ in range(3)], return_exceptions=True)
    ok = [r for r in results if not isinstance(r, Exception)]
    assert ok, f"全部失败: {[str(e) for e in results if isinstance(e, Exception)]}"
    total = (await client.get(f"/api/v1/kb/{kb['id']}/terms", headers={"Authorization": f"Bearer {super_token}"})).json()["data"]["total"]
    assert total == 5
