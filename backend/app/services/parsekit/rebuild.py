"""后处理/版面重建（Phase 4，旧版 Popo 迁移）。

功能：
- build_tree：标题层级栈式重建、图文关联、表注关联、结构树输出；
- render_tree：文档树 → 层级化 Markdown（供后续阶段/前端使用）；
- mark_cross_page_tables：U8 跨页表格标记（本期仅标记，不做合并）。
"""

from __future__ import annotations

from app.core.logging import get_logger

from .types import LayoutBlock

logger = get_logger(__name__)


def _block_node(block: LayoutBlock, kind: str) -> dict:
    return {
        "type": kind,
        "content": (block.content or "").strip(),
        "level": 0,
        "page": block.page_index,
        "order": block.order,
        "children": [],
    }


def _title_level(block: LayoutBlock) -> int:
    structural = block.structural or {}
    return max(1, min(int(structural.get("title_level") or 1), 6))


def _caption_kind(block_type: str) -> str:
    if block_type == "image_caption":
        return "image_caption"
    if block_type == "table_caption":
        return "table_caption"
    return ""


def build_tree(blocks: list[LayoutBlock]) -> dict:
    """将阅读顺序版面块重建为嵌套文档树（标题层级/图文关联/表注关联）。"""
    root: dict = {"type": "root", "level": 0, "content": "", "children": []}
    stack: list[dict] = [root]
    image_links = 0
    table_links = 0

    def attach(node: dict) -> None:
        stack[-1]["children"].append(node)

    for block in blocks:
        if block.type == "title":
            level = _title_level(block)
            node = _block_node(block, "title")
            node["level"] = level
            while len(stack) > 1 and stack[-1]["level"] >= level:
                stack.pop()
            attach(node)
            stack.append(node)
            continue

        if block.type == "image":
            attach(_block_node(block, "image"))
            continue

        if block.type == "table":
            attach(_block_node(block, "table"))
            continue

        caption = _caption_kind(block.type)
        if caption:
            for parent in reversed(stack):
                children = parent["children"]
                if not children:
                    continue
                last = children[-1]
                if caption == "image_caption" and last["type"] == "image":
                    last["children"].append(_block_node(block, "image_caption"))
                    image_links += 1
                    break
                if caption == "table_caption" and last["type"] == "table":
                    last["children"].append(_block_node(block, "table_caption"))
                    table_links += 1
                    break
            else:
                attach(_block_node(block, caption))
            continue

        attach(_block_node(block, block.type))

    stats = {
        "image_caption_links": image_links,
        "table_caption_links": table_links,
        "title_count": sum(1 for b in blocks if b.type == "title"),
    }
    root["stats"] = stats
    return root


def _render_node(node: dict, lines: list[str]) -> None:
    node_type = node["type"]
    level = node.get("level", 0)
    content = node.get("content", "").strip()
    page = node.get("page", 0)

    if node_type == "title":
        lines.append(f"{'#' * min(max(level, 1), 6)} {content.lstrip('#').strip()}")
        lines.append("")
    elif node_type == "table":
        if content.lower().startswith("<table"):
            lines.append(content)
        else:
            lines.append(f"<!-- table: page {page} -->")
        lines.append("")
    elif node_type == "formula":
        lines.append(f"$${content}$$" if content else f"<!-- formula: page {page} -->")
        lines.append("")
    elif node_type == "image":
        lines.append(f"<!-- image: page {page} -->")
        lines.append("")
    elif node_type in ("image_caption", "table_caption"):
        if content:
            lines.append(f"*{content}*")
            lines.append("")
    elif node_type in ("footnote", "aside_text"):
        if content:
            lines.append(f"> {content}")
            lines.append("")
    else:
        if content:
            lines.append(content)
            lines.append("")

    for child in node.get("children", []):
        _render_node(child, lines)


def render_tree(tree: dict) -> str:
    """将文档树渲染为层级化 Markdown。"""
    lines: list[str] = []
    for child in tree.get("children", []):
        _render_node(child, lines)
    return "\n".join(lines).strip() + "\n"


def mark_cross_page_tables(
    page_layouts: list[list[LayoutBlock]],
) -> int:
    """标记跨页表格（U8：本期仅记录，不做合并）。

    规则：上一页底部（y1≥0.85）存在 table 块，下一页顶部（y0≤0.15）存在
    table 块，且两者水平区间有重叠，则两侧块均标记 table_cross_page=true。
    """
    marked = 0
    for idx in range(len(page_layouts) - 1):
        prev_tables = [
            b
            for b in page_layouts[idx]
            if b.type == "table" and b.bbox.y1 >= 0.85
        ]
        next_tables = [
            b
            for b in page_layouts[idx + 1]
            if b.type == "table" and b.bbox.y0 <= 0.15
        ]
        for prev in prev_tables:
            for nxt in next_tables:
                overlap = min(prev.bbox.x1, nxt.bbox.x1) - max(
                    prev.bbox.x0, nxt.bbox.x0
                )
                if overlap > 0:
                    prev.structural = {
                        **(prev.structural or {}),
                        "table_cross_page": True,
                    }
                    nxt.structural = {
                        **(nxt.structural or {}),
                        "table_cross_page": True,
                    }
                    marked += 2
    if marked:
        logger.info("跨页表格标记完成（U8，仅记录）", blocks=marked)
    return marked
