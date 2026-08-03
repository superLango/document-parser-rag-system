"""HTML 表格清洗器（独立实现）。

功能：
- 符号规范化（≥/≤/±/℃/× 等）
- 数值修饰词转换（"不小于" → "≥"）
- rowspan/colspan 展开为独立单元格
- 移除空行
- 列数统计
- 表头提取
"""

from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup, NavigableString, Tag

logger = logging.getLogger(__name__)

# 符号规范化规则
_SYMBOL_FIXES: list[tuple[str, str]] = [
    (r"》=|》\s*=|≥", "≥"),
    (r"《=|《\s*=|≤", "≤"),
    (r"±\s*", "±"),
    (r"℃\s*", "℃"),
    (r"μ\s*m", "μm"),
    (r"°\s*C", "°C"),
    (r"\s*%\s*", "%"),
    (r"(\d+)\s*[xX×]\s*(\d+)", r"\1×\2"),
    (r"(\d+)\s*[-~～]\s*(\d+)", r"\1~\2"),
]

# 数值修饰词转换规则
_MODIFIERS: list[tuple[str, str]] = [
    (r"不小于\s*", "≥"),
    (r"不大于\s*", "≤"),
    (r"大于等于\s*", "≥"),
    (r"小于等于\s*", "≤"),
    (r"大于\s*", ">"),
    (r"小于\s*", "<"),
    (r"不低于\s*", "≥"),
    (r"不超过\s*", "≤"),
    (r"约\s*", "≈"),
]


class TableCleaner:
    """HTML 表格清洗器。

    提供表格清洗、列数统计、表头提取等功能，
    供 ``reconstruction_service`` 和 ``chunker`` 使用。
    """

    @staticmethod
    def is_table(content: str) -> bool:
        """判断内容是否为 HTML 表格。"""
        return bool(content) and "<table" in content.lower()

    @staticmethod
    def clean(html: str) -> str:
        """清洗 HTML 表格。

        流程：符号规范化 → 修饰词转换 → rowspan/colspan 展开 → 移除空行。

        Args:
            html: 原始 HTML 表格字符串。

        Returns:
            清洗后的 HTML 表格字符串。非表格内容原样返回。
        """
        if not TableCleaner.is_table(html):
            return html

        soup = BeautifulSoup(html, "html.parser")
        for table in soup.find_all("table"):
            TableCleaner._clean_cell_contents(table)
            TableCleaner._expand_rowspan_colspan(table)
            TableCleaner._remove_empty_rows(table)
        return str(soup)

    @staticmethod
    def count_columns(html: str) -> int:
        """统计表格最大列数（考虑 colspan）。"""
        if not TableCleaner.is_table(html):
            return 0
        soup = BeautifulSoup(html, "html.parser")
        table = soup.find("table")
        if not table:
            return 0
        rows = table.find_all("tr")
        max_cols = 0
        for row in rows:
            cols_count = sum(
                int(cell.get("colspan", 1)) for cell in row.find_all(["td", "th"])
            )
            max_cols = max(max_cols, cols_count)
        return max_cols

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    @staticmethod
    def _clean_cell_contents(table: Tag) -> None:
        """清洗表格内所有单元格的文本内容。"""
        for cell in table.find_all(["td", "th"]):
            text = cell.get_text(strip=True)
            if not text:
                continue
            # 符号规范化
            for pattern, replacement in _SYMBOL_FIXES:
                text = re.sub(pattern, replacement, text)
            # 数值修饰词转换
            text = TableCleaner._convert_modifiers(text)
            # 清除多余空格
            text = re.sub(r"\s+", " ", text).strip()
            cell.string = NavigableString(text)

    @staticmethod
    def _convert_modifiers(text: str) -> str:
        """将文字修饰符转换为数学符号。"""
        for pattern, symbol in _MODIFIERS:
            if re.search(pattern, text):
                value_match = re.search(rf"{pattern}(\d+\.?\d*)", text)
                if value_match:
                    return f"{symbol}{value_match.group(1)}"
        return text

    @staticmethod
    def _expand_rowspan_colspan(table: Tag) -> None:
        """处理跨行跨列：将合并单元格展开为独立行列。"""
        rows = table.find_all("tr")
        if not rows:
            return

        max_cols = TableCleaner._get_max_cols(rows)
        if max_cols == 0:
            return

        # 构建展开后的网格
        grid: list[list[str | None]] = [
            [None for _ in range(max_cols)] for _ in range(len(rows))
        ]
        for row_idx, row in enumerate(rows):
            col_idx = 0
            for cell in row.find_all(["td", "th"]):
                while col_idx < max_cols and grid[row_idx][col_idx] is not None:
                    col_idx += 1
                if col_idx >= max_cols:
                    break
                rowspan = int(cell.get("rowspan", 1))
                colspan = int(cell.get("colspan", 1))
                cell_text = cell.get_text(strip=True)
                for r in range(row_idx, min(row_idx + rowspan, len(rows))):
                    for c in range(col_idx, min(col_idx + colspan, max_cols)):
                        grid[r][c] = cell_text
                col_idx += colspan

        # 用网格重建表格
        soup = BeautifulSoup("", "html.parser")
        table.clear()
        for row_cells in grid:
            tr = soup.new_tag("tr")
            for cell_text in row_cells:
                td = soup.new_tag("td")
                td.string = NavigableString(cell_text or "")
                tr.append(td)
            table.append(tr)

    @staticmethod
    def _get_max_cols(rows: list[Tag]) -> int:
        """计算表格最大列数（考虑 colspan）。"""
        max_cols = 0
        for row in rows:
            cols_count = sum(
                int(cell.get("colspan", 1)) for cell in row.find_all(["td", "th"])
            )
            max_cols = max(max_cols, cols_count)
        return max_cols

    @staticmethod
    def _remove_empty_rows(table: Tag) -> None:
        """删除完全为空的行。"""
        rows = table.find_all("tr")
        non_empty_rows = [
            row for row in rows if any(cell.get_text(strip=True) for cell in row.find_all(["td", "th"]))
        ]
        if non_empty_rows:
            table.clear()
            for row in non_empty_rows:
                table.append(row)


# 模块级单例
table_cleaner = TableCleaner()
