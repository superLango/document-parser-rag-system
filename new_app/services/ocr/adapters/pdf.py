import asyncio
from html import escape

import pymupdf

from ..config import settings
from ..contracts import OcrRequest, OcrResult, Page
from .base import AdapterOutput, OcrBackendError


class PdfOcrAdapter:
    """Native PDF path: render page images and extract text/tables without a model."""

    name = "pdf"

    async def parse(self, data: bytes, request: OcrRequest) -> AdapterOutput:
        return await asyncio.to_thread(self._parse_sync, data, request)

    def _parse_sync(self, data: bytes, request: OcrRequest) -> AdapterOutput:
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
                        markdown=_page_markdown(page),
                        image_key=image_key,
                    )
                )
        finally:
            document.close()

        if not pages:
            raise OcrBackendError("OCR_EMPTY_DOCUMENT", "pdf has no pages")

        markdown = "\n\n".join(page.markdown for page in pages if page.markdown)
        return AdapterOutput(
            result=OcrResult(
                document_id=request.document_id,
                backend=self.name,
                pages=pages,
                markdown=markdown,
            ),
            assets=assets,
        )


def _page_markdown(page) -> str:
    items: list[tuple[float, str]] = []
    for block in page.get_text("blocks"):
        if len(block) >= 7 and block[6] == 0:
            text = str(block[4]).strip()
            if text:
                items.append((float(block[1]), text))
    try:
        tables = page.find_tables()
    except Exception:
        tables = None
    if tables is not None:
        for table in tables.tables:
            html = _table_html(table)
            if html:
                items.append((float(table.bbox[1]), html))
    items.sort(key=lambda item: item[0])
    return "\n\n".join(value for _, value in items)


def _table_html(table) -> str:
    try:
        rows = table.extract()
    except Exception:
        return ""
    if not rows:
        return ""
    header_names: list[str] = []
    header = getattr(table, "header", None)
    if header is not None and getattr(header, "names", None):
        header_names = [str(name or "") for name in header.names]
    rendered = ([header_names] if header_names else []) + rows
    parts = ["<table>"]
    for row_index, row in enumerate(rendered):
        tag = "th" if header_names and row_index == 0 else "td"
        cells = "".join(f"<{tag}>{escape(str(cell or ''))}</{tag}>" for cell in row)
        parts.append(f"<tr>{cells}</tr>")
    parts.append("</table>")
    return "".join(parts)
