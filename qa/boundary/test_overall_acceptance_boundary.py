"""L4 边界异常：Phase 1-6 整体验收（M23，含并发）。"""

from pathlib import Path

import asyncio
import uuid
from datetime import timedelta

ROOT = Path(__file__).resolve().parents[2]


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
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "boundary overall", fontsize=12)
    data = doc.tobytes()
    doc.close()
    return data


async def _upload_wait(client, token, kb_id, name="b.pdf", data=None, timeout=60):
    import time

    resp = await client.post(
        f"/api/v1/kb/{kb_id}/documents",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": (name, data if data is not None else _pdf(), "application/pdf")},
    )
    assert resp.status_code == 200, resp.text
    doc_id = resp.json()["data"]["document"]["id"]
    deadline = time.monotonic() + timeout
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


# ---------- L4M23-01 并发上传 5 份 ----------
async def test_concurrent_uploads(client, super_token):
    kb = await _create_kb(client, super_token, "M23-并发上传")

    async def up(i):
        return await client.post(
            f"/api/v1/kb/{kb['id']}/documents",
            headers={"Authorization": f"Bearer {super_token}"},
            files={"file": (f"c{i}.pdf", _pdf(), "application/pdf")},
        )

    results = await asyncio.gather(*[up(i) for i in range(5)])
    assert all(r.status_code == 200 for r in results)
    task_ids = [r.json()["data"]["task"]["task_id"] for r in results]
    assert len(set(task_ids)) == 5
    # 全部最终完成
    import time

    for r in results:
        doc = r.json()["data"]["document"]
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            detail = (
                await client.get(
                    f"/api/v1/kb/{kb['id']}/documents/{doc['id']}",
                    headers={"Authorization": f"Bearer {super_token}"},
                )
            ).json()["data"]
            if detail["status"] == "completed":
                break
            await asyncio.sleep(0.2)
        else:
            raise AssertionError(f"文档 {doc['id']} 未完成")


# ---------- L4M23-02 并发重解析（服务层咨询锁） ----------
async def test_concurrent_reparse_lock(client, super_token, db_session):
    from sqlalchemy import text

    from app.core.database import AsyncSessionLocal
    from app.models.document import DocumentTask
    from app.services import document_service, storage

    kb = await _create_kb(client, super_token, "M23-并发重解析")
    async with AsyncSessionLocal() as db:
        await db.execute(text("SELECT set_config('app.is_superuser', 'true', true)"))
        await db.execute(
            text("SELECT set_config('app.current_kb', :kb, true)"), {"kb": kb["id"]}
        )
        key = await storage.put_original(
            uuid.UUID(kb["id"]), str(uuid.uuid4()), "lock.pdf", _pdf()
        )
        doc, task = await document_service.create_document(
            db,
            uuid.UUID(kb["id"]),
            filename="lock.pdf",
            file_type="pdf",
            file_size=10,
            sha256="e" * 64,
            object_key=key,
        )
        task.status = "completed"
        await db.commit()

    from app.core.exceptions import BusinessException

    async def reparse():
        async with AsyncSessionLocal() as d:
            await d.execute(text("SELECT set_config('app.is_superuser', 'true', true)"))
            await d.execute(
                text("SELECT set_config('app.current_kb', :kb, true)"), {"kb": kb["id"]}
            )
            try:
                await document_service.reset_document_for_reparse(
                    d, uuid.UUID(kb["id"]), doc.id, str(uuid.uuid4())
                )
                return "ok"
            except BusinessException:
                return "conflict"

    results = await asyncio.gather(reparse(), reparse())
    assert sorted(results) == ["conflict", "ok"]


# ---------- L4M23-03 OCR 失败 → partial ----------
async def test_ocr_failure_partial(monkeypatch, client, super_token, db_session):
    from sqlalchemy import text

    from app.core.database import AsyncSessionLocal
    from app.models.document import Document
    from app.services import document_service, storage
    from app.services.parsekit import ParseResult

    kb = await _create_kb(client, super_token, "M23-OCR-partial")
    async with AsyncSessionLocal() as db:
        await db.execute(text("SELECT set_config('app.is_superuser', 'true', true)"))
        await db.execute(
            text("SELECT set_config('app.current_kb', :kb, true)"), {"kb": kb["id"]}
        )
        key = await storage.put_original(
            uuid.UUID(kb["id"]), str(uuid.uuid4()), "p.pdf", _pdf()
        )
        doc, _ = await document_service.create_document(
            db,
            uuid.UUID(kb["id"]),
            filename="p.pdf",
            file_type="pdf",
            file_size=10,
            sha256="f" * 64,
            object_key=key,
        )
        await db.refresh(doc)

    def fake_parse(*args, **kwargs):
        return ParseResult(
            markdown="<!-- page: 1 -->\nbody",
            layout={"schema_version": "1.2", "pages": []},
            pages=[{"path": "pages/page-0001.png", "page_index": 1, "width": 595, "height": 842, "image_bytes": b"png"}],
            stats={"pages": 1, "blocks": 1, "ocr_blocks": 0, "ocr_failures": 1},
            ocr_failures=[{"page_index": 1, "block_type": "table", "error": "mock fail"}],
        )

    monkeypatch.setattr(document_service, "parse_pdf", fake_parse)
    async with AsyncSessionLocal() as db:
        await db.execute(text("SELECT set_config('app.is_superuser', 'true', true)"))
        await db.execute(
            text("SELECT set_config('app.current_kb', :kb, true)"), {"kb": kb["id"]}
        )
        result = await document_service.run_parse_task(db, doc.id, uuid.UUID(kb["id"]))
        assert result["partial"] is True
        fresh = await db.get(Document, doc.id)
        assert fresh.process_status == "partial"


# ---------- L4M23-04 并发清理幂等 ----------
async def test_concurrent_cleanup_idempotent(client, super_token, db_session):
    from sqlalchemy import text

    from app.core.database import AsyncSessionLocal
    from app.services import document_service, storage

    kb = await _create_kb(client, super_token, "M23-并发清理")
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
            file_size=10,
            sha256="a1" * 32,
            object_key=key,
            task_id=task_id,
        )
        doc.status = "completed"
        doc.updated_at = doc.created_at - timedelta(days=9)
        base = document_service._ocr_base_from_object_key(key)
        storage.put_object(f"{base}layout.json", b'{"pages": []}', "application/json")
        storage.put_object(f"{base}pages/page-0001.png", b"png", "image/png")
        await db.commit()

    async def clean():
        async with AsyncSessionLocal() as d:
            await d.execute(text("SELECT set_config('app.is_superuser', 'true', true)"))
            return await document_service.cleanup_expired_pages(d, retention_days=7)

    results = await asyncio.gather(clean(), clean(), clean())
    assert sum(1 for r in results if r == 1) == 1
    assert all(r in (0, 1) for r in results)


# ---------- L4M23-05 入口校验（非 PDF/空/超限） ----------
async def test_upload_entry_validation(client, super_token):
    from app.core.config import settings

    kb = await _create_kb(client, super_token, "M23-入口校验")
    h = {"Authorization": f"Bearer {super_token}"}
    bad = await client.post(
        f"/api/v1/kb/{kb['id']}/documents",
        headers=h,
        files={"file": ("a.txt", b"hello", "text/plain")},
    )
    assert bad.status_code == 400
    empty = await client.post(
        f"/api/v1/kb/{kb['id']}/documents",
        headers=h,
        files={"file": ("e.pdf", b"", "application/pdf")},
    )
    assert empty.status_code == 400
    original = settings.DOCUMENT_MAX_SIZE_MB
    settings.DOCUMENT_MAX_SIZE_MB = 0
    try:
        big = await client.post(
            f"/api/v1/kb/{kb['id']}/documents",
            headers=h,
            files={"file": ("big.pdf", b"%PDF x", "application/pdf")},
        )
        assert big.status_code == 400
    finally:
        settings.DOCUMENT_MAX_SIZE_MB = original
