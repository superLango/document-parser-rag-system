"""Reject patches that hardcode a single case or touch protected files."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .lexicon import PROTECTED_DICTIONARY_FILES

FORBIDDEN_PREFIXES = (
    "apps/api/",
    "apps/web/",
    "infra/",
    "deploy/",
    ".github/",
)
TEST_PREFIXES = ("tests/", "metal_doc_agent/selfheal/tests")
IDENTITY_FIELDS = ("doc_id", "record_id", "table_id", "feedback_id", "job_id")
LITERAL_RE = re.compile(r"""["']([^"']{2,})["']""")


def case_literals(
    diagnosis: dict[str, Any] | None,
    finding: Any = None,
) -> list[str]:
    """Collect literals that belong to this one case and must not enter code."""

    values: list[str] = []
    if diagnosis:
        correction = diagnosis.get("correction") or {}
        for key in ("value", "expected"):
            value = correction.get(key) or diagnosis.get(key)
            if value:
                values.append(str(value))
        target = diagnosis.get("target") or {}
        for key in ("record_id", "table_id"):
            if target.get(key):
                values.append(str(target[key]))
        document = diagnosis.get("document") or {}
        for key in ("standard_no", "doc_id"):
            if document.get(key):
                values.append(str(document[key]))
    if finding is not None:
        for key in ("observed", "expected"):
            value = getattr(finding, key, None)
            if value:
                values.append(str(value))
        target = getattr(finding, "target", None)
        if target is not None:
            for key in ("record_id", "table_id"):
                value = getattr(target, key, None)
                if value:
                    values.append(str(value))
    cleaned: list[str] = []
    for value in values:
        text = value.strip()
        if len(text) < 2:
            continue
        if text.isdigit() and len(text) < 3:
            continue
        if text not in cleaned:
            cleaned.append(text)
    return cleaned


def check_patch(
    diff: str,
    files: list[str],
    literals: list[str],
    project_root: str | Path | None = None,
) -> tuple[bool, str]:
    declared = [name.replace("\\", "/").lstrip("./") for name in files]
    problems: list[str] = []
    for name in declared:
        if name.startswith("/") or ".." in name.split("/"):
            problems.append(f"非法路径：{name}")
            continue
        if name in PROTECTED_DICTIONARY_FILES or name.startswith("configs/dictionaries/"):
            problems.append(f"禁止修改词典/别名文件：{name}")
            continue
        if name.startswith("configs/business_dictionary"):
            problems.append(f"禁止修改词典快照：{name}")
            continue
        if any(name.startswith(prefix) for prefix in FORBIDDEN_PREFIXES):
            problems.append(f"禁止修改：{name}")
    if problems:
        return False, "；".join(problems)

    added: list[tuple[str, str]] = []
    current = ""
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            current = line[6:].strip()
            continue
        if line.startswith("+") and not line.startswith("+++"):
            added.append((current, line[1:]))
    for name, line in added:
        if not name or name.startswith(TEST_PREFIXES):
            continue
        if line.strip().startswith("#"):
            continue
        for literal in literals:
            if literal and literal in line:
                problems.append(
                    f"{name} 写入了本案例值「{literal}」，属于个案硬编码"
                )
                break
        if any(
            re.search(rf"\b{field}\s*(==|!=|in)\b", line)
            for field in IDENTITY_FIELDS
        ):
            problems.append(f"{name} 按 {', '.join(IDENTITY_FIELDS)} 特判")
            break
    if problems:
        return False, "；".join(dict.fromkeys(problems))
    return True, "未发现个案硬编码或词典改动"
