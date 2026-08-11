"""L5 安全渗透：M30 检索（权限/RLS/跨 KB/并发）。"""

import asyncio
import json
import time
import uuid

from app.services.indexing.retrieval import retrieval_service
from qa.fixtures.indexing_helpers import create_document_row, create_kb_via_api


async def _make_user(client, super_token, prefix):
    username = f"{prefix}_{uuid.uuid4().hex[:8]}"
    resp = await client.post(
        "/api/v1/users",
        headers={"Authorization": f"Bearer {super_token}"},
        json={"username": username, "password": "Test@1234", "role_codes": ["member"]},
    )
    assert resp.status_code == 200, resp.text
    return username


async def _login(client, username):
    resp = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": "Test@1234"}
    )
    return resp.json()["data"]["access_token"]


async def _invite_accept(client, owner_token, kb_id, username, role="viewer"):
    inv = (
        await client.post(
            f"/api/v1/kb/{kb_id}/invitations",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"username": username, "role": role},
        )
    ).json()["data"]
    token = await _login(client, username)
    await client.post(
        f"/api/v1/kb/invitations/{inv['token']}/accept",
        headers={"Authorization": f"Bearer {token}"},
    )
    return token


async def _seed_simple(client, super_token, db, kb_id, name, content):
    from app.services import storage

    layout = {
        "schema_version": "1.2", "rebuild": {"enabled": True,
            "document_tree": {"type": "root", "children": [
                {"type": "title", "content": "1 秘密章节", "level": 1, "page": 0, "order": 0,
                 "children": [{"type": "text", "content": content, "level": 0,
                               "page": 0, "order": 1, "children": []}]}
            ]}},
    }
    kb_uuid = kb_id if isinstance(kb_id, uuid.UUID) else uuid.UUID(kb_id)
    key = f"kb-{kb_uuid.hex}/ocr/sec/{name}/layout.json"
    storage.put_object(key, json.dumps(layout).encode("utf-8"), "application/json")
    doc_id = await create_document_row(db, kb_uuid, filename=f"{name}.pdf", layout_path=key)
    resp = await client.post(
        f"/api/v1/kb/{kb_id}/documents/{doc_id}/index",
        headers={"Authorization": f"Bearer {super_token}"},
    )
    assert resp.status_code == 200, resp.text
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        r = await client.get(
            f"/api/v1/kb/{kb_id}/documents/{doc_id}",
            headers={"Authorization": f"Bearer {super_token}"},
        )
        if r.json()["data"]["index_status"] == "indexed":
            return doc_id
        await asyncio.sleep(0.4)
    raise AssertionError("索引等待超时")


async def test_viewer_can_search(client, super_token, db_session):
    """L5M30-01：viewer 成员可检索。"""
    owner_name = await _make_user(client, super_token, "s6own")
    viewer_name = await _make_user(client, super_token, "s6view")
    owner_token = await _login(client, owner_name)
    kb = (
        await client.post(
            "/api/v1/kb",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"name": "S6安全-viewer", "domain_code": "general"},
        )
    ).json()["data"]
    viewer_token = await _invite_accept(client, owner_token, kb["id"], viewer_name, "viewer")
    await _seed_simple(client, owner_token, db_session, kb["id"], "v", "机密检索内容 不锈钢")
    resp = await client.post(
        f"/api/v1/kb/{kb['id']}/search",
        headers={"Authorization": f"Bearer {viewer_token}"},
        json={"query": "机密检索内容"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["total"] >= 1


async def test_outsider_cannot_search(client, super_token, db_session):
    """L5M30-02：非成员不可检索。"""
    outsider = await _make_user(client, super_token, "s6out")
    outsider_token = await _login(client, outsider)
    kb = await create_kb_via_api(client, super_token, "S6安全-非成员")
    resp = await client.post(
        f"/api/v1/kb/{kb['id']}/search",
        headers={"Authorization": f"Bearer {outsider_token}"},
        json={"query": "任何"},
    )
    assert resp.status_code == 403


async def test_cross_kb_search_isolation(client, super_token, db_session):
    """L5M30-03：A KB 检索结果不含 B KB 内容。"""
    owner_name = await _make_user(client, super_token, "s6iso")
    owner_token = await _login(client, owner_name)
    kb_a = (
        await client.post(
            "/api/v1/kb",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"name": "S6隔离A", "domain_code": "general"},
        )
    ).json()["data"]
    kb_b = await create_kb_via_api(client, super_token, "S6隔离B")
    await _seed_simple(client, super_token, db_session, kb_b["id"], "b", "仅存在于B库的独特编码 XQZ-99")
    resp = await client.post(
        f"/api/v1/kb/{kb_a['id']}/search",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"query": "XQZ-99"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["total"] == 0


async def test_concurrent_searches_consistent(client, super_token, db_session):
    """L5M30-04（并发）：并发检索不崩溃且结果一致。"""
    kb = await create_kb_via_api(client, super_token, "S6并发检索")
    kb_id = uuid.UUID(kb["id"])
    await _seed_simple(client, super_token, db_session, kb_id, "c", "并发检索稳定性测试内容")
    results = await asyncio.gather(*[
        retrieval_service.search(db_session, kb_id, "并发检索稳定性") for _ in range(6)
    ])
    assert all(r == results[0] for r in results)
    assert results[0]
