from ..contracts import OcrRequest, OcrResult, Page
from .base import AdapterOutput


class TextOcrAdapter:
    """Plain markdown/text input; no model call."""

    name = "text"

    async def parse(self, data: bytes, request: OcrRequest) -> AdapterOutput:
        text = _decode(data)
        page = Page(page_no=1, markdown=text)
        return AdapterOutput(
            result=OcrResult(
                document_id=request.document_id,
                backend=self.name,
                pages=[page],
                markdown=text,
            )
        )


def _decode(data: bytes) -> str:
    for encoding in ("utf-8", "gb18030", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")
