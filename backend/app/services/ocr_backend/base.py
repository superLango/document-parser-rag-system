"""OCRBackend 协议定义。"""

from __future__ import annotations

from typing import Protocol


class OCRBackend(Protocol):
    """块级 OCR 后端协议（Phase 3）。"""

    def ocr_block_sync(
        self,
        image_bytes: bytes,
        block_type: str,
        *,
        page_index: int = 0,
        bbox: list[float] | None = None,
    ) -> str:
        """识别单个裁剪图片块，返回文本/Markdown/HTML/LaTeX。"""
        ...
