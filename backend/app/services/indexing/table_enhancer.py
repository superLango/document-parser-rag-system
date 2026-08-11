"""表格内容增强器（S2/D7）。

将 GLM-OCR 输出的 HTML 表格转换为自然语言增强文本，前置到
content_for_embedding，使 content_vector 捕获表格数据语义（数值型查询可召回）。

与旧项目 table_enhancer.py 的关系：沿用"概述 + 逐行 + 列统计"三类增强思路，
但解析直接消费 table_cleaner.parse_matrix 的规整矩阵（rowspan/colspan 已展开），
增强文本仅由分块器写入 content_for_embedding，原始 HTML 始终保留在 content。
"""

from __future__ import annotations

import re

from app.core.logging import get_logger

from .table_cleaner import table_cleaner

logger = get_logger(__name__)

# 数值提取正则（支持小数、负数、范围、≥/≤ 符号）
_NUMERIC_PATTERN = re.compile(r"[-+]?\d*\.?\d+")

# 增强文本行数上限（防止超大表格拖垮嵌入文本）
_MAX_DESCRIBE_ROWS = 15


class TableContentEnhancer:
    """表格内容增强器：概述 + 逐行键值对 + 数值列统计。"""

    def enhance(self, table_content: str, caption: str = "") -> str:
        """生成表格增强文本。

        Args:
            table_content: 表格内容（HTML）。
            caption: 表格题注（如 "表3 化学成分"）。

        Returns:
            增强文本（多行自然语言描述）；解析失败返回空字符串。
        """
        if not table_content or not table_content.strip():
            return ""
        headers, rows = table_cleaner.parse_matrix(table_content)
        if not headers or not rows:
            return ""

        parts: list[str] = []
        overview = self._create_overview(headers, rows, caption)
        if overview:
            parts.append(overview)
        for row_idx, row_data in enumerate(rows[:_MAX_DESCRIBE_ROWS]):
            row_text = self._describe_row(headers, row_data, row_idx)
            if row_text:
                parts.append(row_text)
        parts.extend(self._summarize_numeric_columns(headers, rows))
        # overview 必然生成（headers/rows 非空），parts 不可能为空
        return "\n".join(parts)

    @staticmethod
    def _create_overview(headers: list[str], rows: list[list[str]], caption: str) -> str:
        """表格概述：行数/列数/类型/题注/表头。"""
        table_type = TableContentEnhancer._detect_table_type(headers)
        parts = [f"表格包含{len(rows)}行{len(headers)}列，主要展示{table_type}。"]
        if caption:
            parts.append(f"题注：{caption}。")
        parts.append(f"表头包括：{', '.join(h for h in headers if h)[:200]}。")
        return "".join(parts)

    @staticmethod
    def _describe_row(headers: list[str], row_data: list[str], row_idx: int) -> str:
        """将一行数据转为键值对自然语言描述（跳过空单元格）。"""
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
        """对数值列生成最小/最大/平均统计。"""
        summaries: list[str] = []
        if not rows:
            return summaries
        for col_idx in self._detect_numeric_columns(headers, rows):
            col_name = headers[col_idx] if col_idx < len(headers) and headers[col_idx] else f"第{col_idx + 1}列"
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

    @staticmethod
    def _detect_table_type(headers: list[str]) -> str:
        """根据表头检测表格类型（标准文档高频场景）。"""
        headers_text = " ".join(headers)
        if any(k in headers_text for k in ["化学成分", "元素", "C", "Si", "Mn", "P", "S"]):
            return "化学成分"
        if any(k in headers_text for k in ["拉伸", "力学性能", "抗拉强度", "伸长率", "屈服"]):
            return "力学性能"
        if any(k in headers_text for k in ["组织", "金相"]):
            return "组织分析"
        if any(k in headers_text for k in ["热处理", "温度", "淬火", "回火"]):
            return "热处理制度"
        return "数据"

    @classmethod
    def _detect_numeric_columns(
        cls, headers: list[str], rows: list[list[str]]
    ) -> list[int]:
        """检测数值列：该列 50% 以上单元格含数值。"""
        if not rows:
            return []
        numeric_cols: list[int] = []
        width = min(len(headers), max(len(r) for r in rows))
        for col_idx in range(width):
            numeric_count = sum(
                1 for row_data in rows
                if col_idx < len(row_data)
                and cls._extract_numeric(row_data[col_idx]) is not None
            )
            if numeric_count >= len(rows) * 0.5:
                numeric_cols.append(col_idx)
        return numeric_cols

    @staticmethod
    def _extract_numeric(text: str) -> float | None:
        """从文本中提取首个数值。"""
        if not text:
            return None
        match = _NUMERIC_PATTERN.search(text)
        if match:
            try:
                return float(match.group())
            except ValueError:  # pragma: no cover - Python 3.13 float 对数字串宽容解析，防御保留
                return None
        return None


table_enhancer = TableContentEnhancer()
