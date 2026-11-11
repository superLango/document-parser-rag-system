import base64

import httpx

from ..contracts import LayoutBlock
from .base import OcrBackendError


class LayoutClient:
    """Client for the PP-DocLayoutV3 HTTP service (port 9978)."""

    def __init__(self, base_url: str, timeout: float = 60.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def analyze(
        self,
        *,
        page_no: int,
        width: float,
        height: float,
        dpi: int,
        image: bytes,
    ) -> tuple[list[LayoutBlock], list[dict], dict]:
        payload = {
            "page_index": page_no,
            "width": width or None,
            "height": height or None,
            "dpi": dpi or 200,
            "image_base64": base64.b64encode(image).decode("ascii"),
        }
        url = f"{self.base_url}/v1/layout"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json=payload)
        except httpx.HTTPError as exc:
            raise OcrBackendError(
                "OCR_LAYOUT_UNAVAILABLE", f"layout request failed: {exc}"
            ) from exc
        if response.status_code != 200:
            raise OcrBackendError(
                "OCR_LAYOUT_ERROR", f"layout returned {response.status_code}"
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise OcrBackendError("OCR_LAYOUT_ERROR", "unexpected layout response") from exc

        blocks = [
            LayoutBlock(
                block_id=f"P{page_no}-B{index}",
                page_no=page_no,
                type=str(item.get("type") or ""),
                bbox=[float(value) for value in item.get("bbox") or []],
            )
            for index, item in enumerate(data.get("blocks") or [], start=1)
        ]
        return blocks, list(data.get("page_failures") or []), data
