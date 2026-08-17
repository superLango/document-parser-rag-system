"""E3 抽取上下文组装。"""

from __future__ import annotations


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
        block = f"[{page_txt}]\n{hit.get('content') or ''}\n"
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
