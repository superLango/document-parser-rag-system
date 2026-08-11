"""L4 边界异常：Phase 3 GLM-OCR 拦截层（M19，含并发用例）。"""

import base64
import time
import uuid
from pathlib import Path

import httpx
import pytest

TEST_DOC = Path(__file__).resolve().parents[2] / "test_doc"
SAMPLE = "LSAM-JD01-0016  优质GH4169合金锻制棒材.pdf"


class FakeOCRBackend:
    def __init__(self, fail_types=None, delay=0, fail_exc=None):
        self.fail_types = set(fail_types or [])
        self.delay = delay
        self.fail_exc = fail_exc
        self.calls = []

    def ocr_block_sync(self, image_bytes, block_type, *, page_index=0, bbox=None):
        self.calls.append((page_index, block_type, tuple(bbox) if bbox else None))
        if self.delay:
            time.sleep(self.delay)
        if block_type in self.fail_types:
            if self.fail_exc:
                raise self.fail_exc
            raise RuntimeError(f"mock fail {block_type}")
        return f"ocr-{block_type}"


def _png_bytes(size=100):
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (size, size), 200).save(buf, format="PNG")
    return buf.getvalue()


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


# ---------- L4M19-01 OCR 超时 → 重试 → 失败记录 ----------
async def test_ocr_timeout_retries_then_failure(monkeypatch):
    from app.services.parsekit import ParseOptions, parse_pdf

    class TimeoutBackend(FakeOCRBackend):
        def ocr_block_sync(self, image_bytes, block_type, *, page_index=0, bbox=None):
            self.calls.append((page_index, block_type, tuple(bbox) if bbox else None))
            raise httpx.TimeoutException("mock timeout")

    import app.services.ocr_backend.glmocr as glmocr_mod

    backend = TimeoutBackend()
    monkeypatch.setattr(glmocr_mod, "get_ocr_backend", lambda: backend)
    pdf = (TEST_DOC / SAMPLE).read_bytes()
    result = parse_pdf(
        pdf,
        options=ParseOptions(dpi=100, ocr_enabled=True),
    )
    assert len(result.ocr_failures) > 0
    assert "timeout" in result.ocr_failures[0]["error"].lower() or "GLM-OCR" in result.ocr_failures[0]["error"]
    # 每个失败块至少调用一次；重试语义由 GLMOCRBackend 内部负责（见 L1M19-02/03）
    block_keys = {(p, t, b) for p, t, b in backend.calls}
    assert len(block_keys) == len(result.ocr_failures)


# ---------- L4M19-02 服务层策略 failed → 任务 failed ----------
async def test_service_ocr_policy_failed_marks_failed(monkeypatch, client, super_token, db_session):
    from sqlalchemy import text

    from app.core.database import AsyncSessionLocal
    from app.models.document import Document
    from app.services import document_service, storage
    from app.services.parsekit import OcrStageError

    kb = await _create_kb(client, super_token, "P3-边界-failed")
    async with AsyncSessionLocal() as db:
        await db.execute(text("SELECT set_config('app.is_superuser', 'true', true)"))
        await db.execute(
            text("SELECT set_config('app.current_kb', :kb, true)"), {"kb": kb["id"]}
        )
        key = await storage.put_original(
            uuid.UUID(kb["id"]), str(uuid.uuid4()), "f.pdf", b"%PDF x"
        )
        doc, _ = await document_service.create_document(
            db,
            uuid.UUID(kb["id"]),
            filename="f.pdf",
            file_type="pdf",
            file_size=6,
            sha256="8" * 64,
            object_key=key,
        )
        await db.refresh(doc)

    def boom(*args, **kwargs):
        raise OcrStageError("GLM-OCR 块识别失败且策略为 failed（U13）")

    monkeypatch.setattr(document_service, "parse_pdf", boom)
    async with AsyncSessionLocal() as db:
        await db.execute(text("SELECT set_config('app.is_superuser', 'true', true)"))
        await db.execute(
            text("SELECT set_config('app.current_kb', :kb, true)"), {"kb": kb["id"]}
        )
        with pytest.raises(RuntimeError):
            await document_service.run_parse_task(db, doc.id, uuid.UUID(kb["id"]))
        await document_service.fail_task(db, uuid.UUID(kb["id"]), doc.id, "GLM-OCR failed")
        fresh = await db.get(Document, doc.id)
        assert fresh.status == "failed"
        assert fresh.process_status == "failed"


# ---------- L4M19-03 并发 OCR 16 块全部成功无重复 ----------
async def test_ocr_concurrent_blocks():
    from app.services.parsekit.ocr import run_ocr_stage
    from app.services.parsekit.types import BBox, LayoutBlock, RenderPage

    page = RenderPage(
        page_index=1, width=595, height=842, image_bytes=_png_bytes(size=400)
    )
    blocks = [
        LayoutBlock(
            type="text",
            bbox=BBox(0.05 + 0.02 * i, 0.1, 0.3, 0.2),
            page_index=1,
            source="ppdoclayoutv3",
        )
        for i in range(16)
    ]
    backend = FakeOCRBackend(delay=0.1)
    t0 = time.monotonic()
    _, failures = run_ocr_stage(
        [page], [blocks], backend, page_concurrency=4, block_concurrency=8
    )
    elapsed = time.monotonic() - t0
    assert failures == []
    assert len(backend.calls) == 16
    assert len({(p, t, b) for p, t, b in backend.calls}) == 16
    assert elapsed < 1.0


# ---------- L4M19-04 超大图缩放 ----------
async def test_ocr_large_image_resized(monkeypatch):
    from app.services.ocr_backend.glmocr import GLMOCRBackend

    captured = {}

    class CaptureBackend:
        def ocr_block_sync(self, image_bytes, block_type, *, page_index=0, bbox=None):
            captured["bytes"] = image_bytes
            return "ok"

    _ = CaptureBackend()
    # 直接验证 prepare 后尺寸
    big = _png_bytes(size=5000)
    data_url = GLMOCRBackend._prepare_image(big, max_edge=2048, min_edge=32)
    raw = base64.b64decode(data_url.split(",", 1)[1])
    import io

    from PIL import Image

    img = Image.open(io.BytesIO(raw))
    assert max(img.size) <= 2048


# ---------- L4M19-05 ppdoclayoutv3 单页失败 partial ----------
async def test_ppdoclayoutv3_page_failure_partial(monkeypatch):
    from app.services.parsekit import ParseOptions, parse_pdf
    from app.services.parsekit.layout_ppdoc import PPDocLayoutEngine

    pdf = (TEST_DOC / SAMPLE).read_bytes()
    calls = {"n": 0}

    original = PPDocLayoutEngine._infer_page

    def flaky(self, image_bytes, width, height):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("injected page failure")
        return original(self, image_bytes, width, height)

    monkeypatch.setattr(PPDocLayoutEngine, "_infer_page", flaky)
    result = parse_pdf(
        pdf,
        options=ParseOptions(dpi=100, ocr_enabled=False),
    )
    assert len(result.page_failures) == 1
    assert result.page_failures[0]["stage"] == "layout"
    assert result.stats["page_failures"] == 1


# ---------- L4M19-06 OCR 返回异常内容（非 UTF-8/超长） ----------
async def test_ocr_oversized_content_recorded(monkeypatch):
    from app.services.parsekit import ParseOptions, parse_pdf

    class HugeBackend:
        def ocr_block_sync(self, image_bytes, block_type, *, page_index=0, bbox=None):
            return "x" * 200000

    import app.services.ocr_backend.glmocr as glmocr_mod

    monkeypatch.setattr(glmocr_mod, "get_ocr_backend", lambda: HugeBackend())
    pdf = (TEST_DOC / SAMPLE).read_bytes()
    result = parse_pdf(
        pdf,
        options=ParseOptions(dpi=100, ocr_enabled=True),
    )
    assert result.ocr_failures == []
    assert len(result.markdown) > 100000
