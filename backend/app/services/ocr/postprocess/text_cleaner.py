"""OCR 文本清洗服务模块。

本模块提供可配置清洗等级的 OCR 文本清洗能力，用于在文档解析流水线中
对 GLM-OCR 输出的 markdown 文本与版面块文本进行规范化处理，
移除空段落、冗余格式标记、乱码字符等噪声，提升文本质量与下游检索精度。

支持三级清洗（``light`` / ``medium`` / ``deep``）：

1. **light**：基础清洗。移除控制字符、尾随空白，折叠连续空行。
   保留 markdown 结构标记（``#`` / ``|`` / ``-`` 等）。
2. **medium**（默认）：在 light 基础上移除纯空白段落，规范化连续换行为
   单换行，清理 Unicode 替换字符 ``\\ufffd``。保留 markdown 结构。
3. **deep**：在 medium 基础上剥离 markdown 标记转为纯文本
   （标题 ``#``、表格 ``|``、列表 ``-`` / ``*``、粗体 ``**``、斜体 ``*``），
   并移除清洗后为空的版面块（对应 bbox 不再高亮）。

使用示例：
    from app.services.ocr.postprocess.text_cleaner import text_cleaner

    cleaned = text_cleaner.clean_text("# 标题\\n正文", level="deep")
    # cleaned -> "标题\\n正文"

    layout = text_cleaner.clean_layout(layout_items, level="medium")
"""

import re

from app.core.logging import get_logger

logger = get_logger(__name__)

# 合法清洗等级
_VALID_LEVELS: tuple[str, ...] = ("light", "medium", "deep")
_DEFAULT_LEVEL: str = "medium"

# 控制字符：\x00-\x08, \x0b, \x0c, \x0e-\x1f（保留 \x09=\t, \x0a=\n, \x0d=\r）
# 不含 \x7f (DEL)，单独处理
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# Unicode 替换字符
_REPLACEMENT_CHAR_RE = re.compile(r"\ufffd")
# 连续 3 个以上换行折叠为 2 个
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")
# 行尾空白
_TRAILING_WS_RE = re.compile(r"[ \t]+$", re.MULTILINE)
# 连续空格（非换行）折叠为单空格
_MULTI_SPACE_RE = re.compile(r"[ ]{2,}")

# ---- deep 模式 markdown 标记剥离规则 ----
# 标题前缀：行首的 # 至 6 个 + 空格
_MD_HEADING_RE = re.compile(r"^[ \t]{0,3}#{1,6}[ \t]+", re.MULTILINE)
# 表格分隔行：仅含 | 、- 、: 、空格 的行（如 |---|:---|）
_MD_TABLE_SEP_RE = re.compile(
    r"^[ \t]*\|?[\s\-:|]+?\|?[ \t]*$", re.MULTILINE
)
# 表格行首尾的 |（保留单元格内容，用空格分隔）
_MD_TABLE_PIPE_RE = re.compile(r"^[ \t]*\||\|[ \t]*$", re.MULTILINE)
# 表格内部单元格分隔的 | 转为空格
_MD_TABLE_INNER_PIPE_RE = re.compile(r"\s*\|\s*")
# 列表项前缀：- / * / + 或 数字. + 空格
_MD_LIST_RE = re.compile(r"^[ \t]{0,3}(?:[-*+]|\d+\.)[ \t]+", re.MULTILINE)
# 粗体 **text** 或 __text__ -> text
_MD_BOLD_RE = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")
# 斜体 *text* 或 _text_ -> text（避免误伤粗体，放在粗体之后）
_MD_ITALIC_RE = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)|(?<!_)_(?!_)(.+?)(?<!_)_(?!_)")
# 行内代码 `code` -> code
_MD_INLINE_CODE_RE = re.compile(r"`([^`]+)`")
# 引用块前缀 >
_MD_BLOCKQUOTE_RE = re.compile(r"^[ \t]{0,3}>[ \t]?", re.MULTILINE)
# 水平分隔线 --- / ***
_MD_HR_RE = re.compile(r"^[ \t]{0,3}(?:-{3,}|\*{3,}|_{3,})[ \t]*$", re.MULTILINE)


class TextCleaner:
    """OCR 文本清洗服务，支持 ``light`` / ``medium`` / ``deep`` 三级清洗。

    所有方法均为纯函数式处理，无副作用、无状态，可安全并发调用。
    """

    @staticmethod
    def _normalize_level(level: str) -> str:
        """规范化清洗等级，非法值回退到默认 ``medium``。

        Args:
            level: 用户指定的清洗等级字符串。

        Returns:
            str: 合法清洗等级（light / medium / deep）。
        """
        if level not in _VALID_LEVELS:
            logger.warning(
                "未知清洗等级，回退到默认",
                level=level,
                default=_DEFAULT_LEVEL,
            )
            return _DEFAULT_LEVEL
        return level

    @staticmethod
    def _clean_light(text: str) -> str:
        """light 级清洗：移除控制字符、尾随空白，折叠连续空行。

        Args:
            text: 待清洗文本。

        Returns:
            str: 清洗后文本。
        """
        if not text:
            return ""
        # 移除控制字符（保留 \t \n \r）
        text = _CONTROL_CHARS_RE.sub("", text)
        # 移除 Unicode 替换字符
        text = _REPLACEMENT_CHAR_RE.sub("", text)
        # 行尾空白
        text = _TRAILING_WS_RE.sub("", text)
        # 连续 3+ 换行折叠为 2 个
        text = _MULTI_NEWLINE_RE.sub("\n\n", text)
        return text

    @staticmethod
    def _clean_medium(text: str) -> str:
        """medium 级清洗：在 light 基础上移除纯空白段落、规范化换行。

        Args:
            text: 待清洗文本。

        Returns:
            str: 清洗后文本。
        """
        text = TextCleaner._clean_light(text)
        if not text:
            return ""
        # 按段落（空行分隔）处理，移除纯空白段落
        paragraphs = text.split("\n")
        cleaned_lines: list[str] = []
        for line in paragraphs:
            stripped = line.strip()
            if stripped:
                # 段落内连续空格折叠为单空格
                cleaned_lines.append(_MULTI_SPACE_RE.sub(" ", stripped))
            else:
                cleaned_lines.append("")
        # 重新拼接，去除首尾空行
        result = "\n".join(cleaned_lines).strip("\n")
        # 再次折叠连续空行（上一步可能产生新的连续空行）
        result = _MULTI_NEWLINE_RE.sub("\n\n", result)
        return result

    @staticmethod
    def _strip_markdown(text: str) -> str:
        """剥离 markdown 标记转为纯文本（deep 级专用）。

        Args:
            text: 待剥离 markdown 的文本。

        Returns:
            str: 纯文本。
        """
        # 行内代码 -> 纯文本（先处理避免被其他规则误伤）
        text = _MD_INLINE_CODE_RE.sub(r"\1", text)
        # 水平分隔线 -> 移除
        text = _MD_HR_RE.sub("", text)
        # 引用块前缀 -> 移除
        text = _MD_BLOCKQUOTE_RE.sub("", text)
        # 标题前缀 -> 移除
        text = _MD_HEADING_RE.sub("", text)
        # 表格分隔行 -> 移除
        text = _MD_TABLE_SEP_RE.sub("", text)
        # 表格行首尾 | -> 移除
        text = _MD_TABLE_PIPE_RE.sub("", text)
        # 表格内部 | -> 空格
        text = _MD_TABLE_INNER_PIPE_RE.sub(" ", text)
        # 列表项前缀 -> 移除
        text = _MD_LIST_RE.sub("", text)
        # 粗体 -> 纯文本
        text = _MD_BOLD_RE.sub(lambda m: m.group(1) or m.group(2) or "", text)
        # 斜体 -> 纯文本
        text = _MD_ITALIC_RE.sub(
            lambda m: m.group(1) or m.group(2) or "", text
        )
        return text

    @staticmethod
    def _clean_deep(text: str) -> str:
        """deep 级清洗：在 medium 基础上剥离 markdown 标记转纯文本。

        Args:
            text: 待清洗文本。

        Returns:
            str: 纯文本。
        """
        text = TextCleaner._strip_markdown(text)
        # 剥离后再做一次 medium 清理（去除剥离产生的空行/空白）
        return TextCleaner._clean_medium(text)

    def clean_text(self, text: str, level: str = _DEFAULT_LEVEL) -> str:
        """清洗全文文本。

        Args:
            text: 待清洗的 OCR 全文文本（通常为 markdown 形式）。
            level: 清洗等级，可选 ``light`` / ``medium`` / ``deep``，
                默认 ``medium``。

        Returns:
            str: 清洗后的文本。输入为空时返回空字符串。
        """
        if not text:
            return ""
        norm_level = self._normalize_level(level)
        if norm_level == "light":
            cleaned = self._clean_light(text)
        elif norm_level == "deep":
            cleaned = self._clean_deep(text)
        else:
            cleaned = self._clean_medium(text)
        return cleaned

    def clean_layout(
        self,
        layout: list[dict],
        level: str = _DEFAULT_LEVEL,
    ) -> list[dict]:
        """清洗版面块列表的文本，并移除空文本块。

        对每个版面块的 ``text`` 字段执行 ``clean_text``。
        ``deep`` 模式下移除清洗后 text 为空且 type 为 text/title 的块
        （保留 table/figure 块以维持版面结构完整性）。

        Args:
            layout: 版面块列表，每项含 ``type`` / ``bbox`` / ``text`` 等字段。
            level: 清洗等级，默认 ``medium``。

        Returns:
            list[dict]: 清洗后的版面块列表，顺序与输入一致。
        """
        if not layout:
            return []
        norm_level = self._normalize_level(level)
        cleaned_layout: list[dict] = []
        removed_count = 0
        for item in layout:
            # 复制避免修改原对象
            cleaned_item = dict(item)
            raw_text = cleaned_item.get("text", "") or ""
            cleaned_text = self.clean_text(raw_text, norm_level)
            cleaned_item["text"] = cleaned_text
            # deep 模式：移除空文本的 text/title 块（table/figure 保留）
            if (
                norm_level == "deep"
                and not cleaned_text
                and cleaned_item.get("type") in ("text", "title")
            ):
                removed_count += 1
                continue
            cleaned_layout.append(cleaned_item)
        if removed_count > 0:
            logger.info(
                "版面块清洗完成",
                level=norm_level,
                input_count=len(layout),
                output_count=len(cleaned_layout),
                removed_empty=removed_count,
            )
        return cleaned_layout


# 模块级单例
text_cleaner = TextCleaner()
