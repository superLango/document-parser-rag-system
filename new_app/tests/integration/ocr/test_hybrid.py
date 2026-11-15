from __future__ import annotations

import asyncio

import pymupdf

from services.ocr.adapters.base import OcrBackendError
from services.ocr.adapters.glm import GlmOcrAdapter
from services.ocr.adapters.hybrid import HybridOcrAdapter, has_text_layer
from services.ocr.contracts import OcrRequest


def _pdf_with_text() -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_textbox(
        pymupdf.Rect(50, 50, 550, 750),
        "Q355B Rm 470 MPa Q235B Rm 400 MPa " * 20,
        fontsize=10,
    )
    data = document.tobytes()
    document.close()
    return data


def _pdf_with_partial_text() -> bytes:
    document = pymupdf.open()
    first = document.new_page()
    first.insert_textbox(
        pymupdf.Rect(50, 50, 550, 200),
        "Q355B Rm 470 MPa Q235B Rm 400 MPa Q345B Rm 450 MPa Q390B Rm 430 MPa",
        fontsize=10,
    )
    second = document.new_page()
    second.insert_text((72, 72), "page 2 Q355B Rm 470 MPa")
    data = document.tobytes()
    document.close()
    return data


def _pdf_without_text() -> bytes:
    document = pymupdf.open()
    document.new_page()
    data = document.tobytes()
    document.close()
    return data


def _pdf_with_gibberish_text() -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_textbox(
        pymupdf.Rect(50, 50, 550, 750),
        '1nij"AHj?#!< tst> #1&7)&!&75& 8?&7&!&7(& ' * 20,
        fontsize=10,
    )
    data = document.tobytes()
    document.close()
    return data


def _request() -> OcrRequest:
    return OcrRequest(
        document_id="doc-1",
        storage_key="documents/doc-1/file.pdf",
        filename="file.pdf",
        content_type="application/pdf",
    )


def test_text_layer_pdf_uses_native_backend() -> None:
    assert has_text_layer(_pdf_with_text())


def test_image_only_pdf_falls_back_to_vision_model() -> None:
    assert not has_text_layer(_pdf_without_text())


def test_gibberish_text_layer_is_not_trusted() -> None:
    assert not has_text_layer(_pdf_with_gibberish_text())


def test_vision_failure_falls_back_to_native_text(monkeypatch) -> None:
    async def fail(self, data, request):  # noqa: ANN001 - test stub
        raise OcrBackendError("OCR_BACKEND_UNAVAILABLE", "model down")

    monkeypatch.setattr(GlmOcrAdapter, "parse", fail)
    output = asyncio.run(
        HybridOcrAdapter().parse(_pdf_with_partial_text(), _request())
    )
    assert output.result.backend == "pdf_fallback"
    assert any("vision OCR unavailable" in item for item in output.result.warnings)
    assert output.result.pages
