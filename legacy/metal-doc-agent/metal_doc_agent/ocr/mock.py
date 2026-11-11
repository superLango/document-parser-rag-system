"""Mock OCR adapter.

Consumes an existing OCR-produced markdown file and splits it by ``# Page N``
markers. This is the default backend for laptop development.
"""

from __future__ import annotations

from pathlib import Path

from ..contracts import Page
from ..ingest import split_pages


class MockOcrAdapter:
    name = "mock"

    def recognize(self, path: Path, out_dir: Path | None = None) -> list[Page]:
        text = Path(path).read_text(encoding="utf-8", errors="ignore")
        return split_pages(text)
