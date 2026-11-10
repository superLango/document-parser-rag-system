"""PDF rasterization and block cropping for the real OCR path."""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RenderedPdfPage:
    page_no: int
    width: float
    height: float
    image_bytes: bytes
    text_blocks: tuple[tuple[tuple[float, float, float, float], str], ...] = ()


def render_pdf(path: str | Path, dpi: int = 200) -> list[RenderedPdfPage]:
    try:
        import pymupdf
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError(
            "PyMuPDF is required for PDF rasterization. Install: pip install -e \".[pdf]\""
        ) from exc

    doc = pymupdf.open(str(path))
    if doc.needs_pass:
        raise ValueError("PDF is encrypted")
    pages: list[RenderedPdfPage] = []
    for index in range(doc.page_count):
        page = doc.load_page(index)
        pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csRGB, alpha=False)
        width = float(page.rect.width) or 1.0
        height = float(page.rect.height) or 1.0
        text_blocks: list[tuple[tuple[float, float, float, float], str]] = []
        for block in page.get_text("blocks"):
            if len(block) < 5 or int(block[6] if len(block) > 6 else 0) != 0:
                continue
            text = str(block[4] or "").strip()
            if not text:
                continue
            x0, y0, x1, y1 = (float(value) for value in block[:4])
            text_blocks.append(
                (
                    (
                        max(0.0, min(1.0, x0 / width)),
                        max(0.0, min(1.0, y0 / height)),
                        max(0.0, min(1.0, x1 / width)),
                        max(0.0, min(1.0, y1 / height)),
                    ),
                    text,
                )
            )
        pages.append(
            RenderedPdfPage(
                page_no=index + 1,
                width=width,
                height=height,
                image_bytes=pix.tobytes("png"),
                text_blocks=tuple(text_blocks),
            )
        )
    return pages


def crop_block(image_bytes: bytes, bbox: tuple[float, float, float, float]) -> bytes:
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError(
            "Pillow is required for block cropping. Install: pip install -e \".[models]\""
        ) from exc

    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    width, height = image.size
    x0, y0, x1, y1 = bbox
    left = max(0, min(width - 1, int(x0 * width)))
    top = max(0, min(height - 1, int(y0 * height)))
    right = max(left + 1, min(width, int(x1 * width)))
    bottom = max(top + 1, min(height, int(y1 * height)))
    if right - left < 2 or bottom - top < 2:
        raise ValueError(f"block too small: {bbox}")
    buffer = io.BytesIO()
    image.crop((left, top, right, bottom)).save(buffer, format="PNG")
    return buffer.getvalue()
