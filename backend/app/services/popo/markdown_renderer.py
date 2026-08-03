"""Markdown 渲染器。

将文档树递归渲染为层级化 Markdown 文档。

渲染规则：
- 标题：``#`` * level + 标题文本（level 1-6，超过 6 用 6）
- 表格：原样输出 HTML
- 图片：占位注释 ``<!-- image: page N -->``
- 题注：斜体 ``*题注文本*``
- 脚注：以 ``> `` 前缀引用样式
- 普通文本：原样输出
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def render(tree: dict, stats: dict | None = None) -> str:
    """将文档树渲染为 Markdown 字符串。

    Args:
        tree: 文档树根节点。
        stats: 重建统计信息（可选，附加到文档末尾）。

    Returns:
        层级化 Markdown 字符串。
    """
    lines: list[str] = []
    _render_node(tree, lines, depth=0)

    # 统计信息
    if stats:
        lines.append("---")
        lines.append("")
        lines.append("## 重建统计")
        lines.append("")
        for key, value in stats.items():
            lines.append(f"- {key}: {value}")
        lines.append("")

    return "\n".join(lines)


def _render_node(node: dict, lines: list[str], depth: int) -> None:
    """递归渲染文档树节点。

    Args:
        node: 当前节点。
        lines: 输出行列表（原地修改）。
        depth: 当前深度（用于缩进，标题不影响深度）。
    """
    for child in node.get("children", []):
        child_type = child["type"]
        level = child.get("level", 0)
        content = child.get("content", "").strip()
        page = child.get("page", 0)

        # 标题节点
        if level > 0 or child_type == "title":
            heading_level = min(max(level, 1), 6)
            heading = "#" * heading_level
            # 移除标题内容中可能已有的 # 前缀
            clean = content.lstrip("#").strip()
            lines.append(f"{heading} {clean}")
            lines.append("")
            _render_node(child, lines, depth + 1)
            lines.append("")

        elif child_type == "table":
            # 表格原样输出 HTML
            if content:
                lines.append(content)
                lines.append("")

        elif child_type in ("image", "seal"):
            lines.append(f"<!-- image: page {page} -->")
            lines.append("")

        elif "caption" in child_type:
            # 题注用斜体
            if content:
                lines.append(f"*{content}*")
                lines.append("")

        elif "footnote" in child_type:
            # 脚注用引用样式
            if content:
                lines.append(f"> {content}")
                lines.append("")

        else:
            # 普通文本
            if content:
                lines.append(content)
                lines.append("")

        # 递归处理子节点（非标题节点也可能有子节点）
        if child.get("children") and level == 0:
            _render_node(child, lines, depth + 1)
