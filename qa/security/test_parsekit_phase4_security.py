"""L5 安全渗透：Phase 4 页面预览与产物生命周期（M20）。"""

import asyncio
import time
import uuid

from app.core.config import settings


async def _unique(prefix):
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


async def _login(client, username, password="Test@1234"):
    resp = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["access_token"]


async def _create_kb(client, token, name):
    resp = await client.post(
        "/api/v1/kb",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": name, "domain_code": "general"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


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


async def _upload_wait(client, token, kb_id, name="sec.pdf"):
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page(width=400, height=600)
    page.insert_text((72, 100), "security p4", fontsize=12)
    data = doc.tobytes()
    doc.close()
    resp = await client.post(
        f"/api/v1/kb/{kb_id}/documents",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": (name, data, "application/pdf")},
    )
    assert resp.status_code == 200, resp.text
    doc_id = resp.json()["data"]["document"]["id"]
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        detail = (
            await client.get(
                f"/api/v1/kb/{kb_id}/documents/{doc_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
        ).json()["data"]
        if detail["status"] in ("completed", "failed"):
            return detail
        await asyncio.sleep(0.2)
    raise AssertionError("未完成")


# ---------- L5M20-01 外部人页面预览 403 ----------
async def test_outsider_page_preview_forbidden(client, super_token):
    owner_name = await _unique("owner")
    outsider_name = await _unique("outsider")
    for name in (owner_name, outsider_name):
        resp = await client.post(
            "/api/v1/users",
            headers={"Authorization": f"Bearer {super_token}"},
            json={"username": name, "password": "Test@1234", "role_codes": ["member"]},
        )
        assert resp.status_code == 200, resp.text
    owner_token = await _login(client, owner_name)
    kb = await _create_kb(client, owner_token, "P4-安全外部")
    detail = await _upload_wait(client, owner_token, kb["id"])
    outsider_token = await _login(client, outsider_name)
    resp = await client.get(
        f"/api/v1/kb/{kb['id']}/documents/{detail['id']}/pages/1",
        headers={"Authorization": f"Bearer {outsider_token}"},
    )
    assert resp.status_code == 403


# ---------- L5M20-02 跨 KB 页面预览 403 ----------
async def test_cross_kb_page_preview_forbidden(client, super_token):
    owner_name = await _unique("owner")
    member_name = await _unique("member")
    for name in (owner_name, member_name):
        resp = await client.post(
            "/api/v1/users",
            headers={"Authorization": f"Bearer {super_token}"},
            json={"username": name, "password": "Test@1234", "role_codes": ["member"]},
        )
        assert resp.status_code == 200, resp.text
    owner_token = await _login(client, owner_name)
    kb_a = await _create_kb(client, owner_token, "P4-KB-A")
    kb_b = await _create_kb(client, owner_token, "P4-KB-B")
    await _invite_accept(client, owner_token, kb_b["id"], member_name)
    member_token = await _login(client, member_name)
    detail = await _upload_wait(client, owner_token, kb_a["id"])
    resp = await client.get(
        f"/api/v1/kb/{kb_a['id']}/documents/{detail['id']}/pages/1",
        headers={"Authorization": f"Bearer {member_token}"},
    )
    assert resp.status_code == 403


# ---------- L5M20-03 删除后页面预览 400 且文件已清理 ----------
async def test_delete_removes_pages(client, super_token):
    from pathlib import Path

    kb = await _create_kb(client, super_token, "P4-删除清理")
    detail = await _upload_wait(client, super_token, kb["id"])
    h = {"Authorization": f"Bearer {super_token}"}
    assert (
        await client.get(
            f"/api/v1/kb/{kb['id']}/documents/{detail['id']}/pages/1", headers=h
        )
    ).status_code == 200
    await client.delete(
        f"/api/v1/kb/{kb['id']}/documents/{detail['id']}", headers=h
    )
    resp = await client.get(
        f"/api/v1/kb/{kb['id']}/documents/{detail['id']}/pages/1", headers=h
    )
    assert resp.status_code == 400
    # 页面目录随删除清理
    base = detail["markdown_path"].rsplit("/result.md", 1)[0] + "/pages/"
    assert not (Path(settings.LOCAL_STORAGE_DIR) / base).exists()


# ---------- L5M20-04 清理后 layout 不含路径泄露 ----------
async def test_cleaned_layout_paths_null(client, super_token, db_session):
    from sqlalchemy import text

    from app.core.database import AsyncSessionLocal
    from app.models.document import Document
    from app.services import document_service

    kb = await _create_kb(client, super_token, "P4-清理脱敏")
    detail = await _upload_wait(client, super_token, kb["id"])
    async with AsyncSessionLocal() as db:
        await db.execute(text("SELECT set_config('app.is_superuser', 'true', true)"))
        doc = await db.get(Document, uuid.UUID(detail["id"]))
        from datetime import timedelta

        doc.updated_at = doc.created_at - timedelta(days=10)
        await db.commit()
        cleaned = await document_service.cleanup_expired_pages(db, retention_days=7)
        assert cleaned == 1
    layout = (
        await client.get(
            f"/api/v1/kb/{kb['id']}/documents/{detail['id']}/layout",
            headers={"Authorization": f"Bearer {super_token}"},
        )
    ).json()["data"]
    for page in layout["pages"]:
        assert page["path"] is None
        assert page["cleaned"] is True


# ---------- L5M20-05 pending 用户页面预览 403 ----------
async def test_pending_user_page_preview_forbidden(client, super_token):
    kb = await _create_kb(client, super_token, "P4-安全pending")
    detail = await _upload_wait(client, super_token, kb["id"])
    original = settings.REGISTRATION_DEFAULT_PENDING
    settings.REGISTRATION_DEFAULT_PENDING = True
    try:
        username = await _unique("pend")
        await client.post(
            "/api/v1/auth/register",
            json={"username": username, "password": "Test@1234"},
        )
        token = await _login(client, username)
        resp = await client.get(
            f"/api/v1/kb/{kb['id']}/documents/{detail['id']}/pages/1",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403
    finally:
        settings.REGISTRATION_DEFAULT_PENDING = original
