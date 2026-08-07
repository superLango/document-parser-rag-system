"""表格边界感知分批处理器（glmocr 线路用）。

将长上下文文本按表格边界切分为多个批次，避免表格被截断。

分批策略：
1. 短文本（< threshold=8000 字符）→ 单批返回
2. 检测 ``<table>...</table>`` 完整块，表格不跨批切分
3. 单大表（> batch_chars=6000 字符）按行切分，每批保留原表头作为前缀
4. 批间保留 500 字符重叠（共指消解）
5. 批次间串行执行（牌号传递依赖）

使用示例::

    from app.services.extraction.llm_extract.batch_processor import batch_processor

    batches = batch_processor.split(text, threshold=8000)
"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.core.logging import get_logger
from app.core.exceptions import BusinessException

logger = get_logger(__name__)

# 表格 HTML 标签正则（匹配 <table>...</table>）
_TABLE_PATTERN = re.compile(r"<table[^>]*>.*?</table>", re.DOTALL | re.IGNORECASE)

# Markdown 表格行正则（以 | 开头）
_MD_TABLE_ROW_PATTERN = re.compile(r"^\|.*\|\s*$", re.MULTILINE)

# HTML 表格行正则（<tr>...</tr>）
_TR_PATTERN = re.compile(r"<tr[^>]*>.*?</tr>", re.DOTALL | re.IGNORECASE)

# HTML 表头正则（<thead>...</thead> 或前几个 <th>）
_THEAD_PATTERN = re.compile(r"<thead[^>]*>.*?</thead>", re.DOTALL | re.IGNORECASE)
_TH_PATTERN = re.compile(r"<th[^>]*>.*?</th>", re.DOTALL | re.IGNORECASE)


class BatchProcessor:
    """表格边界感知分批处理器。

    将长文本按表格边界切分为多个批次，确保表格完整性。
    """

    def __init__(self) -> None:
        pass

    def split(
        self,
        text: str,
        threshold: int | None = None,
        batch_chars: int | None = None,
        overlap: int | None = None,
    ) -> list[str]:
        """将长文本分批（表格边界感知）。

        Args:
            text: 待分批的文本。
            threshold: 长文本阈值，None 时使用配置项（默认 8000）。
            batch_chars: 单批字符上限，None 时使用配置项（默认 6000）。
            overlap: 批间重叠字符数，None 时使用配置项（默认 500）。

        Returns:
            list[str]: 批次列表。短文本返回单批。
        """
        # 分批参数由调用方从配置解析传入（BaseExtract batch 参数），缺失即报错
        if threshold is None:
            raise BusinessException("未配置 BaseExtract 批处理参数 batch.single_threshold")
        if batch_chars is None:
            raise BusinessException("未配置 BaseExtract 批处理参数 batch.batch_chars")
        if overlap is None:
            raise BusinessException("未配置 BaseExtract 批处理参数 batch.overlap")
        _threshold = threshold
        _batch_chars = batch_chars
        _overlap = overlap

        if not text or len(text) <= _threshold:
            return [text] if text else []

        # 表格边界感知切分
        segments = self._split_by_table_boundaries(text)

        # 将 segments 合并为批次（每批不超过 batch_chars）
        batches: list[str] = []
        current_batch: list[str] = []
        current_size = 0

        for segment in segments:
            seg_len = len(segment)

            # 单个大表（超过 batch_chars）：按行切分
            if seg_len > _batch_chars and self._is_table_segment(segment):
                # 先保存当前批次
                if current_batch:
                    batches.append("\n\n".join(current_batch))
                    current_batch = []
                    current_size = 0

                # 大表按行切分
                table_batches = self._split_large_table(segment, _batch_chars, _overlap)
                batches.extend(table_batches)
            elif current_size + seg_len > _batch_chars and current_batch:
                # 当前批次已满，保存并开始新批次
                batches.append("\n\n".join(current_batch))
                current_batch = [segment]
                current_size = seg_len
            else:
                current_batch.append(segment)
                current_size += seg_len

        # 保存最后一批
        if current_batch:
            batches.append("\n\n".join(current_batch))

        # 添加批间重叠
        if _overlap > 0 and len(batches) > 1:
            batches = self._add_overlap(batches, _overlap)

        logger.info(
            "分批完成",
            extra={
                "text_len": len(text),
                "batch_count": len(batches),
                "threshold": _threshold,
                "batch_chars": _batch_chars,
            },
        )
        return batches

    @staticmethod
    def _split_by_table_boundaries(text: str) -> list[str]:
        """按表格边界切分文本。

        将文本中的 ``<table>...</table>`` 块作为独立段落，
        非表格文本按段落分割。

        Args:
            text: 原始文本。

        Returns:
            list[str]: 切分后的段落列表（表格和非表格交替）。
        """
        segments: list[str] = []
        last_end = 0

        for match in _TABLE_PATTERN.finditer(text):
            # 表格前的非表格文本
            if match.start() > last_end:
                pre_text = text[last_end:match.start()].strip()
                if pre_text:
                    segments.extend(pre_text.split("\n\n"))

            # 表格本身
            segments.append(match.group(0))
            last_end = match.end()

        # 末尾的非表格文本
        if last_end < len(text):
            post_text = text[last_end:].strip()
            if post_text:
                segments.extend(post_text.split("\n\n"))

        return [s for s in segments if s]

    @staticmethod
    def _is_table_segment(segment: str) -> bool:
        """判断段落是否为表格。

        Args:
            segment: 文本段落。

        Returns:
            bool: 是否为表格段落。
        """
        return segment.strip().lower().startswith("<table")

    def _split_large_table(
        self,
        table_html: str,
        batch_chars: int,
        overlap: int,
    ) -> list[str]:
        """按行切分大表格，每批保留表头。

        Args:
            table_html: 表格 HTML 字符串。
            batch_chars: 每批字符上限。
            overlap: 重叠字符数（表格切分时不用重叠，用表头前置）。

        Returns:
            list[str]: 切分后的表格批次列表。
        """
        # 提取表头
        header = self._extract_table_header(table_html)

        # 提取所有行
        rows = _TR_PATTERN.findall(table_html)
        if not rows:
            return [table_html]

        # 区分表头行和数据行
        header_rows: list[str] = []
        data_rows: list[str] = []
        for row in rows:
            if _TH_PATTERN.search(row):
                header_rows.append(row)
            else:
                data_rows.append(row)

        if not data_rows:
            return [table_html]

        # 按字符上限切分数据行
        batches: list[str] = []
        current_rows: list[str] = []
        current_size = len(header) if header else 0

        for row in data_rows:
            row_size = len(row) + 5  # 加上换行和标签开销
            if current_size + row_size > batch_chars and current_rows:
                # 当前批次已满，生成完整表格
                table_batch = self._build_table(header, header_rows, current_rows)
                batches.append(table_batch)
                current_rows = []
                current_size = len(header) if header else 0
            current_rows.append(row)
            current_size += row_size

        # 保存最后一批
        if current_rows:
            table_batch = self._build_table(header, header_rows, current_rows)
            batches.append(table_batch)

        return batches

    @staticmethod
    def _extract_table_header(table_html: str) -> str:
        """提取表格的 ``<thead>`` 部分。

        Args:
            table_html: 表格 HTML。

        Returns:
            str: thead 内容（无 thead 时返回空字符串）。
        """
        match = _THEAD_PATTERN.search(table_html)
        if match:
            return match.group(0)
        return ""

    @staticmethod
    def _build_table(
        header: str,
        header_rows: list[str],
        data_rows: list[str],
    ) -> str:
        """构建完整表格 HTML。

        Args:
            header: thead 内容（可能为空）。
            header_rows: 表头行列表（``<tr><th>...</th></tr>``）。
            data_rows: 数据行列表（``<tr><td>...</td></tr>``）。

        Returns:
            str: 完整的 ``<table>...</table>`` HTML。
        """
        parts = ["<table>"]
        if header:
            parts.append(header)
        elif header_rows:
            parts.append("<thead>")
            parts.extend(header_rows)
            parts.append("</thead>")
        parts.append("<tbody>")
        parts.extend(data_rows)
        parts.append("</tbody>")
        parts.append("</table>")
        return "\n".join(parts)

    @staticmethod
    def _add_overlap(batches: list[str], overlap: int) -> list[str]:
        """为批次添加重叠（前批末尾 N 字符作为下批前缀）。

        Args:
            batches: 原始批次列表。
            overlap: 重叠字符数。

        Returns:
            list[str]: 带重叠的批次列表。
        """
        if len(batches) <= 1 or overlap <= 0:
            return batches

        result: list[str] = [batches[0]]
        for i in range(1, len(batches)):
            prev_tail = batches[i - 1][-overlap:] if len(batches[i - 1]) > overlap else batches[i - 1]
            result.append(f"...{prev_tail}\n\n{batches[i]}")
        return result


# 模块级单例
batch_processor = BatchProcessor()
