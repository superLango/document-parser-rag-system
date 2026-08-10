"""L2 集成链路：Phase 3 GLM-OCR 拦截层 + DocLayout-YOLO 真实引擎（M19）。"""

import asyncio
import time
import uuid
from pathlib import Path

import httpx
import pytest

from app.core.config import settings

TEST_DOC = Path(__file__).resolve().parents[2] / "test_doc"
SAMPLE = "LSAM-JD01-0016  优质GH4169合金锻制棒材.pdf"


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


class FakeOCRBackend:
    def __init__(self, text="OCR识别文本", fail_types=None, delay=0):
        self.text = text
        self.fail_types = set(fail_types or [])
        self.delay = delay
        self.calls = []

    def ocr_block_sync(self, image_bytes, block_type, *, page_index=0, bbox=None):
        self.calls.append((page_index, block_type))
        if self.delay:
            time.sleep(self.delay)
        if block_type in self.fail_types:
            raise RuntimeError(f"mock fail {block_type}")
        return f"{self.text}-{block_type}"


# ---------- L2M19-01 doclayout + fake OCR 全链路 ----------
async def test_pipeline_doclayout_with_fake_ocr(monkeypatch):
    import app.services.ocr_backend.glmocr as glmocr_mod
    from app.services.parsekit import ParseOptions, parse_pdf

    backend = FakeOCRBackend()
    monkeypatch.setattr(glmocr_mod, "get_ocr_backend", lambda: backend)
    pdf = (TEST_DOC / SAMPLE).read_bytes()
    result = parse_pdf(
        pdf,
        options=ParseOptions(layout_engine="doclayout", dpi=100, ocr_enabled=True),
    )
    assert result.stats["engine"] == "doclayout"
    assert result.stats["blocks"] > 0
    assert result.stats["ocr_blocks"] > 0
    assert result.ocr_failures == []
    assert len(backend.calls) == result.stats["ocr_blocks"]
    assert "OCR识别文本-table" in result.markdown or "OCR识别文本-text" in result.markdown
    assert result.layout["schema_version"] == "1.1"
    assert result.layout["ocr"]["backend"] == "glm-ocr"


# ---------- L2M19-02 服务层 partial（OCR 失败默认策略） ----------
async def test_service_ocr_partial(monkeypatch, client, super_token, db_session):
    from sqlalchemy import text

    from app.core.database import AsyncSessionLocal
    from app.models.document import Document
    from app.services import document_service, storage
    from app.services.parsekit import ParseResult

    kb = await _create_kb(client, super_token, "P3-OCR-partial")
    async with AsyncSessionLocal() as db:
        await db.execute(text("SELECT set_config('app.is_superuser', 'true', true)"))
        await db.execute(
            text("SELECT set_config('app.current_kb', :kb, true)"), {"kb": kb["id"]}
        )
        key = await storage.put_original(
            uuid.UUID(kb["id"]), str(uuid.uuid4()), "p3.pdf", b"%PDF x"
        )
        doc, _ = await document_service.create_document(
            db,
            uuid.UUID(kb["id"]),
            filename="p3.pdf",
            file_type="pdf",
            file_size=6,
            sha256="7" * 64,
            object_key=key,
        )
        await db.refresh(doc)

    def fake_parse(*args, **kwargs):
        return ParseResult(
            markdown="<!-- page: 1 -->\nbody",
            layout={"schema_version": "1.1", "pages": [], "ocr": {"backend": "glm-ocr"}},
            pages=[{"path": "pages/page-0001.png", "page_index": 1, "width": 595, "height": 842, "image_bytes": b"png"}],
            stats={"pages": 1, "blocks": 1, "ocr_blocks": 1, "ocr_failures": 1},
            ocr_failures=[{"page_index": 1, "block_type": "table", "error": "mock ocr fail"}],
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


# ---------- L2M19-03 策略 failed → 抛 OcrStageError ----------
async def test_pipeline_ocr_policy_failed(monkeypatch):
    import app.services.ocr_backend.glmocr as glmocr_mod
    from app.services.parsekit import OcrStageError, ParseOptions, parse_pdf

    backend = FakeOCRBackend(fail_types={"table", "text", "title"})
    monkeypatch.setattr(glmocr_mod, "get_ocr_backend", lambda: backend)
    pdf = (TEST_DOC / SAMPLE).read_bytes()

    # 默认 partial：返回结果并记录失败
    result = parse_pdf(
        pdf,
        options=ParseOptions(
            layout_engine="doclayout", dpi=100, ocr_enabled=True,
            ocr_failure_policy="partial",
        ),
    )
    assert len(result.ocr_failures) > 0
    assert result.stats["ocr_failures"] > 0

    # failed：直接抛错（U13）
    with pytest.raises(OcrStageError):
        parse_pdf(
            pdf,
            options=ParseOptions(
                layout_engine="doclayout", dpi=100, ocr_enabled=True,
                ocr_failure_policy="failed",
            ),
        )


# ---------- L2M19-04 真实 GLM-OCR 冒烟（服务可用时执行） ----------
async def test_real_glmocr_smoke(monkeypatch):
    try:
        resp = httpx.get(
            f"{settings.GLMOCR_SERVER_URL.rsplit('/v1/', 1)[0]}/v1/models",
            timeout=5,
        )
        if resp.status_code != 200:
            pytest.skip("GLM-OCR 服务不可用")
    except Exception:
        pytest.skip("GLM-OCR 服务不可用")

    from app.services.parsekit import ParseOptions, parse_pdf

    pdf = (TEST_DOC / SAMPLE).read_bytes()
    result = parse_pdf(
        pdf,
        options=ParseOptions(layout_engine="doclayout", dpi=100, ocr_enabled=True),
    )
    assert result.ocr_failures == []
    assert result.stats["ocr_blocks"] > 0
    assert "优质 GH4169" in result.markdown
    assert "Page 1 of 10" not in result.markdown
    assert "<table" in result.markdown
