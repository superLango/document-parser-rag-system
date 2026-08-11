"""L5 安全渗透：Phase 1 文档模块（M17）。"""

import uuid


async def _unique(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


async def _kb(client, super_token, name="安全文档库"):
    resp = await client.post(
        "/api/v1/kb",
        headers={"Authorization": f"Bearer {super_token}"},
        json={"name": name, "domain_code": "general"},
    )
    return resp.json()["data"]


async def test_filename_traversal_sanitized(client, super_token, db_session):
    from sqlalchemy import text as sa_text

    from app.core.database import AsyncSessionLocal
    from app.models.document import Document

    kb = await _kb(client, super_token)
    h = {"Authorization": f"Bearer {super_token}"}
    resp = await client.post(
        f"/api/v1/kb/{kb['id']}/documents",
        headers=h,
        files={"file": ("../evil.pdf", b"%PDF evil", "application/pdf")},
    )
    assert resp.status_code == 200
    doc_id = resp.json()["data"]["document"]["id"]
    async with AsyncSessionLocal() as db:
        await db.execute(
            sa_text("SELECT set_config('app.is_superuser', 'true', true)")
        )
        doc = await db.get(Document, uuid.UUID(doc_id))
        assert doc is not None
        assert ".." not in doc.object_key
        assert doc.object_key.endswith("evil.pdf")


async def test_pending_user_cannot_access_documents(client, super_token):
    from app.core.config import settings

    kb = await _kb(client, super_token)
    original = settings.REGISTRATION_DEFAULT_PENDING
    settings.REGISTRATION_DEFAULT_PENDING = True
    try:
        username = await _unique("pendoc")
        await client.post(
            "/api/v1/auth/register", json={"username": username, "password": "Test@1234"}
        )
        login = await client.post(
            "/api/v1/auth/login", json={"username": username, "password": "Test@1234"}
        )
        token = login.json()["data"]["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        assert (
            await client.get(f"/api/v1/kb/{kb['id']}/documents", headers=h)
        ).status_code == 403
        assert (
            await client.post(
                f"/api/v1/kb/{kb['id']}/documents",
                headers=h,
                files={"file": ("p.pdf", b"%PDF", "application/pdf")},
            )
        ).status_code == 403
    finally:
        settings.REGISTRATION_DEFAULT_PENDING = original


async def test_upload_audit_recorded(client, super_token):
    import asyncio
    import time

    kb = await _kb(client, super_token)
    h = {"Authorization": f"Bearer {super_token}"}
    await client.post(
        f"/api/v1/kb/{kb['id']}/documents",
        headers=h,
        files={"file": ("audit.pdf", b"%PDF audit", "application/pdf")},
    )
    deadline = time.monotonic() + 4
    found = False
    while time.monotonic() < deadline:
        logs = (
            await client.get(
                "/api/v1/audit-logs?action=document.upload&page=1&page_size=50",
                headers=h,
            )
        ).json()["data"]["items"]
        if logs:
            found = True
            break
        await asyncio.sleep(0.2)
    assert found, "document.upload 应写入审计日志"


async def _make_user(client, super_token):
    username = await _unique("orig")
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
    return username, resp.json()["data"]["id"]


async def _login(client, username):
    resp = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": "Test@1234"}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["access_token"]


async def _invite_accept(client, owner_token, kb_id, username):
    inv = (
        await client.post(
            f"/api/v1/kb/{kb_id}/invitations",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"username": username, "role": "viewer"},
        )
    ).json()["data"]
    token = await _login(client, username)
    await client.post(
        f"/api/v1/kb/invitations/{inv['token']}/accept",
        headers={"Authorization": f"Bearer {token}"},
    )
    return token


async def test_original_endpoint_permissions(client, super_token):
    """L5：original 端点 viewer 可读、非成员 403、删除后 400。"""
    owner_name, _ = await _make_user(client, super_token)
    viewer_name, _ = await _make_user(client, super_token)
    outsider_name, _ = await _make_user(client, super_token)
    owner_token = await _login(client, owner_name)
    kb = (
        await client.post(
            "/api/v1/kb",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"name": "original权限", "domain_code": "general"},
        )
    ).json()["data"]
    viewer_token = await _invite_accept(client, owner_token, kb["id"], viewer_name)
    outsider_token = await _login(client, outsider_name)

    up = await client.post(
        f"/api/v1/kb/{kb['id']}/documents",
        headers={"Authorization": f"Bearer {owner_token}"},
        files={"file": ("orig.pdf", b"%PDF-1.4 original", "application/pdf")},
    )
    assert up.status_code == 200
    doc_id = up.json()["data"]["document"]["id"]

    out = await client.get(
        f"/api/v1/kb/{kb['id']}/documents/{doc_id}/original",
        headers={"Authorization": f"Bearer {outsider_token}"},
    )
    assert out.status_code == 403

    view = await client.get(
        f"/api/v1/kb/{kb['id']}/documents/{doc_id}/original",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert view.status_code == 200
    assert view.headers["content-type"].startswith("application/pdf")
    assert view.content.startswith(b"%PDF")

    await client.delete(
        f"/api/v1/kb/{kb['id']}/documents/{doc_id}",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    gone = await client.get(
        f"/api/v1/kb/{kb['id']}/documents/{doc_id}/original",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert gone.status_code == 400
