"""Compatibility gate: code changes must be additive and non-breaking."""

from __future__ import annotations

import re

CONTRACT_FILES = (
    "metal_doc_agent/contracts.py",
    "metal_doc_agent/selfheal/contracts.py",
    "apps/api/hanson_api/schemas.py",
)
ENUM_RE = re.compile(r"^\s{4}(\w+)\s*=\s*[\"']([^\"']+)[\"']\s*$")
DEF_RE = re.compile(r"^\s*(?:async\s+)?def\s+(\w+)")
CLASS_RE = re.compile(r"^\s*class\s+(\w+)")


def check_compat(diff: str, files: list[str]) -> tuple[bool, str]:
    declared = [name.replace("\\", "/").lstrip("./") for name in files]
    removed_defs: list[str] = []
    added_defs: list[str] = []
    removed_enums: list[str] = []
    added_required: list[str] = []
    current = ""
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            current = line[6:].strip()
            continue
        if line.startswith("--- a/") or line.startswith("@@"):
            continue
        body = line[1:]
        if not current:
            continue
        if line.startswith("-") and not line.startswith("---"):
            match = DEF_RE.match(body) or CLASS_RE.match(body)
            if match:
                removed_defs.append(f"{current}:{match.group(1)}")
            if current in CONTRACT_FILES and ENUM_RE.match(body):
                removed_enums.append(f"{current}:{body.strip()}")
        elif line.startswith("+") and not line.startswith("+++"):
            match = DEF_RE.match(body) or CLASS_RE.match(body)
            if match:
                added_defs.append(match.group(1))
            if current in CONTRACT_FILES and _looks_required_field(body):
                added_required.append(f"{current}:{body.strip()}")

    problems: list[str] = []
    for item in removed_defs:
        name = item.rsplit(":", 1)[-1]
        if name not in added_defs:
            problems.append(f"删除/重命名既有定义：{item}")
    if removed_enums:
        problems.append("删除枚举值：" + "、".join(removed_enums[:3]))
    if added_required:
        problems.append(
            "新增必填契约字段（应改为可选）：" + "、".join(added_required[:3])
        )
    if problems:
        return False, "；".join(problems)
    return True, "接口/契约保持兼容（仅增量）"


def _looks_required_field(line: str) -> bool:
    text = line.strip()
    if not text or text.startswith(("def ", "class ", "@", "#", '"""')):
        return False
    if "=" in text or text.endswith((":", ",", ")")):
        return False
    return bool(re.match(r"^\w+\s*:\s*[^=]+$", text))
