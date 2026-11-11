"""OCR adapter interface."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from ..contracts import Page


class OcrAdapter(Protocol):
    name: str

    def recognize(self, path: Path, out_dir: Path | None = None) -> list[Page]:
        """Return page-level markdown for a document."""
        ...
