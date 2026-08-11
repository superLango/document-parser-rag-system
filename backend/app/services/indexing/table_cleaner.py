"""表格清洗器（S2/D7，适配 GLM-OCR 输出）。

职责：
- 符号规范化（≥/≤/±/℃/×/~ 等）；
- 数值修饰词转换（"不小于"→"≥"）；
- rowspan/colspan 展开为规整矩阵（供增强器解析）；
- 空行移除、列数统计、表头提取。

与旧项目 table_cleaner.py 的关系：沿用"清洗-展开-统计"思路，
但按当前 GLM-OCR HTML 输出重写解析实现，并独立提供规整矩阵供增强器消费。
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

# 符号规范化规则（按顺序应用）
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

_MODIFIERS: list[tuple[str, str]] = [
    (r"不小于\s*", "≥"),
    (r"不大于\s*", "≤"),
    (r"大于等于\s*", "≥"),
    (r"小于等于\s*", "≤"),
    (r"不低于\s*", "≥"),
    (r"不超过\s*", "≤"),
]


class TableCleaner:
    """HTML 表格清洗与规整矩阵解析。"""

    @staticmethod
    def is_table(content: str) -> bool:
        return bool(content) and "<table" in content.lower()

    @staticmethod
    def _clean_text(text: str) -> str:
        for pattern, repl in _SYMBOL_FIXES:
            text = re.sub(pattern, repl, text)
        for pattern, repl in _MODIFIERS:
            text = re.sub(pattern, repl, text)
        return text.strip()

    @classmethod
    def clean(cls, html: str) -> str:
        """清洗 HTML：符号规范化 + 修饰词转换 + 删除全空行。"""
        if not cls.is_table(html):
            return html
        soup = BeautifulSoup(html, "html.parser")
        table = soup.find("table")
        if not table:
            return html
        for cell in table.find_all(["th", "td"]):
            for txt in cell.find_all(string=True):
                txt.replace_with(cls._clean_text(txt))
        for tr in table.find_all("tr"):
            cells = tr.find_all(["th", "td"], recursive=False)
            if cells and all(not c.get_text(strip=True) for c in cells):
                tr.decompose()
        return str(soup)

    @classmethod
    def parse_matrix(cls, html: str) -> tuple[list[str], list[list[str]]]:
        """将 HTML 表格解析为规整矩阵（展开 rowspan/colspan）。

        Returns:
            (headers, rows)：headers 为表头列表；rows 为数据行二维列表。
            解析失败返回 ([], [])。
        """
        if not cls.is_table(html):
            return [], []
        try:
            soup = BeautifulSoup(html, "html.parser")
            table = soup.find("table")
            if not table:
                return [], []
            trs = table.find_all("tr")
            if not trs:
                return [], []

            grid = cls._build_grid_with_rowspan(trs)
            grid = [r for r in grid if any(str(c).strip() for c in r)]
            if not grid:
                return [], []

            headers, data_rows = cls._extract_headers_rows(trs, grid)
            return headers, data_rows
        except (ValueError, TypeError, AttributeError, IndexError):
            return [], []

    @classmethod
    def _build_grid_with_rowspan(cls, trs: list) -> list[list[str]]:
        """构造规整矩阵，rowspan 单元格占用的后续列以空串占位。

        占用登记表 occupied[i] = 第 i 行被上方 rowspan 占用的列集合；
        写入单元格前先跳过这些列，普通单元格不会被误判为占位。
        """
        grid: list[list[str]] = []
        occupied: list[set[int]] = []
        for tr_idx, tr in enumerate(trs):
            row: list[str] = []
            cells = tr.find_all(["th", "td"], recursive=False)
            col = 0
            for cell in cells:
                rowspan = max(1, int(cell.get("rowspan", 1) or 1))
                colspan = max(1, int(cell.get("colspan", 1) or 1))
                # 跳过本行已被上方 rowspan 占用的列（只查当前行的占用登记）
                occupied_row = occupied[tr_idx] if tr_idx < len(occupied) else set()
                while col in occupied_row:
                    col += 1
                text = cls._clean_text(cell.get_text(" ", strip=True))
                for c in range(colspan):
                    while len(row) <= col + c:
                        row.append("")
                    row[col + c] = text
                # 登记后续行的占用列
                for r in range(1, rowspan):
                    while len(occupied) <= tr_idx + r:
                        occupied.append(set())
                    for c in range(colspan):
                        occupied[tr_idx + r].add(col + c)
                col += colspan
            grid.append(row)
        return grid

    @staticmethod
    def _extract_headers_rows(
        trs: list, grid: list[list[str]]
    ) -> tuple[list[str], list[list[str]]]:
        """提取表头与数据行。

        含 th 的行视为表头（可多行合并）；无任何 th 时首行即表头。
        """
        th_rows: list[list[str]] = []
        data_rows: list[list[str]] = []
        for tr, row in zip(trs, grid):
            if tr.find("th"):
                th_rows.append(row)
            elif th_rows:
                data_rows.append(row)
        if not th_rows:
            return (grid[0], grid[1:]) if grid else ([], [])
        width = max(len(r) for r in th_rows)
        headers: list[str] = []
        for i in range(width):
            parts: list[str] = []
            for r in th_rows:
                if i < len(r) and r[i]:
                    parts.append(r[i])
            headers.append(" ".join(dict.fromkeys(parts)))
        return headers, data_rows

    @staticmethod
    def count_columns(html: str) -> int:
        """统计表格最大列数（考虑 colspan）。"""
        headers, rows = TableCleaner.parse_matrix(html)
        widths = [len(headers)] + [len(r) for r in rows]
        return max(widths) if widths else 0


table_cleaner = TableCleaner()
