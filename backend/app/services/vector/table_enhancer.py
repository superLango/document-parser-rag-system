"""表格内容增强模块（移植自 glm-ocr，用于向量入库阶段）。

将 HTML/Markdown 表格转换为三类自然语言增强文本，前置到表格 content 前，
使 content_vector 编码时捕获表格的语义信息，提升检索召回率。

三类增强文本：
1. **表格概述**：行数、列数、表头列表、表格类型
2. **逐行键值对**：每行数据转为 "字段名为X" 的自然语言描述
3. **列统计**：数值列的最小/最大/平均值

使用示例::

    from app.services.vector.table_enhancer import table_enhancer

    enhanced = table_enhancer.enhance(table_html, caption="表3 化学成分")
    # enhanced = "表格概述...\n逐行描述...\n列统计...\n\n<原始表格>"
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


class TableContentEnhancer:
    """表格内容增强器。

    将表格转换为自然语言描述文本，前置到 content 中提升向量检索召回率。
    增强文本仅作为检索信号，原始表格 HTML/Markdown 保留在 content 中供 LLM 抽取。
    """

    # 数值提取正则（支持小数、负数、范围、≥/≤ 符号）
    _NUMERIC_PATTERN = re.compile(r"[-+]?\d*\.?\d+")

    def enhance(self, table_content: str, caption: str = "") -> str:
        """生成表格增强文本。

        Args:
            table_content: 表格内容（HTML 或 Markdown 格式）。
            caption: 表格题注（如 "表3 化学成分"）。

        Returns:
            增强文本（多行自然语言描述），调用方应前置到 content 前。
            若表格解析失败，返回空字符串。
        """
        if not table_content or not table_content.strip():
            return ""

        # 尝试解析 HTML 表格
        headers, rows = self._parse_html_table(table_content)
        if not headers:
            # 尝试解析 Markdown 表格
            headers, rows = self._parse_markdown_table(table_content)
        if not headers or not rows:
            return ""

        context = {"caption": caption} if caption else None
        enhanced_parts: list[str] = []

        # 1. 表格概述
        overview = self._create_overview(headers, rows, context)
        if overview:
            enhanced_parts.append(overview)

        # 2. 逐行键值对描述（限制前 15 行，避免增强文本过长）
        for row_idx, row_data in enumerate(rows[:15]):
            row_text = self._describe_row(headers, row_data, row_idx)
            if row_text:
                enhanced_parts.append(row_text)

        # 3. 列统计（数值列）
        col_summaries = self._summarize_numeric_columns(headers, rows)
        enhanced_parts.extend(col_summaries)

        if not enhanced_parts:
            return ""

        return "\n".join(enhanced_parts)

    # ------------------------------------------------------------------
    # 表格解析
    # ------------------------------------------------------------------

    def _parse_html_table(self, content: str) -> tuple[list[str], list[list[str]]]:
        """解析 HTML 表格，返回 (表头, 数据行)。"""
        if "<table" not in content.lower():
            return [], []

        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return [], []

        try:
            soup = BeautifulSoup(content, "html.parser")
            table = soup.find("table")
            if not table:
                return [], []

            all_rows = table.find_all("tr")
            if not all_rows:
                return [], []

            # 提取表头（前 3 行中包含 th 的行）
            headers: list[str] = []
            data_rows: list[list[str]] = []

            for row_idx, tr in enumerate(all_rows):
                cells = tr.find_all(["th", "td"])
                cell_texts = [c.get_text(strip=True) for c in cells]
                if not cell_texts:
                    continue

                # 前 3 行且包含 th 视为表头
                if row_idx < 3 and tr.find("th"):
                    if not headers:
                        headers = cell_texts
                    else:
                        # 多行表头：合并到现有表头
                        for i, txt in enumerate(cell_texts):
                            if i < len(headers) and txt and txt not in headers[i]:
                                headers[i] = f"{headers[i]}-{txt}"
                else:
                    data_rows.append(cell_texts)

            # 如果没有 th，取第一行作为表头
            if not headers and data_rows:
                headers = data_rows.pop(0)

            return headers, data_rows
        except Exception as exc:
            logger.debug("HTML 表格解析失败: %s", exc)
            return [], []

    def _parse_markdown_table(self, content: str) -> tuple[list[str], list[list[str]]]:
        """解析 Markdown 表格，返回 (表头, 数据行)。"""
        lines = content.strip().split("\n")
        # Markdown 表格特征：至少 2 行，包含 | 分隔符，第二行为分隔行
        table_lines = [ln for ln in lines if "|" in ln and ln.strip()]
        if len(table_lines) < 2:
            return [], []

        # 检查第二行是否为分隔行（---|---）
        if not re.match(r"^\s*\|?[\s\-:|]+\|?\s*$", table_lines[1]):
            return [], []

        def split_row(row: str) -> list[str]:
            parts = row.strip().strip("|").split("|")
            return [p.strip() for p in parts]

        headers = split_row(table_lines[0])
        data_rows = [split_row(ln) for ln in table_lines[2:]]
        return headers, data_rows

    # ------------------------------------------------------------------
    # 增强文本生成
    # ------------------------------------------------------------------

    def _create_overview(
        self, headers: list[str], rows: list[list[str]], context: dict | None
    ) -> str:
        """生成表格概述。"""
        num_rows = len(rows)
        num_cols = len(headers)
        table_type = self._detect_table_type(headers, rows)

        parts = [f"表格包含{num_rows}行{num_cols}列，主要展示{table_type}。"]
        if context and context.get("caption"):
            parts.append(f"题注：{context['caption']}。")
        parts.append(f"表头包括：{', '.join(headers[:10])}。")
        return "".join(parts)

    def _describe_row(
        self, headers: list[str], row_data: list[str], row_idx: int
    ) -> str:
        """将一行数据转为键值对自然语言描述。"""
        key_values: list[str] = []
        for i, header in enumerate(headers):
            if i < len(row_data) and row_data[i]:
                key_values.append(f"{header}为{row_data[i]}")
        if not key_values:
            return ""
        return f"第{row_idx + 1}行数据：" + "，".join(key_values) + "。"

    def _summarize_numeric_columns(
        self, headers: list[str], rows: list[list[str]]
    ) -> list[str]:
        """对数值列生成统计摘要。"""
        summaries: list[str] = []
        if not rows:
            return summaries

        numeric_cols = self._detect_numeric_columns(headers, rows)
        for col_idx in numeric_cols:
            col_name = headers[col_idx] if col_idx < len(headers) else f"第{col_idx + 1}列"
            values: list[float] = []
            for row_data in rows:
                if col_idx < len(row_data):
                    val = self._extract_numeric(row_data[col_idx])
                    if val is not None:
                        values.append(val)
            if values:
                summaries.append(
                    f"{col_name}统计：最小值为{min(values)}，"
                    f"最大值为{max(values)}，平均值为{sum(values) / len(values):.2f}。"
                )
        return summaries

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_table_type(headers: list[str], rows: list[list[str]]) -> str:
        """根据表头检测表格类型。"""
        headers_text = " ".join(headers)
        if any(k in headers_text for k in ["化学成分", "元素", "C", "Si", "Mn"]):
            return "化学成分"
        if any(k in headers_text for k in ["拉伸", "力学性能", "抗拉强度", "伸长率"]):
            return "力学性能"
        if any(k in headers_text for k in ["组织", "金相"]):
            return "组织分析"
        if any(k in headers_text for k in ["热处理", "温度"]):
            return "热处理制度"
        return "数据"

    def _detect_numeric_columns(
        self, headers: list[str], rows: list[list[str]]
    ) -> list[int]:
        """检测哪些列是数值型（50% 以上单元格含数值）。"""
        numeric_cols: list[int] = []
        if not rows:
            return numeric_cols
        num_cols = min(len(headers), len(rows[0]))
        for col_idx in range(num_cols):
            numeric_count = sum(
                1 for row_data in rows
                if col_idx < len(row_data) and self._extract_numeric(row_data[col_idx]) is not None
            )
            if numeric_count >= len(rows) * 0.5:
                numeric_cols.append(col_idx)
        return numeric_cols

    def _extract_numeric(self, text: str) -> float | None:
        """从文本中提取首个数值。"""
        if not text:
            return None
        match = self._NUMERIC_PATTERN.search(text)
        if match:
            try:
                return float(match.group())
            except ValueError:
                return None
        return None


# 模块级单例
table_enhancer = TableContentEnhancer()
