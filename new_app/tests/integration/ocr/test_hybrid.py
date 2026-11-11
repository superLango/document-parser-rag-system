from __future__ import annotations

import pymupdf

from services.ocr.adapters.hybrid import has_text_layer


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


def _pdf_without_text() -> bytes:
    document = pymupdf.open()
    document.new_page()
    data = document.tobytes()
    document.close()
    return data


def test_text_layer_pdf_uses_native_backend() -> None:
    assert has_text_layer(_pdf_with_text())


def test_image_only_pdf_falls_back_to_vision_model() -> None:
    assert not has_text_layer(_pdf_without_text())
