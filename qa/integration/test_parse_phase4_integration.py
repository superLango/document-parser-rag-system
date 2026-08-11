"""L2 集成链路：Phase 4 后处理、页面预览与 7 天清理（M20）。"""

import asyncio
import json
import time
import uuid
from datetime import timedelta
from pathlib import Path

import pymupdf

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


def _pdf(text="phase4"):
    doc = pymupdf.open()
    for i in range(2):
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 100 + i * 100), f"{text} page {i + 1}", fontsize=12)
    data = doc.tobytes()
    doc.close()
    return data


async def _upload_wait(client, token, kb_id, name="p4.pdf"):
    resp = await client.post(
        f"/api/v1/kb/{kb_id}/documents",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": (name, _pdf(), "application/pdf")},
    )
    assert resp.status_code == 200, resp.text
    doc_id = resp.json()["data"]["document"]["id"]
    await client.post(
        f"/api/v1/kb/{kb_id}/documents/{doc_id}/start",
        headers={"Authorization": f"Bearer {token}"},
    )
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


# ---------- L2M20-01 完整管线结构树/U8/页面产物 ----------
async def test_pipeline_rebuild_artifacts(client, super_token):
    kb = await _create_kb(client, super_token, "P4-管线")
    detail = await _upload_wait(client, super_token, kb["id"])
    assert detail["status"] == "completed"
    h = {"Authorization": f"Bearer {super_token}"}
    layout = (
        await client.get(
            f"/api/v1/kb/{kb['id']}/documents/{detail['id']}/layout", headers=h
        )
    ).json()["data"]
    assert layout["schema_version"] == "1.2"
    assert "document_tree" in layout["rebuild"]
    assert layout["rebuild"]["enabled"] is True
    assert detail["pages_cleaned_at"] is None
    # 页面产物存在
    page = await client.get(
        f"/api/v1/kb/{kb['id']}/documents/{detail['id']}/pages/1", headers=h
    )
    assert page.status_code == 200
    assert page.content.startswith(b"\x89PNG") or page.content[:8] == b"\x89PNG\r\n"


# ---------- L2M20-02 页面预览权限（viewer 200 / outsider 403） ----------
async def test_page_preview_permissions(client, super_token):
    owner_name = await _unique("owner")
    viewer_name = await _unique("viewer")
    outsider_name = await _unique("outsider")
    for name in (owner_name, viewer_name, outsider_name):
        resp = await client.post(
            "/api/v1/users",
            headers={"Authorization": f"Bearer {super_token}"},
            json={"username": name, "password": "Test@1234", "role_codes": ["member"]},
        )
        assert resp.status_code == 200, resp.text
    owner_token = await _login(client, owner_name)
    kb = await _create_kb(client, owner_token, "P4-预览权限")
    viewer_token = await _invite_accept(client, owner_token, kb["id"], viewer_name)
    outsider_token = await _login(client, outsider_name)
    detail = await _upload_wait(client, owner_token, kb["id"])
    assert (
        await client.get(
            f"/api/v1/kb/{kb['id']}/documents/{detail['id']}/pages/1",
            headers={"Authorization": f"Bearer {viewer_token}"},
        )
    ).status_code == 200
    assert (
        await client.get(
            f"/api/v1/kb/{kb['id']}/documents/{detail['id']}/pages/1",
            headers={"Authorization": f"Bearer {outsider_token}"},
        )
    ).status_code == 403


# ---------- L2M20-03 7 天清理：过期清理/未过期保留 ----------
async def test_cleanup_expired_pages(client, super_token, db_session):
    from sqlalchemy import text

    from app.core.database import AsyncSessionLocal
    from app.models.document import Document
    from app.services import document_service, storage

    kb = await _create_kb(client, super_token, "P4-清理")
    async with AsyncSessionLocal() as db:
        await db.execute(text("SELECT set_config('app.is_superuser', 'true', true)"))
        await db.execute(
            text("SELECT set_config('app.current_kb', :kb, true)"), {"kb": kb["id"]}
        )
        task_id = str(uuid.uuid4())
        key = await storage.put_original(
            uuid.UUID(kb["id"]), task_id, "old.pdf", _pdf()
        )
        old, _ = await document_service.create_document(
            db,
            uuid.UUID(kb["id"]),
            filename="old.pdf",
            file_type="pdf",
            file_size=10,
            sha256="a" * 64,
            object_key=key,
            task_id=task_id,
        )
        fresh, _ = await document_service.create_document(
            db,
            uuid.UUID(kb["id"]),
            filename="fresh.pdf",
            file_type="pdf",
            file_size=10,
            sha256="b" * 64,
            object_key=await storage.put_original(
                uuid.UUID(kb["id"]), str(uuid.uuid4()), "fresh.pdf", _pdf()
            ),
        )
        # 模拟两个已完成文档（fresh 未过期、old 过期 8 天）
        for d in (old, fresh):
            d.status = "completed"
            d.process_status = "completed"
            d.updated_at = d.updated_at or d.created_at
        old.updated_at = old.created_at - timedelta(days=8)
        base = document_service._ocr_base_from_object_key(key)
        storage.put_object(f"{base}result.md", b"# result", "text/markdown")
        storage.put_object(
            f"{base}layout.json",
            json.dumps(
                {"pages": [{"page_index": 1, "path": "pages/page-0001.png"}]}
            ).encode(),
            "application/json",
        )
        storage.put_object(
            f"{base}pages/page-0001.png", b"\x89PNG\r\n\x1a\n", "image/png"
        )
        await db.commit()

        cleaned = await document_service.cleanup_expired_pages(db, retention_days=7)
        assert cleaned == 1
        await db.refresh(old)
        await db.refresh(fresh)
        assert old.pages_cleaned_at is not None
        assert fresh.pages_cleaned_at is None
        # 页面已删、result.md/layout.json 保留且 layout 标记清理
        pages_dir = Path(settings.LOCAL_STORAGE_DIR) / f"{base}pages/"
        assert not pages_dir.exists(), "pages 目录应被清理"
        assert (Path(settings.LOCAL_STORAGE_DIR) / f"{base}result.md").exists()
        layout = json.loads(
            storage.get_object(f"{base}layout.json").decode("utf-8")
        )
        assert layout["pages"][0]["path"] is None
        assert layout["pages"][0]["cleaned"] is True


# ---------- L2M20-04 页面越界/已清理预览 ----------
async def test_page_preview_out_of_range_and_cleaned(client, super_token, db_session):
    from sqlalchemy import text

    from app.core.database import AsyncSessionLocal
    from app.models.document import Document

    kb = await _create_kb(client, super_token, "P4-边界预览")
    detail = await _upload_wait(client, super_token, kb["id"])
    h = {"Authorization": f"Bearer {super_token}"}
    assert (
        await client.get(
            f"/api/v1/kb/{kb['id']}/documents/{detail['id']}/pages/999", headers=h
        )
    ).status_code == 400
    # 模拟已清理
    async with AsyncSessionLocal() as db:
        await db.execute(text("SELECT set_config('app.is_superuser', 'true', true)"))
        doc = await db.get(Document, uuid.UUID(detail["id"]))
        doc.pages_cleaned_at = doc.updated_at or doc.created_at
        await db.commit()
    resp = await client.get(
        f"/api/v1/kb/{kb['id']}/documents/{detail['id']}/pages/1", headers=h
    )
    assert resp.status_code == 400
    assert "清理" in resp.json()["message"]
