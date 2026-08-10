"""L4 边界异常：Phase 2 文档解析管线（M18，含并发用例）。"""

import asyncio
import io
import time
import uuid

import pymupdf
import pytest

from app.core.config import settings


async def _unique(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


async def _create_kb(client, super_token, name):
    resp = await client.post(
        "/api/v1/kb",
        headers={"Authorization": f"Bearer {super_token}"},
        json={"name": name, "domain_code": "general"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


async def _upload(client, token, kb_id, name, data):
    resp = await client.post(
        f"/api/v1/kb/{kb_id}/documents",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": (name, data, "application/pdf")},
    )
    return resp


async def _wait_status(client, token, kb_id, doc_id, target="completed", timeout=60.0):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        resp = await client.get(
            f"/api/v1/kb/{kb_id}/documents/{doc_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, resp.text
        last = resp.json()["data"]
        if last["status"] == target or last["process_status"] == target:
            return last
        await asyncio.sleep(0.2)
    raise AssertionError(f"未达到 {target}，最后={last}")


def _simple_pdf(pages=1, text="boundary"):
    doc = pymupdf.open()
    for i in range(pages):
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 100 + i * 40), f"{text} {i + 1}", fontsize=12)
    data = doc.tobytes()
    doc.close()
    return data


def _image_only_pdf():
    doc = pymupdf.open()
    page = doc.new_page(width=400, height=600)
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 300, 400))
    pix.clear_with(200)
    page.insert_image(pymupdf.Rect(50, 50, 350, 450), pixmap=pix)
    data = doc.tobytes()
    doc.close()
    return data


def _encrypted_pdf():
    doc = pymupdf.open()
    page = doc.new_page(width=400, height=600)
    page.insert_text((72, 100), "secret", fontsize=12)
    buf = io.BytesIO()
    doc.save(
        buf,
        encryption=pymupdf.PDF_ENCRYPT_AES_256,
        user_pw="u1234567",
        owner_pw="o1234567",
    )
    doc.close()
    return buf.getvalue()


# ---------- L4M18-01 空 PDF ----------
async def test_empty_pdf_rejected(client, super_token):
    kb = await _create_kb(client, super_token, "L4空PDF")
    resp = await _upload(client, super_token, kb["id"], "empty.pdf", b"")
    assert resp.status_code == 400
    assert "空" in resp.json()["message"]


# ---------- L4M18-02 半有效 PDF（%PDF 头 + 垃圾体） ----------
async def test_half_valid_pdf_failed(client, super_token):
    kb = await _create_kb(client, super_token, "L4半有效PDF")
    resp = await _upload(client, super_token, kb["id"], "half.pdf", b"%PDF-1.4 garbage body")
    assert resp.status_code == 200
    doc = resp.json()["data"]["document"]
    detail = await _wait_status(client, super_token, kb["id"], doc["id"], target="failed")
    assert "PDF" in detail["error"]["message"] or "无法打开" in detail["error"]["message"]


# ---------- L4M18-03 加密 PDF ----------
async def test_encrypted_pdf_failed(client, super_token):
    kb = await _create_kb(client, super_token, "L4加密PDF")
    resp = await _upload(client, super_token, kb["id"], "enc.pdf", _encrypted_pdf())
    assert resp.status_code == 200
    doc = resp.json()["data"]["document"]
    detail = await _wait_status(client, super_token, kb["id"], doc["id"], target="failed")
    assert "加密" in detail["error"]["message"]


# ---------- L4M18-04 doclayout 权重缺失 ----------
async def test_doclayout_missing_weights_failed(client, super_token):
    kb = await _create_kb(client, super_token, "L4权重缺失")
    original_engine = settings.PARSEKIT_LAYOUT_ENGINE
    original_dir = settings.PARSEKIT_LAYOUT_MODEL_DIR
    settings.PARSEKIT_LAYOUT_ENGINE = "doclayout"
    settings.PARSEKIT_LAYOUT_MODEL_DIR = "/nonexistent/doclayout_yolo"
    try:
        resp = await _upload(client, super_token, kb["id"], "w.pdf", _simple_pdf())
        assert resp.status_code == 200
        doc = resp.json()["data"]["document"]
        detail = await _wait_status(client, super_token, kb["id"], doc["id"], target="failed")
        assert "DocLayout-YOLO 权重未部署" in detail["error"]["message"]
    finally:
        settings.PARSEKIT_LAYOUT_ENGINE = original_engine
        settings.PARSEKIT_LAYOUT_MODEL_DIR = original_dir


# ---------- L4M18-05 并发上传 5 份 ----------
async def test_concurrent_uploads(client, super_token):
    kb = await _create_kb(client, super_token, "L4并发上传")
    h = {"Authorization": f"Bearer {super_token}"}

    async def _up(i):
        return await _upload(client, super_token, kb["id"], f"c{i}.pdf", _simple_pdf())

    results = await asyncio.gather(*[_up(i) for i in range(5)])
    assert all(r.status_code == 200 for r in results)
    task_ids = [r.json()["data"]["task"]["task_id"] for r in results]
    assert len(set(task_ids)) == 5
    for r in results:
        doc = r.json()["data"]["document"]
        await _wait_status(client, super_token, kb["id"], doc["id"])


# ---------- L4M18-06 并发重解析：服务层咨询锁 ----------
async def test_concurrent_reparse_service_lock(client, super_token, db_session):
    from sqlalchemy import select, text

    from app.core.database import AsyncSessionLocal
    from app.models.document import Document, DocumentTask
    from app.services import document_service, storage

    kb = await _create_kb(client, super_token, "L4并发重解析")
    async with AsyncSessionLocal() as db:
        await db.execute(text("SELECT set_config('app.is_superuser', 'true', true)"))
        await db.execute(
            text("SELECT set_config('app.current_kb', :kb, true)"), {"kb": kb["id"]}
        )
        key = await storage.put_original(
            uuid.UUID(kb["id"]), str(uuid.uuid4()), "lock.pdf", _simple_pdf()
        )
        doc, task = await document_service.create_document(
            db,
            uuid.UUID(kb["id"]),
            filename="lock.pdf",
            file_type="pdf",
            file_size=len(_simple_pdf()),
            sha256="2" * 64,
            object_key=key,
        )
        task.status = "completed"  # 模拟首轮已完成，之后才允许并发重解析
        await db.commit()

    from app.core.exceptions import BusinessException

    async def _reparse():
        async with AsyncSessionLocal() as d:
            await d.execute(text("SELECT set_config('app.is_superuser', 'true', true)"))
            await d.execute(
                text("SELECT set_config('app.current_kb', :kb, true)"),
                {"kb": kb["id"]},
            )
            try:
                await document_service.reset_document_for_reparse(
                    d, uuid.UUID(kb["id"]), doc.id, str(uuid.uuid4())
                )
                return "ok"
            except BusinessException:
                return "conflict"

    results = await asyncio.gather(_reparse(), _reparse())
    assert sorted(results) == ["conflict", "ok"]


# ---------- L4M18-07 并发重解析 API 冒烟 ----------
async def test_concurrent_reparse_api(client, super_token):
    kb = await _create_kb(client, super_token, "L4并发重解析API")
    resp = await _upload(client, super_token, kb["id"], "api.pdf", _simple_pdf())
    doc = resp.json()["data"]["document"]
    await _wait_status(client, super_token, kb["id"], doc["id"])
    h = {"Authorization": f"Bearer {super_token}"}

    async def _reparse():
        return await client.post(
            f"/api/v1/kb/{kb['id']}/documents/{doc['id']}/reparse", headers=h
        )

    results = await asyncio.gather(*[_reparse() for _ in range(5)])
    assert all(r.status_code in (200, 400) for r in results)
    ok = [r for r in results if r.status_code == 200]
    assert len(ok) >= 1
    task_ids = [r.json()["data"]["task"]["task_id"] for r in ok]
    assert len(task_ids) == len(set(task_ids))
    final = await _wait_status(client, super_token, kb["id"], doc["id"])
    assert final["status"] == "completed"


# ---------- L4M18-08 单页失败 → partial ----------
async def test_partial_page_failure(monkeypatch, client, super_token, db_session):
    from sqlalchemy import text

    from app.core.database import AsyncSessionLocal
    from app.models.document import Document
    from app.services import document_service, storage
    from app.services.parsekit import ParseResult

    kb = await _create_kb(client, super_token, "L4单页失败")
    async with AsyncSessionLocal() as db:
        await db.execute(text("SELECT set_config('app.is_superuser', 'true', true)"))
        await db.execute(
            text("SELECT set_config('app.current_kb', :kb, true)"), {"kb": kb["id"]}
        )
        key = await storage.put_original(
            uuid.UUID(kb["id"]), str(uuid.uuid4()), "partial.pdf", _simple_pdf()
        )
        doc, _ = await document_service.create_document(
            db,
            uuid.UUID(kb["id"]),
            filename="partial.pdf",
            file_type="pdf",
            file_size=10,
            sha256="3" * 64,
            object_key=key,
        )
        await db.refresh(doc)

    def fake_parse(*args, **kwargs):
        return ParseResult(
            markdown="<!-- page: 1 -->\nbody",
            layout={"schema_version": "1.0", "pages": [], "page_failures": [{"page_index": 2, "error": "boom"}]},
            pages=[{"path": "pages/page-0001.png", "page_index": 1, "width": 595, "height": 842, "image_bytes": b"png"}],
            stats={"pages": 1, "blocks": 1, "erased_blocks": 0, "page_failures": 1},
            page_failures=[{"page_index": 2, "error": "boom"}],
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
        assert fresh.status == "completed"


# ---------- L4M18-09 多页 PDF（20 页） ----------
async def test_many_page_pdf(client, super_token):
    kb = await _create_kb(client, super_token, "L4多页PDF")
    resp = await _upload(client, super_token, kb["id"], "many.pdf", _simple_pdf(20))
    doc = resp.json()["data"]["document"]
    detail = await _wait_status(client, super_token, kb["id"], doc["id"])
    assert detail["page_count"] == 20


# ---------- L4M18-10 非法 DPI 配置 ----------
async def test_invalid_dpi_config(client, super_token):
    kb = await _create_kb(client, super_token, "L4非法DPI")
    original = settings.PARSEKIT_DPI
    settings.PARSEKIT_DPI = 10
    try:
        resp = await _upload(client, super_token, kb["id"], "dpi.pdf", _simple_pdf())
        doc = resp.json()["data"]["document"]
        detail = await _wait_status(client, super_token, kb["id"], doc["id"], target="failed")
        assert "DPI" in detail["error"]["message"]
    finally:
        settings.PARSEKIT_DPI = original


# ---------- L4M18-11 纯图片 PDF（无文本层） ----------
async def test_image_only_pdf(client, super_token):
    kb = await _create_kb(client, super_token, "L4纯图片PDF")
    resp = await _upload(client, super_token, kb["id"], "img.pdf", _image_only_pdf())
    assert resp.status_code == 200, resp.text
    doc = resp.json()["data"]["document"]
    detail = await _wait_status(client, super_token, kb["id"], doc["id"])
    assert detail["status"] == "completed"
    md = (
        await client.get(
            f"/api/v1/kb/{kb['id']}/documents/{doc['id']}/markdown",
            headers={"Authorization": f"Bearer {super_token}"},
        )
    ).text
    assert "<!-- image: page 1 -->" in md
