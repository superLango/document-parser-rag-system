"""文档内状态/条件别名挖掘。"""
from __future__ import annotations

import re
from typing import Iterable

ALIAS_RE = re.compile(r"([\u4e00-\u9fff]{1,8})[（(]([A-Za-z0-9]{1,4})[)）]")
PREFIX_CHARS = "及为是状态的和在"


def clean_alias_name(name: str) -> str:
    value = name
    while value and value[0] in PREFIX_CHARS:
        value = value[1:]
    return value


def extract_state_aliases(text: str) -> dict[str, str]:
    """从文本中提取 状态名称(代号) 映射，例如 软态(M)、固溶退火态(ST)。"""
    mapping: dict[str, str] = {}
    for match in ALIAS_RE.finditer(str(text or "")):
        name = clean_alias_name(match.group(1))
        code = match.group(2)
        if not name:
            continue
        if not any(word in name for word in ("态", "处理")):
            continue
        current = mapping.get(code)
        if current is None or len(name) < len(current.split("(")[0]):
            mapping[code] = f"{name}({code})"
    return mapping


def extract_document_aliases(pages_markdown: Iterable[str]) -> dict[str, str]:
    """从整篇文档各页 markdown 提取状态别名（后出现的覆盖不了更短名称）。"""
    mapping: dict[str, str] = {}
    for text in pages_markdown:
        for code, full in extract_state_aliases(str(text or "")).items():
            current = mapping.get(code)
            if current is None or len(full.split("(")[0]) < len(current.split("(")[0]):
                mapping[code] = full
    return mapping
