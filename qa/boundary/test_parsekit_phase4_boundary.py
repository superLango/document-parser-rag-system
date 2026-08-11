"""L4 边界异常：Phase 4 后处理/页面预览/7 天清理（M20，含并发）。"""

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


async def _create_kb(client, super_token, name):
    resp = await client.post(
        "/api/v1/kb",
        headers={"Authorization": f"Bearer {super_token}"},
        json={"name": name, "domain_code": "general"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def _pdf():
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "boundary", fontsize=12)
    data = doc.tobytes()
    doc.close()
    return data


async def _upload_wait(client, token, kb_id, name="b.pdf"):
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
    raise AssertionError("未完成")


# ---------- L4M20-01 页码越界/非法 ----------
async def test_page_index_out_of_range(client, super_token):
    kb = await _create_kb(client, super_token, "P4-越界")
    detail = await _upload_wait(client, super_token, kb["id"])
    h = {"Authorization": f"Bearer {super_token}"}
    assert (
        await client.get(
            f"/api/v1/kb/{kb['id']}/documents/{detail['id']}/pages/0", headers=h
        )
    ).status_code == 400
    assert (
        await client.get(
            f"/api/v1/kb/{kb['id']}/documents/{detail['id']}/pages/999", headers=h
        )
    ).status_code == 400
    assert (
        await client.get(
            f"/api/v1/kb/{kb['id']}/documents/{detail['id']}/pages/abc", headers=h
        )
    ).status_code == 400


# ---------- L4M20-02 已清理预览 400 ----------
async def test_page_preview_after_cleanup(client, super_token, db_session):
    from sqlalchemy import text

    from app.core.database import AsyncSessionLocal
    from app.models.document import Document

    kb = await _create_kb(client, super_token, "P4-已清理")
    detail = await _upload_wait(client, super_token, kb["id"])
    h = {"Authorization": f"Bearer {super_token}"}
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


# ---------- L4M20-03 并发清理幂等 ----------
async def test_concurrent_cleanup_idempotent(client, super_token, db_session):
    from sqlalchemy import text

    from app.core.database import AsyncSessionLocal
    from app.services import document_service, storage

    kb = await _create_kb(client, super_token, "P4-并发清理")
    async with AsyncSessionLocal() as db:
        await db.execute(text("SELECT set_config('app.is_superuser', 'true', true)"))
        await db.execute(
            text("SELECT set_config('app.current_kb', :kb, true)"), {"kb": kb["id"]}
        )
        task_id = str(uuid.uuid4())
        key = await storage.put_original(
            uuid.UUID(kb["id"]), task_id, "old.pdf", _pdf()
        )
        doc, _ = await document_service.create_document(
            db,
            uuid.UUID(kb["id"]),
            filename="old.pdf",
            file_type="pdf",
            file_size=8,
            sha256="c" * 64,
            object_key=key,
            task_id=task_id,
        )
        doc.status = "completed"
        doc.updated_at = doc.created_at - timedelta(days=9)
        base = document_service._ocr_base_from_object_key(key)
        storage.put_object(f"{base}layout.json", b'{"pages": []}', "application/json")
        storage.put_object(f"{base}pages/page-0001.png", b"png", "image/png")
        await db.commit()

    async def _clean():
        async with AsyncSessionLocal() as d:
            await d.execute(text("SELECT set_config('app.is_superuser', 'true', true)"))
            try:
                return await document_service.cleanup_expired_pages(d, retention_days=7)
            except Exception:
                return -1

    results = await asyncio.gather(_clean(), _clean(), _clean())
    assert sum(1 for r in results if r == 1) == 1
    assert all(r in (0, 1) for r in results)


# ---------- L4M20-04 损坏 layout 清理不中断 ----------
async def test_cleanup_skips_corrupt_layout(client, super_token, db_session):
    from sqlalchemy import text

    from app.core.database import AsyncSessionLocal
    from app.services import document_service, storage

    kb = await _create_kb(client, super_token, "P4-坏layout")
    async with AsyncSessionLocal() as db:
        await db.execute(text("SELECT set_config('app.is_superuser', 'true', true)"))
        await db.execute(
            text("SELECT set_config('app.current_kb', :kb, true)"), {"kb": kb["id"]}
        )
        task_id = str(uuid.uuid4())
        key = await storage.put_original(
            uuid.UUID(kb["id"]), task_id, "bad.pdf", _pdf()
        )
        doc, _ = await document_service.create_document(
            db,
            uuid.UUID(kb["id"]),
            filename="bad.pdf",
            file_type="pdf",
            file_size=8,
            sha256="d" * 64,
            object_key=key,
            task_id=task_id,
        )
        doc.status = "completed"
        doc.updated_at = doc.created_at - timedelta(days=9)
        base = document_service._ocr_base_from_object_key(key)
        storage.put_object(f"{base}layout.json", b"{corrupt", "application/json")
        await db.commit()

    async with AsyncSessionLocal() as db:
        await db.execute(text("SELECT set_config('app.is_superuser', 'true', true)"))
        cleaned = await document_service.cleanup_expired_pages(db, retention_days=7)
        assert cleaned == 0  # 坏 layout 跳过，不中断


# ---------- L4M20-05 retention 非法值 ----------
async def test_invalid_retention_days(client, super_token, db_session):
    from sqlalchemy import text

    from app.core.database import AsyncSessionLocal
    from app.services import document_service

    kb = await _create_kb(client, super_token, "P4-保留期")
    async with AsyncSessionLocal() as db:
        await db.execute(text("SELECT set_config('app.is_superuser', 'true', true)"))
        try:
            await document_service.cleanup_expired_pages(db, retention_days=0)
            raise AssertionError("应抛 ValueError")
        except ValueError as exc:
            assert "大于 0" in str(exc)


# ---------- L4M20-06 跨页表格刚好接触不标记 ----------
async def test_cross_page_table_touch_not_marked():
    from app.services.parsekit.rebuild import mark_cross_page_tables
    from app.services.parsekit.types import BBox, LayoutBlock

    pages = [
        [LayoutBlock(type="table", bbox=BBox(0.1, 0.9, 0.5, 0.98), page_index=1)],
        [LayoutBlock(type="table", bbox=BBox(0.5, 0.02, 0.9, 0.1), page_index=2)],
    ]
    assert mark_cross_page_tables(pages) == 0
