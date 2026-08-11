"""parsekit：文档解析管线（Phase 2）。

模块划分（对齐 docs/DOCUMENT_PARSING_PLAN.md §6）：
- render.py         PDF → 高清图片 + 文本层提取（PyMuPDF，DPI=200）
- header_footer.py  页眉页脚擦除（方案 A 内置，U3 择优胜出）
- layout_ppdoc.py   版面分析（PP-DocLayoutV3 唯一引擎，25 类 + 阅读顺序 head）
- reading_order.py  阅读顺序排序（V3 内置 order_seq；自研分簇逻辑已随旧引擎移除）
- assemble.py       Markdown 拼接拼装
- pipeline.py       阶段编排与产物契约（layout.json 预留 U9 字段）

当前状态：版面分析固定 PP-DocLayoutV3，真实 GLM-OCR（正文/表格/公式）识别。
"""

from .errors import (
    InvalidParseOptions,
    LayoutModelUnavailable,
    OcrStageError,
    PageParseError,
    ParsekitError,
    PdfRenderError,
)
from .pipeline import ParseOptions, ParseResult, parse_pdf

__all__ = [
    "InvalidParseOptions",
    "LayoutModelUnavailable",
    "OcrStageError",
    "PageParseError",
    "ParseOptions",
    "ParseResult",
    "ParsekitError",
    "PdfRenderError",
    "parse_pdf",
]
