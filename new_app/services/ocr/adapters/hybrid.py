"""Hybrid OCR: native text layer for digital PDFs, vision model for scans."""

from __future__ import annotations

import asyncio
import re

import pymupdf

from ..contracts import OcrRequest
from .base import AdapterOutput, OcrBackendError
from .glm import GlmOcrAdapter
from .pdf import PdfOcrAdapter

MIN_TEXT_PAGE_RATIO = 0.6
MIN_CHARS_PER_PAGE = 120
MIN_CHARS_PER_PAGE_HIT = 60
MIN_ANY_TEXT_PAGE_RATIO = 0.25
MIN_ANY_CHARS_PER_PAGE = 40
MIN_READABLE_PAGE_RATIO = 0.6
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_LETTER_RE = re.compile(r"[A-Za-z]")
_PUNCT_RE = re.compile(r"[^\w\s\u4e00-\u9fff]")


class HybridOcrAdapter:
    """Select the cheapest backend that can read the document.

    Text-layer PDFs are rendered and parsed natively (seconds); scanned pages
    fall back to the GLM vision model. If the vision model is unavailable, a
    low-confidence native extraction is used instead of failing the run.
    """

    name = "hybrid"

    async def parse(self, data: bytes, request: OcrRequest) -> AdapterOutput:
        if await asyncio.to_thread(has_text_layer, data):
            return await PdfOcrAdapter().parse(data, request)
        try:
            return await GlmOcrAdapter().parse(data, request)
        except OcrBackendError as exc:
            if not await asyncio.to_thread(has_any_text, data):
                raise
            output = await PdfOcrAdapter().parse(data, request)
            output.result.backend = "pdf_fallback"
            output.result.warnings.append(f"vision OCR unavailable: {exc.code}")
            return output


def _readable(text: str) -> bool:
    compact = re.sub(r"\s+", "", text)
    if len(compact) < 40:
        return False
    cjk = len(_CJK_RE.findall(text))
    if cjk / len(compact) >= 0.15:
        return True
    letters = len(_LETTER_RE.findall(text))
    spaces = text.count(" ")
    punct = len(_PUNCT_RE.findall(text))
    return (
        letters / len(compact) >= 0.5
        and spaces >= 5
        and punct / len(compact) <= 0.2
    )


def _text_stats(data: bytes) -> tuple[int, int, int, int]:
    document = pymupdf.open(stream=data, filetype="pdf")
    try:
        pages = list(document)
        if not pages:
            return 0, 0, 0, 0
        text_pages = 0
        readable_pages = 0
        total_chars = 0
        for page in pages:
            text = page.get_text("text").strip()
            total_chars += len(text)
            if len(text) >= MIN_CHARS_PER_PAGE_HIT:
                text_pages += 1
            if _readable(text):
                readable_pages += 1
        return len(pages), text_pages, total_chars, readable_pages
    finally:
        document.close()


def has_text_layer(data: bytes) -> bool:
    try:
        pages, text_pages, total_chars, readable_pages = _text_stats(data)
    except Exception:
        return False
    if not pages:
        return False
    return (
        text_pages / pages >= MIN_TEXT_PAGE_RATIO
        and total_chars / pages >= MIN_CHARS_PER_PAGE
        and readable_pages / pages >= MIN_READABLE_PAGE_RATIO
    )


def has_any_text(data: bytes) -> bool:
    try:
        pages, text_pages, total_chars, readable_pages = _text_stats(data)
    except Exception:
        return False
    if not pages:
        return False
    return (
        text_pages / pages >= MIN_ANY_TEXT_PAGE_RATIO
        and total_chars / pages >= MIN_ANY_CHARS_PER_PAGE
        and readable_pages / pages >= MIN_ANY_TEXT_PAGE_RATIO
    )
