"""层级化 Markdown 重建器。

将 ``ParentChunk`` + ``ChildChunk`` 列表转换为层级化的 Markdown 文档，
输出 ``reconstructed.md``。

格式示例::

    # {level 1 标题}
    {parent content}

    ## {level 2 标题}
    {parent content}
    <table>...</table>

    ---
    ## 重建统计
    - 父块数: N
    - 子块数: N
    - 题注关联数: N
    - 向量入库数: N
"""

from __future__ import annotations

from app.services.vector.vector_models import ChildChunk, ParentChunk


class MarkdownBuilder:
    """层级化 Markdown 重建器。"""

    @staticmethod
    def build(
        parent_chunks: list[ParentChunk],
        child_chunks: list[ChildChunk],
        stats: dict | None = None,
    ) -> str:
        """生成 reconstructed.md。

        Args:
            parent_chunks: 父块列表。
            child_chunks: 子块列表。
            stats: 重建统计信息（可选）。

        Returns:
            层级化 Markdown 字符串。
        """
        lines: list[str] = []

        for parent in parent_chunks:
            # 根据层级生成标题（移除标题中已有的 # 前缀，避免双重 ##）
            clean_title = parent.title.lstrip("#").strip()
            heading_level = min(parent.level, 6) if parent.level > 0 else 1
            heading_prefix = "#" * heading_level
            lines.append(f"{heading_prefix} {clean_title}")
            lines.append("")

            # 输出父块内容（移除内容中与标题重复的首行）
            if parent.content:
                content_lines = parent.content.splitlines()
                # 跳过与标题重复的首行
                if content_lines and content_lines[0].strip().lstrip("#").strip() == clean_title:
                    content_lines = content_lines[1:]
                lines.append("\n".join(content_lines))
                lines.append("")

            # 输出该父块的子块信息（调试用，可注释）
            parent_children = [c for c in child_chunks if c.parent_id == parent.id]
            if len(parent_children) > 1:
                lines.append(
                    f"<!-- {len(parent_children)} 个子块，parent_text 长度: {len(parent.content)} -->"
                )
                lines.append("")

            lines.append("---")
            lines.append("")

        # 重建统计
        if stats:
            lines.append("## 重建统计")
            lines.append("")
            for key, value in stats.items():
                lines.append(f"- {key}: {value}")
            lines.append("")

        return "\n".join(lines)


# 模块级单例
markdown_builder = MarkdownBuilder()
