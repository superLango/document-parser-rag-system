from pathlib import Path

from ..config import settings
from .base import OcrBackendError, OcrPort
from .glm import GlmOcrAdapter
from .hybrid import HybridOcrAdapter
from .layout_first import LayoutFirstOcrAdapter
from .mock import MockOcrAdapter
from .pdf import PdfOcrAdapter
from .text import TextOcrAdapter

TEXT_SUFFIXES = {".md", ".markdown", ".txt"}


def build_adapter(backend: str | None, filename: str) -> OcrPort:
    name = (backend or settings.ocr_backend or "auto").lower()
    suffix = Path(filename).suffix.lower()
    if settings.ocr_layout_first and suffix == ".pdf" and name in {"auto", "pdf", "glm"}:
        return LayoutFirstOcrAdapter()
    if name == "auto":
        if suffix in TEXT_SUFFIXES:
            return TextOcrAdapter()
        if settings.glm_ocr_base_url and settings.glm_ocr_model:
            return HybridOcrAdapter()
        return PdfOcrAdapter()
    if name == "mock":
        return MockOcrAdapter()
    if name == "text":
        return TextOcrAdapter()
    if name == "pdf":
        return PdfOcrAdapter()
    if name == "glm":
        return GlmOcrAdapter()
    raise OcrBackendError("OCR_UNKNOWN_BACKEND", f"unknown backend: {name}")
