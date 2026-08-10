"""OCR 阶段（Phase 3）：版面块裁剪 → GLM-OCR 并发识别（U11 页4×块8）。"""

from __future__ import annotations

import io
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from PIL import Image

from app.core.logging import get_logger
from app.services.ocr_backend.base import OCRBackend

from .types import BBox, LayoutBlock, RenderPage

logger = get_logger(__name__)

OCR_BLOCK_TYPES = frozenset(
    {
        "title",
        "text",
        "table",
        "formula",
        "image_caption",
        "table_caption",
        "footnote",
        "aside_text",
    }
)


def crop_block(page_image: bytes, bbox: BBox) -> bytes:
    """按归一化 bbox 裁剪页面图片块。"""
    img = Image.open(io.BytesIO(page_image)).convert("RGB")
    width, height = img.size
    box = (
        max(0, int(bbox.x0 * width)),
        max(0, int(bbox.y0 * height)),
        min(width, int(bbox.x1 * width)),
        min(height, int(bbox.y1 * height)),
    )
    if box[2] - box[0] < 2 or box[3] - box[1] < 2:
        raise ValueError("版面块裁剪区域过小")
    buf = io.BytesIO()
    img.crop(box).save(buf, format="PNG")
    return buf.getvalue()


def _ocr_one(
    backend: OCRBackend,
    page: RenderPage,
    block: LayoutBlock,
    page_sem: threading.Semaphore,
    block_sem: threading.Semaphore,
    failures: list[dict],
    lock: threading.Lock,
) -> None:
    with page_sem, block_sem:
        try:
            crop = crop_block(page.image_bytes, block.bbox)
            text = backend.ocr_block_sync(
                crop,
                block.type,
                page_index=page.page_index,
                bbox=block.bbox.as_list(),
            )
            block.content = text
            block.structural = {
                **(block.structural or {}),
                "ocr_source": "glm-ocr",
                "ocr_at": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as exc:  # noqa: BLE001 - 块级失败记录（U13）
            block.structural = {
                **(block.structural or {}),
                "ocr_failed": str(exc)[:300],
            }
            with lock:
                failures.append(
                    {
                        "page_index": page.page_index,
                        "block_type": block.type,
                        "bbox": block.bbox.as_list(),
                        "error": str(exc)[:300],
                    }
                )
            logger.warning(
                "GLM-OCR 块识别失败（U13）",
                page=page.page_index,
                block_type=block.type,
                error=str(exc)[:200],
            )


def run_ocr_stage(
    pages: list[RenderPage],
    page_layouts: list[list[LayoutBlock]],
    backend: OCRBackend,
    *,
    page_concurrency: int = 4,
    block_concurrency: int = 8,
) -> tuple[list[list[LayoutBlock]], list[dict]]:
    """对 doclayout 版面块执行 GLM-OCR；返回 (布局, 块级失败列表)。

    并发语义（U11）：页并发 page_concurrency × 页内块并发 block_concurrency。
    规则引擎产出的文本块（source=text）已含文本层内容，不重复 OCR。
    """
    failures: list[dict] = []
    lock = threading.Lock()
    page_sem = threading.Semaphore(max(1, page_concurrency))
    block_sem = threading.Semaphore(max(1, block_concurrency))
    futures = []
    workers = max(1, page_concurrency) * max(1, block_concurrency)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for page, blocks in zip(pages, page_layouts):
            for block in blocks:
                if block.source != "doclayout":
                    continue
                if block.type not in OCR_BLOCK_TYPES:
                    continue
                futures.append(
                    pool.submit(
                        _ocr_one,
                        backend,
                        page,
                        block,
                        page_sem,
                        block_sem,
                        failures,
                        lock,
                    )
                )
        for future in futures:
            future.result()
    ocr_count = sum(
        1
        for blocks in page_layouts
        for b in blocks
        if (b.structural or {}).get("ocr_source") == "glm-ocr"
    )
    logger.info(
        "OCR 阶段完成",
        blocks=ocr_count,
        failures=len(failures),
        workers=workers,
    )
    return page_layouts, failures
