from ..contracts import OcrRequest, OcrResult, Page
from .base import AdapterOutput

MOCK_MARKDOWN = """# 模拟标准文档

表1 力学性能

<table>
<tr><th>牌号</th><th>抗拉强度 Rm MPa</th><th>断后伸长率 A %</th></tr>
<tr><td>Q355B</td><td>470</td><td>22</td></tr>
<tr><td>Q235B</td><td>400</td><td>26</td></tr>
</table>
"""


class MockOcrAdapter:
    name = "mock"

    async def parse(self, data: bytes, request: OcrRequest) -> AdapterOutput:
        page = Page(
            page_no=1,
            width=1000.0,
            height=1400.0,
            dpi=150,
            markdown=MOCK_MARKDOWN,
        )
        return AdapterOutput(
            result=OcrResult(
                document_id=request.document_id,
                backend=self.name,
                pages=[page],
                markdown=MOCK_MARKDOWN,
            )
        )
