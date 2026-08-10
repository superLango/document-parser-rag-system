"""parsekit：文档解析管线（Phase 2）。

模块划分（对齐 docs/DOCUMENT_PARSING_PLAN.md §6）：
- render.py         PDF → 高清图片 + 文本层提取（PyMuPDF，DPI=200）
- header_footer.py  页眉页脚擦除（方案 A 内置 / 方案 B 样本增强，A/B 择优）
- layout.py         版面分析（RuleLayoutEngine 兜底 / DocLayoutEngine 可插拔）
- reading_order.py  阅读顺序排序（PDF-Extract-Kit 思路）
- assemble.py       Markdown 拼接拼装
- pipeline.py       阶段编排与产物契约（layout.json 预留 U9 字段）

当前状态：Phase 2 使用文本层提取作为内容来源，真实 GLM-OCR（正文/表格/公式）
在 Phase 3 接入；DocLayout-YOLO 权重未部署时使用规则引擎并明确报错。
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
