"""parsekit 异常体系。"""


class ParsekitError(Exception):
    """parsekit 解析错误基类。"""


class PdfRenderError(ParsekitError):
    """PDF 无法打开/加密/渲染。"""


class PageParseError(ParsekitError):
    """单页解析失败（U11：页面级失败可标记 partial 不中断）。"""

    def __init__(self, page_index: int, message: str) -> None:
        super().__init__(f"第 {page_index} 页解析失败：{message}")
        self.page_index = page_index


class LayoutModelUnavailable(ParsekitError):
    """版面模型权重或运行依赖缺失。"""


class OcrStageError(ParsekitError):
    """OCR 阶段失败（U13：策略 failed 时抛出）。"""


class InvalidParseOptions(ParsekitError):
    """解析参数非法。"""
