"""Layout-first OCR: layout blocks drive text/table OCR.

This is the Phase-0 PoC path.  The layout service returns block boxes; text
blocks reuse the PDF text layer when it is readable, table blocks are cropped
and sent to GLM-OCR, and unreadable blocks are sent to GLM-OCR individually.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import unicodedata
from collections import Counter
from html import escape

import pymupdf

from ..algorithms.text_tables import build_table
from ..config import settings
from ..contracts import OcrRequest, OcrResult, Page
from .base import AdapterOutput, OcrBackendError
from .glm import PROMPT as GLM_PROMPT
from .glm import GlmOcrAdapter
from .layout import LayoutClient

logger = logging.getLogger(__name__)

TABLE_PROMPT = (
    "识别这个表格块，只输出 HTML <table>。保留表头、单位、合并单元格；"
    "不要输出解释或 Markdown 代码块。"
)
TEXT_BLOCK_TYPES = {
    "title",
    "text",
    "image_caption",
    "table_caption",
    "footnote",
    "aside_text",
}
TABLE_BLOCK_TYPES = {"table"}
OCR_BLOCK_TYPES = TEXT_BLOCK_TYPES | TABLE_BLOCK_TYPES | {"formula"}

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
# 常见汉字。字体编码损坏的 PDF 文本层会整页都是生僻字（如“犐犆犛”），
# 常用字比例接近 0，而真实中文标准一页通常超过 8%。
_COMMON_CJK = set(
    "的与和及或按应在不为中上下本标准试验方法规定要求材料性能表试样温度时间等图附录第条款规范"
)


def _looks_garbled(text: str) -> bool:
    """Detect a broken text layer or a broken font cmap on one page.

    Two failure modes are common in Chinese standards:

    * rare CJK glyphs only (``犐犆犛``) because the cmap is wrong;
    * ASCII/punctuation noise with control characters (``!"#$%&``) because the
      PDF has no usable Unicode mapping at all.
    """
    text = str(text or "")
    if len(text.strip()) < 120:
        return False
    cjk = len(_CJK_RE.findall(text))
    common = sum(1 for char in text if char in _COMMON_CJK)
    if cjk >= 40 and common / cjk < 0.05:
        return True
    control = sum(
        1
        for char in text
        if (unicodedata.category(char) == "Cc" and char not in "\n\r\t")
        or 0xE000 <= ord(char) <= 0xF8FF
    )
    if control / len(text) > 0.01:
        return True
    if cjk == 0:
        symbols = sum(1 for char in text if unicodedata.category(char)[0] in "PS")
        if symbols / len(text) > 0.45:
            return True
    return False


def _document_garbled_pages(data: bytes) -> set[int]:
    """Return 1-based page numbers whose native text layer must not be trusted."""
    document = pymupdf.open(stream=data, filetype="pdf")
    try:
        return {
            index + 1
            for index, page in enumerate(document)
            if _looks_garbled(str(page.get_text() or ""))
        }
    finally:
        document.close()


_TR_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
_CELL_RE = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S | re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_NUMBERED_CELL_RE = re.compile(r"^\d+(?:\.\d+){1,4}\s*\S{0,6}$")


def _is_degenerate_ocr(text: str) -> bool:
    """Detect runaway repeat loops from the vision model.

    GLM-OCR occasionally turns a tall crop into dozens of invented
    sub-clauses (5.1.1 … 5.1.100) or repeats the same cell.  Such output must
    not reach table extraction.
    """
    if not text or len(text) < 200:
        return False
    rows = _TR_RE.findall(text)
    if not rows:
        return False
    cells: list[str] = []
    for row in rows:
        value = "".join(
            _TAG_RE.sub("", cell) for cell in _CELL_RE.findall(row)
        ).strip()
        if value:
            cells.append(value)
    if len(cells) < 30:
        return False
    numbered = sum(1 for value in cells if _NUMBERED_CELL_RE.match(value))
    if numbered / len(cells) >= 0.6:
        return True
    most_common = Counter(cells).most_common(1)[0][1]
    return most_common / len(cells) >= 0.5


class LayoutFirstOcrAdapter:
    name = "layout_first"

    async def parse(self, data: bytes, request: OcrRequest) -> AdapterOutput:
        if not settings.layout_base_url:
            return await self._fallback(data, request)
        try:
            return await self._parse_layout_first(data, request)
        except OcrBackendError as exc:
            output = await self._fallback(data, request)
            output.result.warnings.append(f"layout-first fallback: {exc.code}")
            return output

    async def _parse_layout_first(self, data: bytes, request: OcrRequest) -> AdapterOutput:
        started = time.monotonic()
        pages, assets = await asyncio.to_thread(_render_pages, data, request)
        layout = LayoutClient(settings.layout_base_url, settings.layout_timeout_seconds)
        glm = GlmOcrAdapter() if settings.glm_ocr_base_url and settings.glm_ocr_model else None
        result = OcrResult(
            document_id=request.document_id,
            backend=self.name,
            pages=pages,
        )
        layout_failures = 0
        stats = {"glm": 0}
        page_blocks: list[list] = []
        for page in pages:
            image = assets[page.image_key or ""]
            try:
                blocks, block_failures, _ = await layout.analyze(
                    page_no=page.page_no,
                    width=page.width,
                    height=page.height,
                    dpi=page.dpi,
                    image=image,
                )
            except OcrBackendError as exc:
                layout_failures += 1
                result.warnings.append(
                    f"layout page {page.page_no}: {exc.code}; page uses native text"
                )
                if layout_failures >= 2:
                    raise OcrBackendError(
                        "OCR_LAYOUT_UNAVAILABLE", "layout failed twice"
                    ) from exc
                page.markdown = _native_page_markdown(data, page.page_no)
                page_blocks.append([])
                continue
            result.layout.extend(blocks)
            if block_failures:
                result.warnings.append(
                    f"layout page {page.page_no}: {len(block_failures)} block failures"
                )
            page_blocks.append(blocks)

        # Legacy parsekit concurrency: 4 pages x 2 blocks in flight.
        page_semaphore = asyncio.Semaphore(max(1, settings.layout_page_concurrency))
        block_semaphore = asyncio.Semaphore(max(1, settings.layout_block_concurrency))
        garbled_pages = await asyncio.to_thread(_document_garbled_pages, data)
        if garbled_pages:
            result.warnings.append(
                "garbled text layer detected on page(s) "
                f"{sorted(garbled_pages)[:10]}; text blocks are sent to GLM OCR"
            )

        async def run_page(page: Page, blocks: list) -> str:
            if not blocks:
                return page.markdown or _native_page_markdown(data, page.page_no)
            try:
                async with page_semaphore:
                    async with asyncio.timeout(settings.layout_page_timeout_seconds):
                        return await self._page_markdown(
                            data,
                            page,
                            blocks,
                            glm,
                            result,
                            block_semaphore,
                            stats,
                            force_glm=page.page_no in garbled_pages,
                        )
            except TimeoutError:
                result.warnings.append(
                    f"layout page {page.page_no}: block OCR timeout; native text"
                )
                return _native_page_markdown(data, page.page_no)

        markdowns = await asyncio.gather(
            *(run_page(page, blocks) for page, blocks in zip(pages, page_blocks, strict=True))
        )
        for page, markdown in zip(pages, markdowns, strict=True):
            page.markdown = markdown
        if layout_failures == len(pages):
            raise OcrBackendError(
                "OCR_LAYOUT_UNAVAILABLE", "layout failed for every page"
            )
        result.markdown = "\n\n".join(page.markdown for page in pages if page.markdown)
        logger.info(
            "layout-first document=%s pages=%s blocks=%s glm_blocks=%s duration=%.1fs",
            request.document_id,
            len(pages),
            len(result.layout),
            stats["glm"],
            time.monotonic() - started,
        )
        return AdapterOutput(result=result, assets=assets)

    async def _page_markdown(
        self,
        data: bytes,
        page: Page,
        blocks: list,
        glm: GlmOcrAdapter | None,
        result: OcrResult,
        semaphore: asyncio.Semaphore,
        stats: dict[str, int],
        force_glm: bool = False,
    ) -> str:
        page_text = await asyncio.to_thread(_native_page_markdown, data, page.page_no)
        # A broken font cmap yields readable-looking but meaningless text; it
        # must not be preferred over OCR.
        words = (
            []
            if force_glm
            else await asyncio.to_thread(_page_words, data, page.page_no)
        )
        table_blocks = sum(1 for block in blocks if block.type in TABLE_BLOCK_TYPES)
        if table_blocks:
            result.warnings.append(
                f"layout page {page.page_no}: {table_blocks} table block(s)"
            )

        async def render_block(block) -> str:
            if block.type in TEXT_BLOCK_TYPES:
                text = _text_in_bbox(words, block.bbox)
                if text.strip() or glm is None:
                    return text
                # Text layer exists but this block's bbox lines up with nothing
                # (rotated pages, broken coordinates): OCR the crop instead of
                # silently dropping the block.
                async with semaphore:
                    stats["glm"] += 1
                    crop = await asyncio.to_thread(
                        _crop_page, data, page.page_no, block.bbox
                    )
                    return await self._ocr_block(
                        glm, crop, None,
                        label=f"page{page.page_no}:{block.type}",
                    )
            if block.type in TABLE_BLOCK_TYPES:
                if glm is not None:
                    async with semaphore:
                        stats["glm"] += 1
                        crop = await asyncio.to_thread(
                            _crop_page, data, page.page_no, block.bbox
                        )
                        return await self._ocr_block(
                            glm, crop, TABLE_PROMPT,
                            label=f"page{page.page_no}:table",
                        )
                text = await asyncio.to_thread(
                    _native_table_html, data, page.page_no, block.bbox
                )
                if not text:
                    text = _text_in_bbox(words, block.bbox)
                result.warnings.append(
                    f"table block page {page.page_no}: GLM unavailable, "
                    f"{'native table' if text.startswith('<table>') else 'text'} fallback"
                )
                return text
            if block.type in OCR_BLOCK_TYPES and glm is not None:
                async with semaphore:
                    stats["glm"] += 1
                    crop = await asyncio.to_thread(
                        _crop_page, data, page.page_no, block.bbox
                    )
                    return await self._ocr_block(
                        glm, crop, None,
                        label=f"page{page.page_no}:{block.type}",
                    )
            return ""

        texts = await asyncio.gather(*(render_block(block) for block in blocks))
        if glm is not None and any(_is_degenerate_ocr(text) for text in texts):
            # 块级裁剪图会让模型陷入重复循环；整页重识别通常能恢复。
            async with semaphore:
                stats["glm"] += 1
                page_image = await asyncio.to_thread(
                    _render_page_image, data, page.page_no
                )
                full = await self._ocr_block(
                    glm,
                    page_image,
                    GLM_PROMPT,
                    label=f"page{page.page_no}:degenerate",
                )
            if full.strip() and not _is_degenerate_ocr(full):
                result.warnings.append(
                    f"degenerate block OCR on page {page.page_no}; "
                    "full-page GLM output used"
                )
                return full
            texts = [text for text in texts if not _is_degenerate_ocr(text)]
            result.warnings.append(
                f"degenerate block OCR dropped on page {page.page_no}"
            )
        parts = [text.strip() for text in texts if text and text.strip()]
        if not parts:
            # Layout produced no readable block: keep native text as a safety net.
            return page_text
        return "\n\n".join(parts)

    async def _ocr_block(
        self,
        glm: GlmOcrAdapter,
        crop: bytes,
        prompt: str | None,
        *,
        label: str = "",
    ) -> str:
        # Legacy parity: two retries per block before giving up.
        started = time.monotonic()
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                text = await glm.ocr_block(crop, prompt=prompt)
                logger.info(
                    "block ocr %s bytes=%s attempt=%s duration=%.1fs",
                    label,
                    len(crop),
                    attempt + 1,
                    time.monotonic() - started,
                )
                return text
            except Exception as exc:  # noqa: BLE001 - one block should not fail the page
                last_error = exc
                if attempt < 2:
                    await asyncio.sleep(0.5 * (attempt + 1))
        logger.warning(
            "block OCR failed %s bytes=%s after %.1fs: %s",
            label,
            len(crop),
            time.monotonic() - started,
            last_error,
        )
        return ""

    async def _fallback(self, data: bytes, request: OcrRequest) -> AdapterOutput:
        from .hybrid import HybridOcrAdapter

        return await HybridOcrAdapter().parse(data, request)


def _render_pages(data: bytes, request: OcrRequest) -> tuple[list[Page], dict[str, bytes]]:
    try:
        document = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise OcrBackendError("OCR_PDF_INVALID", f"cannot open pdf: {exc}") from exc
    pages: list[Page] = []
    assets: dict[str, bytes] = {}
    try:
        for index, page in enumerate(document, start=1):
            pixmap = page.get_pixmap(dpi=settings.ocr_dpi)
            image_key = f"ocr/{request.document_id}/pages/{index}.png"
            assets[image_key] = pixmap.tobytes("png")
            pages.append(
                Page(
                    page_no=index,
                    width=float(page.rect.width),
                    height=float(page.rect.height),
                    dpi=settings.ocr_dpi,
                    image_key=image_key,
                )
            )
    finally:
        document.close()
    if not pages:
        raise OcrBackendError("OCR_EMPTY_DOCUMENT", "pdf has no pages")
    return pages, assets


def _page_words(data: bytes, page_no: int) -> list[tuple[float, float, float, float, str]]:
    document = pymupdf.open(stream=data, filetype="pdf")
    try:
        page = document[page_no - 1]
        width = float(page.rect.width) or 1.0
        height = float(page.rect.height) or 1.0
        words = []
        for item in page.get_text("words"):
            if len(item) < 5:
                continue
            x0, y0, x1, y1, text = item[:5]
            if not str(text).strip():
                continue
            words.append(
                (
                    max(0.0, min(1.0, float(x0) / width)),
                    max(0.0, min(1.0, float(y0) / height)),
                    max(0.0, min(1.0, float(x1) / width)),
                    max(0.0, min(1.0, float(y1) / height)),
                    str(text),
                )
            )
        return words
    finally:
        document.close()


def _text_in_bbox(
    words: list[tuple[float, float, float, float, str]], bbox: list[float]
) -> str:
    if len(bbox) < 4:
        return ""
    x0, y0, x1, y1 = bbox[:4]
    selected = []
    for wx0, wy0, wx1, wy1, text in words:
        cx = (wx0 + wx1) / 2
        cy = (wy0 + wy1) / 2
        if x0 <= cx <= x1 and y0 <= cy <= y1:
            selected.append((wy0, wx0, text))
    selected.sort(key=lambda item: (round(item[0], 2), item[1]))
    return " ".join(item[2] for item in selected).strip()


def _render_page_image(data: bytes, page_no: int, dpi: int = 220) -> bytes:
    """Render a whole page at a higher DPI for the degenerate-block retry."""
    document = pymupdf.open(stream=data, filetype="pdf")
    try:
        page = document[page_no - 1]
        return page.get_pixmap(dpi=dpi).tobytes("png")
    finally:
        document.close()


def _crop_page(data: bytes, page_no: int, bbox: list[float]) -> bytes:
    """Render a block crop directly from the PDF page (no Pillow needed)."""
    document = pymupdf.open(stream=data, filetype="pdf")
    try:
        page = document[page_no - 1]
        width = float(page.rect.width) or 1.0
        height = float(page.rect.height) or 1.0
        x0 = max(0.0, min(1.0, bbox[0])) * width
        y0 = max(0.0, min(1.0, bbox[1])) * height
        x1 = max(0.0, min(1.0, bbox[2])) * width
        y1 = max(0.0, min(1.0, bbox[3])) * height
        clip = pymupdf.Rect(x0, y0, max(x0 + 1, x1), max(y0 + 1, y1))
        return page.get_pixmap(clip=clip, dpi=settings.ocr_dpi).tobytes("png")
    finally:
        document.close()


def _native_table_html(data: bytes, page_no: int, bbox: list[float]) -> str:
    """Use a drawn table from the same page when GLM is unavailable."""
    document = pymupdf.open(stream=data, filetype="pdf")
    try:
        page = document[page_no - 1]
        width = float(page.rect.width) or 1.0
        height = float(page.rect.height) or 1.0
        try:
            tables = page.find_tables()
        except Exception:
            return ""
        for table in tables.tables:
            tx0, ty0, tx1, ty1 = (float(value) for value in table.bbox)
            nx0, ny0, nx1, ny1 = tx0 / width, ty0 / height, tx1 / width, ty1 / height
            overlap_w = max(0.0, min(nx1, bbox[2]) - max(nx0, bbox[0]))
            overlap_h = max(0.0, min(ny1, bbox[3]) - max(ny0, bbox[1]))
            area = max((bbox[2] - bbox[0]) * (bbox[3] - bbox[1]), 1e-6)
            if overlap_w * overlap_h / area < 0.3:
                continue
            rows = table.extract()
            if not rows:
                continue
            parts = ["<table>"]
            for row in rows:
                cells = "".join(
                    f"<td>{escape(str(cell or ''))}</td>" for cell in row
                )
                parts.append(f"<tr>{cells}</tr>")
            parts.append("</table>")
            return "".join(parts)
        if settings.ocr_text_table_fallback:
            recovered = build_table(_page_words(data, page_no), bbox)
            if recovered:
                return recovered.html
        return ""
    finally:
        document.close()


def _native_page_markdown(data: bytes, page_no: int) -> str:
    document = pymupdf.open(stream=data, filetype="pdf")
    try:
        return str(document[page_no - 1].get_text("text") or "").strip()
    finally:
        document.close()
