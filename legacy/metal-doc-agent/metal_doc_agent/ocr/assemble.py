"""Assemble OCR block contents into page Markdown."""

from __future__ import annotations

from collections.abc import Iterable


def _block_markdown(block_type: str, content: str) -> str:
    text = content.strip()
    if not text or block_type == "image":
        return ""
    if block_type == "title":
        return "## " + text.lstrip("#").strip()
    if block_type == "table":
        return text
    if block_type == "formula":
        if text.startswith("$$"):
            return text
        return f"$$\n{text}\n$$"
    if block_type == "footnote":
        return "\n".join(f"> {line}" for line in text.splitlines())
    return text


def assemble_page_markdown(blocks: Iterable[tuple[str, str]]) -> str:
    parts = [
        part
        for block_type, content in blocks
        if (part := _block_markdown(block_type, content))
    ]
    return "\n\n".join(parts)
