"""Document preview helpers: page list, page images and layout blocks.

The OCR pipeline writes ``pages.json``, ``pages/page-XXXX.png`` and
``pages/layout-XXXX.json`` into the job output directory. This module keeps the
platform API independent from artifact layout details.
"""

from __future__ import annotations

import json
from pathlib import Path


def build_preview(out_dir: str | Path, doc_id: str = "") -> dict:
    root = Path(out_dir).resolve()
    pages_path = root / "pages.json"
    if not pages_path.exists():
        raise FileNotFoundError(f"pages.json missing under {root}")
    pages = json.loads(pages_path.read_text(encoding="utf-8"))
    items: list[dict] = []
    for index, page in enumerate(pages, start=1):
        page_no = int(page.get("page_no") or index)
        items.append(
            {
                "page_no": page_no,
                "markdown": page.get("markdown") or "",
                "image": _relative_image(root, page.get("image_path"), page_no),
                "layout": _relative_layout(root, page_no),
            }
        )
    return {"doc_id": doc_id, "page_count": len(items), "pages": items}


def load_layout(out_dir: str | Path, page_no: int) -> dict:
    root = Path(out_dir).resolve()
    path = root / "pages" / f"layout-{page_no:04d}.json"
    if not path.exists():
        raise FileNotFoundError(f"layout missing for page {page_no}")
    data = json.loads(path.read_text(encoding="utf-8"))
    width = data.get("width")
    height = data.get("height")
    for block in data.get("blocks", []):
        block["bbox"] = normalize_bbox(block.get("bbox"), width, height)
    return data


def page_image_path(out_dir: str | Path, page_no: int) -> Path | None:
    root = Path(out_dir).resolve()
    for candidate in (
        root / "pages" / f"page-{page_no:04d}.png",
        root / "pages" / f"page-{page_no}.png",
    ):
        if candidate.exists():
            return candidate
    return None


def normalize_bbox(
    bbox: object, width: float | None, height: float | None
) -> list[float]:
    """Normalize a bbox to 0..1; the layout service normally returns 0..1."""

    try:
        x1, y1, x2, y2 = [float(value) for value in bbox]  # type: ignore[union-attr]
    except (TypeError, ValueError):
        return [0.0, 0.0, 0.0, 0.0]
    if max(x1, y1, x2, y2) <= 1.5:
        return [x1, y1, x2, y2]
    if width and height and width > 1 and height > 1:
        return [
            min(1.0, max(0.0, x1 / width)),
            min(1.0, max(0.0, y1 / height)),
            min(1.0, max(0.0, x2 / width)),
            min(1.0, max(0.0, y2 / height)),
        ]
    peak = max(x1, y1, x2, y2)
    if peak > 0:
        return [x1 / peak, y1 / peak, x2 / peak, y2 / peak]
    return [0.0, 0.0, 0.0, 0.0]


def _relative_image(root: Path, value: object, page_no: int) -> str | None:
    relative = _safe_relative(root, value)
    if relative is not None:
        return relative
    fallback = page_image_path(root, page_no)
    if fallback is None:
        return None
    return fallback.relative_to(root).as_posix()


def _relative_layout(root: Path, page_no: int) -> str | None:
    path = root / "pages" / f"layout-{page_no:04d}.json"
    if not path.exists():
        return None
    return path.relative_to(root).as_posix()


def _safe_relative(root: Path, value: object) -> str | None:
    if not value:
        return None
    path = Path(str(value))
    if not path.is_absolute():
        path = root / path
    try:
        relative = path.resolve().relative_to(root)
    except ValueError:
        return None
    return relative.as_posix() if path.exists() else None
