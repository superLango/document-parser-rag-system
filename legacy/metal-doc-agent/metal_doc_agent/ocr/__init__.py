"""OCR adapter factory."""

from __future__ import annotations

from ..settings import Settings
from .base import OcrAdapter
from .glm import GlmOcrAdapter
from .mock import MockOcrAdapter


def build_ocr_adapter(settings: Settings) -> OcrAdapter:
    backend = settings.ocr_backend
    if backend == "mock":
        return MockOcrAdapter()
    if backend == "glm":
        return GlmOcrAdapter(settings)
    raise ValueError(f"unknown OCR backend: {backend}")
