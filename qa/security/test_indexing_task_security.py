"""L5 安全渗透：M28 索引任务（权限矩阵/RLS/跨 KB 隔离）。"""

import uuid

from qa.fixtures.indexing_helpers import create_document_row, create_kb_via_api


async def _make_user(client, super_token, prefix):
    import uuid as _uuid

    username = f"{prefix}_{_uuid.uuid4().hex[:8]}"
    resp = await client.post(
        "/api/v1/users",
        headers={"Authorization": f"Bearer {super_token}"},
        json={
            "username": username,
            "password": "Test@1234",
            "role_codes": ["member"],
        },
    )
    assert resp.status_code == 200, resp.text
    return username


async def _login(client, username):
    resp = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": "Test@1234"}
    )
    assert resp.status_code == 200, resp.text
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


async def test_viewer_cannot_trigger_index(client, super_token, db_session):
    """L5M28-01：viewer 成员不可触发索引（editor+）。"""
    owner_name = await _make_user(client, super_token, "s4own")
    viewer_name = await _make_user(client, super_token, "s4view")
    owner_token = await _login(client, owner_name)
    kb = (
        await client.post(
            "/api/v1/kb",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"name": "S4安全-viewer", "domain_code": "general"},
        )
    ).json()["data"]
    viewer_token = await _invite_accept(client, owner_token, kb["id"], viewer_name, "viewer")
    doc_id = await create_document_row(
        db_session, uuid.UUID(kb["id"]), layout_path="kb-x/ocr/t/layout.json"
    )
    resp = await client.post(
        f"/api/v1/kb/{kb['id']}/documents/{doc_id}/index",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert resp.status_code == 403


async def test_outsider_cannot_trigger_index(client, super_token, db_session):
    """L5M28-02：非成员不可触发索引/查看任务。"""
    outsider_name = await _make_user(client, super_token, "s4out")
    outsider_token = await _login(client, outsider_name)
    kb = await create_kb_via_api(client, super_token, "S4安全-非成员")
    doc_id = await create_document_row(
        db_session, uuid.UUID(kb["id"]), layout_path="kb-x/ocr/t/layout.json"
    )
    resp = await client.post(
        f"/api/v1/kb/{kb['id']}/documents/{doc_id}/index",
        headers={"Authorization": f"Bearer {outsider_token}"},
    )
    assert resp.status_code == 403
    tasks = await client.get(
        f"/api/v1/kb/{kb['id']}/index/tasks",
        headers={"Authorization": f"Bearer {outsider_token}"},
    )
    assert tasks.status_code == 403


async def test_editor_can_trigger_index(client, super_token, db_session):
    """L5M28-03：editor 成员可触发索引。"""
    owner_name = await _make_user(client, super_token, "s4own2")
    editor_name = await _make_user(client, super_token, "s4edit")
    owner_token = await _login(client, owner_name)
    kb = (
        await client.post(
            "/api/v1/kb",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"name": "S4安全-editor", "domain_code": "general"},
        )
    ).json()["data"]
    editor_token = await _invite_accept(client, owner_token, kb["id"], editor_name, "editor")
    doc_id = await create_document_row(
        db_session, uuid.UUID(kb["id"]), layout_path="kb-x/ocr/t/layout.json"
    )
    resp = await client.post(
        f"/api/v1/kb/{kb['id']}/documents/{doc_id}/index",
        headers={"Authorization": f"Bearer {editor_token}"},
    )
    assert resp.status_code == 200, resp.text


async def test_cross_kb_index_isolation(client, super_token, db_session):
    """L5M28-04：A KB 成员无法看到/触发 B KB 的索引任务。"""
    owner_name = await _make_user(client, super_token, "s4iso")
    owner_token = await _login(client, owner_name)
    kb_a = (
        await client.post(
            "/api/v1/kb",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"name": "S4隔离A", "domain_code": "general"},
        )
    ).json()["data"]
    kb_b = await create_kb_via_api(client, super_token, "S4隔离B")
    # A 的 owner 不是 B 的成员（B 由 admin 创建）
    doc_b = await create_document_row(
        db_session, uuid.UUID(kb_b["id"]), layout_path="kb-x/ocr/b/layout.json"
    )
    # owner 尝试访问 B 的文档索引：KB 上下文服务层校验拒绝
    resp = await client.post(
        f"/api/v1/kb/{kb_b['id']}/documents/{doc_b}/index",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert resp.status_code == 403
