"""HTML 表格 → 逐行结构化文本（供 LLM 抽取）。

背景：LLM 直接读 HTML 表格抽取质量差（值挤在一行、无显式行号/分隔），
改为按行输出「行N: 值1 | 值2 | ...」，表头行保留在行序列中，
LLM 可结合表头理解每列含义，提升"表格数据 → 记录"的抽取可靠性。

说明：不做 rowspan/colspan 的完整合并（跨行/跨列单元格值按出现顺序展开，
不重复填充），保持实现轻量；值之间用竖线分隔，行号用于引用。
"""

from __future__ import annotations

import html as html_lib
import re

_TR_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.DOTALL)
_CELL_RE = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")


def _row_cells(tr_html: str) -> list[str]:
    """提取一个 <tr> 内全部 td/th 的文本（去标签、HTML 反转义、去空白）。"""
    cells: list[str] = []
    for m in _CELL_RE.finditer(tr_html):
        raw = m.group(1)
        text = _TAG_RE.sub("", raw)
        text = html_lib.unescape(text)
        text = re.sub(r"\s+", " ", text).strip()
        cells.append(text)
    return cells


def table_to_rows(content: str) -> str:
    """HTML 表格 → 逐行文本；非表格内容原样返回。"""
    if not (content or "").lstrip().lower().startswith("<table"):
        return content or ""
    rows = _TR_RE.findall(content)
    lines = ["[表格内容（逐行，行号即数据行序号）]"]
    for i, tr in enumerate(rows, start=1):
        cells = _row_cells(tr)
        if not cells:
            continue
        lines.append(f"行{i}: " + " | ".join(cells))
    return "\n".join(lines)
