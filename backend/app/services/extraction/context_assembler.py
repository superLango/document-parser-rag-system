"""E3 抽取上下文组装。"""

from __future__ import annotations

from .table_to_rows import table_to_rows


def assemble_segments(
    hits: list[dict],
    *,
    top_k: int,
    max_text_chars: int = 6000,
) -> list[dict]:
    """按表格边界 + 语义边界分组上下文段。

    - 表格块：独立成段（完整行文本，不跨表不混表）；
    - 文本块：按顺序聚合到 max_text_chars 上限成段（正文说明不丢失）；
    - 保持阅读顺序：表格段与文本段交错排列。
    返回 [{"type": "table"|"text", "content": str}]。
    """
    segments: list[dict] = []
    text_buf: list[str] = []
    text_chars = 0

    def flush_text() -> None:
        nonlocal text_buf, text_chars
        if text_buf:
            segments.append({"type": "text", "content": "\n".join(text_buf)})
            text_buf = []
            text_chars = 0

    for hit in hits[:top_k]:
        pages = hit.get("source_pages") or []
        page_txt = f"第 {pages[0]} 页" if pages else "未知页"
        content = hit.get("content") or ""
        if hit.get("has_table"):
            flush_text()
            segments.append({
                "type": "table",
                "content": f"[{page_txt}]\n{table_to_rows(content)}",
            })
        else:
            block = f"[{page_txt}]\n{content}"
            text_buf.append(block)
            text_chars += len(block)
            if text_chars >= max_text_chars:
                flush_text()
    flush_text()
    return segments


def assemble(
    hits: list[dict],
    *,
    top_k: int,
    max_tokens: int | None = None,
    chars_per_token: float = 1.5,
    min_keep_chars: int = 200,
    truncate_marker: str = "\n[...内容截断...]",
) -> str:
    """按命中顺序拼接上下文，受块数限制。

    max_tokens=None 时不按预算截断（完整性优先，交由抽取引擎分批处理）；
    传入 max_tokens 时保留旧行为（按预算截断），供测试/特殊场景使用。
    """
    budget = int(max_tokens * chars_per_token) if max_tokens is not None else None
    parts: list[str] = []
    used = 0
    for hit in hits[:top_k]:
        pages = hit.get("source_pages") or []
        page_txt = f"第 {pages[0]} 页" if pages else "未知页"
        content = hit.get("content") or ""
        # 表格块：HTML → 逐行结构化文本，提升 LLM 表格抽取质量
        if hit.get("has_table"):
            content = table_to_rows(content)
        block = f"[{page_txt}]\n{content}\n"
        if budget is None:
            parts.append(block)
            used += len(block)
            continue
        if used + len(block) <= budget:
            parts.append(block)
            used += len(block)
            continue
        remain = budget - used
        if remain >= min_keep_chars:
            parts.append(block[:remain] + truncate_marker)
        break
    return "\n".join(parts).strip()
