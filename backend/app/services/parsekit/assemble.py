"""Markdown 拼接拼装（阶段 E，输出 result.md）。"""

from __future__ import annotations

from .types import LayoutBlock


def _title_level(block: LayoutBlock) -> int:
    structural = block.structural or {}
    level = int(structural.get("title_level") or 1)
    return max(1, min(level, 6))


def _render_block(block: LayoutBlock) -> list[str]:
    content = (block.content or "").strip()
    if block.type == "title":
        clean = content.lstrip("#").strip()
        if not clean:
            return []
        return [f"{'#' * _title_level(block)} {clean}", ""]
    if block.type == "table":
        if content.lower().startswith("<table"):
            return [content, ""]
        return [f"<!-- table: page {block.page_index} -->", ""]
    if block.type in ("formula", "equation"):
        if content:
            return [f"$${content}$$", ""]
        return [f"<!-- formula: page {block.page_index} -->", ""]
    if block.type == "image":
        return [f"<!-- image: page {block.page_index} -->", ""]
    if "caption" in block.type:
        return [f"*{content}*", ""] if content else []
    if "footnote" in block.type or block.type == "aside_text":
        return [f"> {content}", ""] if content else []
    if content:
        return [content, ""]
    return []


def assemble_markdown(ordered_blocks: list[LayoutBlock]) -> str:
    """将按阅读顺序排好的版面块渲染为 Markdown。"""
    lines: list[str] = []
    current_page = 0
    for block in ordered_blocks:
        if block.page_index != current_page:
            current_page = block.page_index
            lines.append(f"<!-- page: {current_page} -->")
            lines.append("")
        lines.extend(_render_block(block))
    return "\n".join(lines).strip() + "\n"
