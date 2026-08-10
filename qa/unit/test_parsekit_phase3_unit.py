"""L1 单元测试：DocLayout-YOLO 真实引擎（M18 补测）+ GLM-OCR 拦截层（M19）。"""

import base64
import hashlib
import io
import time

import httpx
import pytest
import pymupdf

from app.services.ocr_backend.glmocr import GLMOCRBackend, OcrBlockError
from app.services.parsekit import InvalidParseOptions, ParseOptions, parse_pdf
from app.services.parsekit.errors import LayoutModelUnavailable
from app.services.parsekit.layout import DocLayoutEngine
from app.services.parsekit.ocr import crop_block, run_ocr_stage
from app.services.parsekit.render import render_pdf
from app.services.parsekit.types import BBox, LayoutBlock, RenderPage, TextBlock

WEIGHTS = (
    "/home/grainuser/hansonDoc_RAG/models/doclayout_yolo/doclayout_yolo.pt"
)
WEIGHTS_SHA256 = "1b152460888dc30be6db7f5dfab28bde3dcc999e5202f46187a764a1699c80be"


def _pdf_bytes(text="hello ocr"):
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), text, fontsize=12)
    data = doc.tobytes()
    doc.close()
    return data


def _png_bytes(size=100, color=200):
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (size, size), color).save(buf, format="PNG")
    return buf.getvalue()


class FakeHttpClient:
    """可编程 httpx.Client 替身。"""

    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.calls = []

    def post(self, url, json=None, **kwargs):
        self.calls.append({"url": url, "json": json})
        if self.responses:
            resp = self.responses.pop(0)
            if isinstance(resp, Exception):
                raise resp
            resp.request = httpx.Request("POST", url)
            return resp
        resp = httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}]})
        resp.request = httpx.Request("POST", url)
        return resp

    def close(self):
        pass


# ---------- M18 补测：真实权重完整性/加载/推理 ----------
async def test_doclayout_weights_present_and_hash_locked():
    import os

    assert os.path.exists(WEIGHTS), "DocLayout-YOLO 权重必须部署"
    digest = hashlib.sha256(open(WEIGHTS, "rb").read()).hexdigest()
    assert digest == WEIGHTS_SHA256


async def test_doclayout_real_engine_load():
    engine = DocLayoutEngine(WEIGHTS, device="cpu")
    model = engine._load_model()
    assert engine._names[0] == "title"
    assert len(engine._names) == 10
    assert model is not None


async def test_doclayout_real_engine_single_page_infer():
    engine = DocLayoutEngine(WEIGHTS, device="cpu")
    pdf = _pdf_bytes()
    page = render_pdf(pdf, dpi=100, partial_on_page_failure=True).pages[0]
    blocks = engine.analyze([page])[0]
    assert isinstance(blocks, list)
    for b in blocks:
        assert 0.0 <= b.bbox.x0 <= 1.0
        assert 0.0 <= b.bbox.y1 <= 1.0
        assert b.source == "doclayout"
        assert b.confidence > 0


async def test_doclayout_real_engine_page_failure_partial(monkeypatch):
    engine = DocLayoutEngine(WEIGHTS, device="cpu")
    page = render_pdf(_pdf_bytes(), dpi=100, partial_on_page_failure=True).pages[0]

    def boom(image_bytes):
        raise RuntimeError("injected layout failure")

    monkeypatch.setattr(engine, "_infer_page", boom)
    blocks = engine.analyze([page])[0]
    assert blocks == []
    assert len(engine.failures) == 1
    assert engine.failures[0]["page_index"] == 1


# ---------- M19 L1：GLMOCRBackend ----------
async def test_glmocr_success_parse():
    backend = GLMOCRBackend(
        server_url="http://fake/v1/chat/completions",
        model="GLM-OCR",
        retries=2,
        client=FakeHttpClient(),
    )
    text = backend.ocr_block_sync(_png_bytes(), "text", page_index=3)
    assert text == "OK"
    payload = backend._client.calls[0]["json"]
    assert payload["model"] == "GLM-OCR"
    content = payload["messages"][0]["content"]
    assert content[0]["type"] == "image_url"
    assert content[0]["image_url"]["url"].startswith("data:image/png;base64,")
    assert "正文" in content[1]["text"]


async def test_glmocr_empty_content_retries_then_fail():
    backend = GLMOCRBackend(
        retries=2,
        client=FakeHttpClient(
            [
                httpx.Response(200, json={"choices": [{"message": {"content": "  "}}]}),
                httpx.Response(200, json={"choices": [{"message": {"content": ""}}]}),
                httpx.Response(200, json={"choices": [{"message": {"content": "x"}}]}),
            ]
        ),
    )
    text = backend.ocr_block_sync(_png_bytes(), "text")
    assert text == "x"
    assert len(backend._client.calls) == 3


async def test_glmocr_http_error_retries_then_fail():
    backend = GLMOCRBackend(
        retries=2,
        client=FakeHttpClient(
            [
                httpx.Response(500),
                httpx.Response(503),
                httpx.Response(500),
            ]
        ),
    )
    with pytest.raises(OcrBlockError):
        backend.ocr_block_sync(_png_bytes(), "table")
    assert len(backend._client.calls) == 3


async def test_glmocr_image_resize():
    big = _png_bytes(size=4096)
    data_url = GLMOCRBackend._prepare_image(big, max_edge=2048, min_edge=32)
    raw = base64.b64decode(data_url.split(",", 1)[1])
    from PIL import Image

    img = Image.open(io.BytesIO(raw))
    assert max(img.size) <= 2048
    small = _png_bytes(size=64)
    data_url2 = GLMOCRBackend._prepare_image(small, max_edge=2048, min_edge=32)
    img2 = Image.open(io.BytesIO(base64.b64decode(data_url2.split(",", 1)[1])))
    assert img2.size == (64, 64)


async def test_glmocr_prompt_by_type():
    assert "HTML <table>" in GLMOCRBackend._prompt_for("table")
    assert "LaTeX" in GLMOCRBackend._prompt_for("formula")
    assert "正文" in GLMOCRBackend._prompt_for("text")
    assert "标题" in GLMOCRBackend._prompt_for("title")


# ---------- M19 L1：裁剪与并发 ----------
async def test_crop_block_and_bounds():
    page_img = _png_bytes(size=200)
    crop = crop_block(page_img, BBox(0.1, 0.1, 0.5, 0.5))
    from PIL import Image

    img = Image.open(io.BytesIO(crop))
    assert img.size == (80, 80)
    crop2 = crop_block(page_img, BBox(-0.1, -0.1, 1.2, 1.2))
    assert Image.open(io.BytesIO(crop2)).size == (200, 200)


class FakeOCRBackend:
    def __init__(self, fail_types=None, delay=0.01, text="ocr-text"):
        self.fail_types = set(fail_types or [])
        self.delay = delay
        self.text = text
        self.calls = 0

    def ocr_block_sync(self, image_bytes, block_type, *, page_index=0, bbox=None):
        self.calls += 1
        time.sleep(self.delay)
        if block_type in self.fail_types:
            raise OcrBlockError(f"mock fail {block_type}")
        return f"{self.text}-{block_type}"


async def test_ocr_stage_concurrent():
    page = RenderPage(
        page_index=1, width=595, height=842, image_bytes=_png_bytes(size=300)
    )
    blocks = [
        LayoutBlock(
            type="text",
            bbox=BBox(0.1, 0.1 + i * 0.08, 0.5, 0.16 + i * 0.08),
            page_index=1,
            source="doclayout",
        )
        for i in range(8)
    ]
    backend = FakeOCRBackend(delay=0.15)
    t0 = time.monotonic()
    result, failures = run_ocr_stage(
        [page], [blocks], backend, page_concurrency=2, block_concurrency=8
    )
    elapsed = time.monotonic() - t0
    assert failures == []
    assert all((b.structural or {}).get("ocr_source") == "glm-ocr" for b in result[0])
    assert elapsed < 0.8  # 8 块并发而不是串行 1.2s


async def test_ocr_stage_failure_recorded():
    page = RenderPage(
        page_index=1, width=595, height=842, image_bytes=_png_bytes(size=300)
    )
    blocks = [
        LayoutBlock(
            type="table",
            bbox=BBox(0.1, 0.2, 0.6, 0.5),
            page_index=1,
            source="doclayout",
        )
    ]
    backend = FakeOCRBackend(fail_types={"table"})
    result, failures = run_ocr_stage([page], [blocks], backend)
    assert len(failures) == 1
    assert failures[0]["block_type"] == "table"
    assert "ocr_failed" in (result[0][0].structural or {})


# ---------- M19 L1：拼装/参数 ----------
async def test_formula_latex_in_markdown():
    from app.services.parsekit.assemble import assemble_markdown

    md = assemble_markdown(
        [
            LayoutBlock(
                type="formula",
                bbox=BBox(0.1, 0.1, 0.5, 0.2),
                page_index=1,
                content="E=mc^2",
            )
        ]
    )
    assert "$$E=mc^2$$" in md


async def test_invalid_ocr_policy():
    with pytest.raises(InvalidParseOptions):
        parse_pdf(b"%PDF test", options=ParseOptions(ocr_failure_policy="unknown"))


async def test_rule_engine_skips_ocr_blocks():
    """规则引擎文本块不重复 OCR（Phase 3 语义）。"""
    page = render_pdf(_pdf_bytes("hello text"), dpi=100).pages[0]
    blocks = [
        LayoutBlock(
            type="text",
            bbox=BBox(0.1, 0.1, 0.5, 0.2),
            page_index=1,
            content="hello text",
            source="text",
        )
    ]
    backend = FakeOCRBackend()
    result, failures = run_ocr_stage([page], [blocks], backend)
    assert backend.calls == 0
    assert failures == []
    assert result[0][0].content == "hello text"
