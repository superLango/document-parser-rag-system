"""PDF → 页面图片 + 文本层提取（PyMuPDF，U2 DPI=200）。"""

from __future__ import annotations

import pymupdf

from app.core.logging import get_logger

from .errors import InvalidParseOptions, PdfRenderError
from .types import BBox, RenderPage, RenderResult, TextBlock

logger = get_logger(__name__)

PDF_MAGIC = b"%PDF"


def _extract_text_blocks(page: pymupdf.Page, page_index: int) -> list[TextBlock]:
    blocks: list[TextBlock] = []
    raw = page.get_text("dict")
    for item in raw.get("blocks", []):
        if item.get("type") != 0:
            continue
        x0, y0, x1, y1 = item["bbox"]
        texts: list[str] = []
        max_size = 0.0
        font_name = ""
        flags = 0
        for line in item.get("lines", []):
            for span in line.get("spans", []):
                text = (span.get("text") or "").strip()
                if not text:
                    continue
                texts.append(text)
                size = float(span.get("size") or 0)
                if size > max_size:
                    max_size = size
                    font_name = span.get("font") or ""
                    flags = int(span.get("flags") or 0)
        if not texts:
            continue
        blocks.append(
            TextBlock(
                text=" ".join(texts),
                bbox=BBox(x0, y0, x1, y1),
                font_size=max_size,
                font_name=font_name,
                flags=flags,
                page_index=page_index,
            )
        )
    return blocks


def _extract_image_boxes(page: pymupdf.Page) -> list[BBox]:
    boxes: list[BBox] = []
    for info in page.get_image_info():
        bbox = info.get("bbox")
        if bbox:
            boxes.append(BBox(*bbox))
    return boxes


def _render_page(
    doc: pymupdf.Document, index: int, dpi: int
) -> RenderPage:
    page = doc.load_page(index)
    pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csRGB, alpha=False)
    return RenderPage(
        page_index=index + 1,
        width=page.rect.width,
        height=page.rect.height,
        image_bytes=pix.tobytes("png"),
        text_blocks=_extract_text_blocks(page, index + 1),
        image_boxes=_extract_image_boxes(page),
    )


def render_pdf(
    pdf_bytes: bytes, dpi: int = 200, partial_on_page_failure: bool = False
) -> RenderResult:
    """渲染 PDF 全部页面。

    - 空内容/文件头错误/加密/损坏均抛 PdfRenderError；
    - partial_on_page_failure=True 时单页失败记录到 failures 不中断（U11）。
    """
    if not pdf_bytes:
        raise PdfRenderError("PDF 内容为空")
    if not pdf_bytes.lstrip().startswith(PDF_MAGIC):
        raise PdfRenderError("文件不是有效 PDF（缺少 %PDF 文件头）")
    if not 50 <= dpi <= 600:
        raise InvalidParseOptions(f"DPI 必须介于 50-600，当前 {dpi}")

    try:
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:
        raise PdfRenderError(f"PDF 无法打开：{exc}") from exc

    try:
        if doc.needs_pass:
            raise PdfRenderError("PDF 已加密，无法解析")
        if doc.page_count <= 0:
            raise PdfRenderError("PDF 无有效页面")

        pages: list[RenderPage] = []
        failures: list[dict] = []
        for idx in range(doc.page_count):
            try:
                pages.append(_render_page(doc, idx, dpi))
            except Exception as exc:
                failures.append(
                    {
                        "page_index": idx + 1,
                        "stage": "rendering",
                        "error": str(exc)[:300],
                    }
                )
                if not partial_on_page_failure:
                    raise PdfRenderError(
                        f"第 {idx + 1} 页渲染失败：{exc}"
                    ) from exc

        if not pages:
            raise PdfRenderError("所有页面渲染失败")
        logger.info(
            "PDF 渲染完成",
            pages=len(pages),
            failures=len(failures),
            dpi=dpi,
        )
        return RenderResult(pages=pages, failures=failures)
    except PdfRenderError:
        raise
    except Exception as exc:
        raise PdfRenderError(f"PDF 渲染失败：{exc}") from exc
    finally:
        doc.close()
