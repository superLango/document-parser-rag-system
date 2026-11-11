"""Hybrid OCR: native text layer for digital PDFs, vision model for scans."""

from __future__ import annotations

import asyncio

import pymupdf

from ..contracts import OcrRequest
from .base import AdapterOutput
from .glm import GlmOcrAdapter
from .pdf import PdfOcrAdapter

MIN_TEXT_PAGE_RATIO = 0.6
MIN_CHARS_PER_PAGE = 120
MIN_CHARS_PER_PAGE_HIT = 60


class HybridOcrAdapter:
    """Select the cheapest backend that can read the document.

    Text-layer PDFs are rendered and parsed natively (seconds); scanned pages
    fall back to the GLM vision model. This keeps the model server off the
    critical path for the large share of digital standards.
    """

    name = "hybrid"

    async def parse(self, data: bytes, request: OcrRequest) -> AdapterOutput:
        if await asyncio.to_thread(has_text_layer, data):
            return await PdfOcrAdapter().parse(data, request)
        return await GlmOcrAdapter().parse(data, request)


def has_text_layer(data: bytes) -> bool:
    try:
        document = pymupdf.open(stream=data, filetype="pdf")
    except Exception:
        return False
    try:
        pages = list(document)
        if not pages:
            return False
        text_pages = 0
        total_chars = 0
        for page in pages:
            text = page.get_text("text").strip()
            total_chars += len(text)
            if len(text) >= MIN_CHARS_PER_PAGE_HIT:
                text_pages += 1
        return (
            text_pages / len(pages) >= MIN_TEXT_PAGE_RATIO
            and total_chars / len(pages) >= MIN_CHARS_PER_PAGE
        )
    finally:
        document.close()
