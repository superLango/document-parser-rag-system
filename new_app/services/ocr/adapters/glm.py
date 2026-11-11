import asyncio
import base64

import httpx
import pymupdf

from ..config import settings
from ..contracts import OcrRequest, OcrResult, Page
from .base import AdapterOutput, OcrBackendError

PROMPT = (
    "请识别这张标准文档页面，输出 Markdown。"
    "表格必须使用 HTML <table> 标签，保留表头与合并单元格信息。不要添加解释。"
)


class GlmOcrAdapter:
    """GLM vision OCR through an OpenAI-compatible chat completions endpoint."""

    name = "glm"

    async def parse(self, data: bytes, request: OcrRequest) -> AdapterOutput:
        if not settings.glm_ocr_base_url or not settings.glm_ocr_model:
            raise OcrBackendError(
                "OCR_BACKEND_UNAVAILABLE", "glm ocr is not configured"
            )

        pages, assets = await asyncio.to_thread(_render_pages, data, request)
        budget = min(
            settings.glm_ocr_max_document_timeout_seconds,
            max(
                settings.glm_ocr_document_timeout_seconds,
                len(pages) * settings.glm_ocr_page_budget_seconds,
            ),
        )
        try:
            async with asyncio.timeout(budget):
                async with httpx.AsyncClient(
                    timeout=settings.glm_ocr_timeout_seconds
                ) as client:
                    for page in pages:
                        image_key = page.image_key or ""
                        page.markdown = await self._ocr_image(
                            client, assets[image_key]
                        )
        except TimeoutError as exc:
            raise OcrBackendError(
                "OCR_BACKEND_TIMEOUT",
                "glm ocr exceeded the document time budget",
            ) from exc

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

    async def _ocr_image(self, client: httpx.AsyncClient, image: bytes) -> str:
        url = f"{settings.glm_ocr_base_url.rstrip('/')}/chat/completions"
        payload = {
            "model": settings.glm_ocr_model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": "data:image/png;base64,"
                                + base64.b64encode(image).decode("ascii")
                            },
                        },
                        {"type": "text", "text": PROMPT},
                    ],
                }
            ],
            "temperature": 0,
        }
        try:
            response = await client.post(url, json=payload)
        except httpx.HTTPError as exc:
            raise OcrBackendError(
                "OCR_BACKEND_UNAVAILABLE", f"glm ocr request failed: {exc}"
            ) from exc
        if response.status_code != 200:
            raise OcrBackendError(
                "OCR_BACKEND_ERROR", f"glm ocr returned {response.status_code}"
            )
        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError) as exc:
            raise OcrBackendError("OCR_BACKEND_ERROR", "unexpected glm response") from exc
        if isinstance(content, list):
            content = "".join(
                str(part.get("text", "")) for part in content if isinstance(part, dict)
            )
        return str(content)


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
