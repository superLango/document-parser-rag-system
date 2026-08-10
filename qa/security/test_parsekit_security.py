"""L5 安全渗透：Phase 2 文档解析管线（M18）。"""

import asyncio
import time
import uuid

import pytest
from sqlalchemy import text as sa_text

from app.core.config import settings


async def _unique(prefix: str) -> str:
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


async def _upload_wait(client, token, kb_id, name="sec.pdf", data=None):
    import pymupdf

    if data is None:
        doc = pymupdf.open()
        page = doc.new_page(width=400, height=600)
        page.insert_text((72, 100), "security", fontsize=12)
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
    raise AssertionError("文档未在 30s 内完成")


# ---------- L5M18-01 RLS 直接查询 ----------
async def test_rls_select_denied_without_context(client, super_token, db_session):
    from sqlalchemy.exc import DBAPIError, ProgrammingError

    kb = await _create_kb(client, super_token, "L5-RLS")
    detail = await _upload_wait(client, super_token, kb["id"])
    assert detail["status"] == "completed"

    try:
        await db_session.execute(
            sa_text("CREATE ROLE hansondoc_rls_phase2 NOSUPERUSER LOGIN")
        )
        await db_session.commit()
    except ProgrammingError:
        await db_session.rollback()
    await db_session.execute(sa_text("GRANT USAGE ON SCHEMA public TO hansondoc_rls_phase2"))
    await db_session.execute(sa_text("GRANT SELECT ON documents TO hansondoc_rls_phase2"))
    await db_session.execute(
        sa_text(
            "GRANT SELECT ON knowledge_bases, kb_members, kb_group_access, group_members "
            "TO hansondoc_rls_phase2"
        )
    )
    await db_session.commit()

    await db_session.execute(sa_text("SET ROLE hansondoc_rls_phase2"))
    rows = (
        await db_session.execute(sa_text("SELECT id, markdown_path FROM documents"))
    ).all()
    assert rows == []
    await db_session.execute(sa_text("RESET ROLE"))

    await db_session.execute(sa_text("SELECT set_config('app.is_superuser', 'true', true)"))
    rows = (
        await db_session.execute(sa_text("SELECT id, markdown_path FROM documents"))
    ).all()
    assert len(rows) >= 1


# ---------- L5M18-02 外部人/待审批访问产物 ----------
async def test_outsider_and_pending_denied(client, super_token):
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
    kb = await _create_kb(client, owner_token, "L5外部人")
    detail = await _upload_wait(client, owner_token, kb["id"])
    outsider_token = await _login(client, outsider_name)
    oh = {"Authorization": f"Bearer {outsider_token}"}
    for suffix in ("markdown", "layout"):
        resp = await client.get(
            f"/api/v1/kb/{kb['id']}/documents/{detail['id']}/{suffix}", headers=oh
        )
        assert resp.status_code == 403

    original = settings.REGISTRATION_DEFAULT_PENDING
    settings.REGISTRATION_DEFAULT_PENDING = True
    try:
        pending_name = await _unique("pend")
        await client.post(
            "/api/v1/auth/register",
            json={"username": pending_name, "password": "Test@1234"},
        )
        pending_token = await _login(client, pending_name)
        ph = {"Authorization": f"Bearer {pending_token}"}
        resp = await client.get(
            f"/api/v1/kb/{kb['id']}/documents/{detail['id']}/markdown", headers=ph
        )
        assert resp.status_code == 403
    finally:
        settings.REGISTRATION_DEFAULT_PENDING = original


# ---------- L5M18-03 路径穿越净化 ----------
async def test_path_traversal_sanitized(client, super_token, db_session):
    from app.core.database import AsyncSessionLocal
    from app.models.document import Document

    kb = await _create_kb(client, super_token, "L5路径穿越")
    resp = await client.post(
        f"/api/v1/kb/{kb['id']}/documents",
        headers={"Authorization": f"Bearer {super_token}"},
        files={"file": ("../../evil.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    assert resp.status_code == 200
    doc_id = resp.json()["data"]["document"]["id"]
    async with AsyncSessionLocal() as db:
        await db.execute(sa_text("SELECT set_config('app.is_superuser', 'true', true)"))
        doc = await db.get(Document, uuid.UUID(doc_id))
        assert ".." not in doc.object_key
        assert doc.object_key.endswith("evil.pdf")


# ---------- L5M18-04 跨 KB 隔离 ----------
async def test_cross_kb_isolation(client, super_token):
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
    kb_a = await _create_kb(client, owner_token, "L5-KB-A")
    kb_b = await _create_kb(client, owner_token, "L5-KB-B")
    await _invite_accept(client, owner_token, kb_b["id"], member_name)
    member_token = await _login(client, member_name)
    detail = await _upload_wait(client, owner_token, kb_a["id"])
    mh = {"Authorization": f"Bearer {member_token}"}
    resp = await client.get(
        f"/api/v1/kb/{kb_a['id']}/documents/{detail['id']}/markdown", headers=mh
    )
    assert resp.status_code == 403
    resp = await client.get(
        f"/api/v1/kb/{kb_a['id']}/documents/{detail['id']}/layout", headers=mh
    )
    assert resp.status_code == 403


# ---------- L5M18-05 viewer 不能重解析 ----------
async def test_viewer_cannot_reparse(client, super_token):
    owner_name = await _unique("owner")
    viewer_name = await _unique("viewer")
    for name in (owner_name, viewer_name):
        resp = await client.post(
            "/api/v1/users",
            headers={"Authorization": f"Bearer {super_token}"},
            json={"username": name, "password": "Test@1234", "role_codes": ["member"]},
        )
        assert resp.status_code == 200, resp.text
    owner_token = await _login(client, owner_name)
    kb = await _create_kb(client, owner_token, "L5重解析权限")
    viewer_token = await _invite_accept(client, owner_token, kb["id"], viewer_name)
    detail = await _upload_wait(client, owner_token, kb["id"])
    vh = {"Authorization": f"Bearer {viewer_token}"}
    resp = await client.post(
        f"/api/v1/kb/{kb['id']}/documents/{detail['id']}/reparse", headers=vh
    )
    assert resp.status_code == 403


# ---------- L5M18-06 审计留痕 ----------
async def test_audit_trails(client, super_token):
    kb = await _create_kb(client, super_token, "L5审计")
    detail = await _upload_wait(client, super_token, kb["id"])
    h = {"Authorization": f"Bearer {super_token}"}
    await client.post(
        f"/api/v1/kb/{kb['id']}/documents/{detail['id']}/reparse", headers=h
    )
    await asyncio.sleep(0.5)
    logs = (
        await client.get(
            "/api/v1/audit-logs?page=1&page_size=50", headers=h
        )
    ).json()["data"]["items"]
    actions = {log["action"] for log in logs}
    assert "document.upload" in actions
    assert "document.reparse" in actions


# ---------- L5M18-07 页眉页脚不泄漏 ----------
async def test_header_footer_not_leak(client, super_token):
    from pathlib import Path

    test_doc = Path(__file__).resolve().parents[2] / "test_doc"
    sample = (test_doc / "LSAM-JD01-0016  优质GH4169合金锻制棒材.pdf").read_bytes()
    kb = await _create_kb(client, super_token, "L5页眉页脚")
    detail = await _upload_wait(client, super_token, kb["id"], "sample.pdf", sample)
    assert detail["status"] == "completed"
    md = (
        await client.get(
            f"/api/v1/kb/{kb['id']}/documents/{detail['id']}/markdown",
            headers={"Authorization": f"Bearer {super_token}"},
        )
    ).text
    assert "Page 1 of 10" not in md


# ---------- L5M18-08 删除后产物不可读且存储清理 ----------
async def test_deleted_document_artifacts_removed(client, super_token):
    from app.core.config import settings
    from pathlib import Path

    kb = await _create_kb(client, super_token, "L5删除产物")
    detail = await _upload_wait(client, super_token, kb["id"])
    h = {"Authorization": f"Bearer {super_token}"}
    md_path = Path(settings.LOCAL_STORAGE_DIR) / detail["markdown_path"]
    assert md_path.exists()
    resp = await client.delete(
        f"/api/v1/kb/{kb['id']}/documents/{detail['id']}", headers=h
    )
    assert resp.status_code == 200
    for suffix in ("markdown", "layout"):
        resp = await client.get(
            f"/api/v1/kb/{kb['id']}/documents/{detail['id']}/{suffix}", headers=h
        )
        assert resp.status_code == 400
    # 原始 PDF 删除；产物目录随 delete_document_objects 按对象键删除
    assert not md_path.exists()
