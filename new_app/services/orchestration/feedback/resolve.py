"""Deterministic expected-value resolution from OCR pages.

Three sources, in order of reliability:

* table cells vs record raw values (handled in ``diagnosis._first_mismatch``)
* cover metadata: standard number and title
* clause lines: the source sentence that states a requirement
"""

from __future__ import annotations

import re
from typing import Any

from .schema_contract import property_name

STANDARD_RE = re.compile(
    r"(?:GB|GJB|JB|NB|YB|YS|ASTM|ASME|API|ISO|EN|DIN|RCC-M|HAF)"
    r"\s*/?\s*[A-Z]?\s*\d[\dA-Za-z.\-—－:]*",
    re.IGNORECASE,
)
META_KEYWORDS = (
    "标准号",
    "标准编号",
    "标准名称",
    "标准名",
    "标题",
    "版本",
    "发布",
    "实施",
)
CLAUSE_KEYWORDS = (
    "试验方法",
    "检验规则",
    "取样",
    "室温拉伸",
    "高温拉伸",
    "低温拉伸",
    "冲击",
    "硬度",
    "化学成分",
    "力学性能",
    "技术要求",
)
REQUIREMENT_MARKERS = ("≥", "≤", ">=", "<=", "不小于", "不大于", "大于", "小于", "应")
CJK_RE = re.compile(r"[\u4e00-\u9fff]{2,}")


def normalize_text(text: str) -> str:
    """Repair UTF-8 text that was decoded as Latin-1 by the OCR layer."""
    if not text:
        return ""
    sample = text[:400]
    suspicious = sum(1 for char in sample if 0x80 <= ord(char) <= 0xFF)
    if suspicious < len(sample) * 0.25:
        return text
    for encoding in ("utf-8", "gbk"):
        try:
            return text.encode("latin-1").decode(encoding)
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
    return text


def _lines(page: dict[str, Any]) -> list[str]:
    text = normalize_text(str(page.get("markdown") or ""))
    return [line.strip() for line in text.splitlines() if line.strip()]


def _is_table_row(line: str) -> bool:
    return line.count("|") >= 3


def _page_candidates(pages: list[dict[str, Any]], limit: int = 40) -> list[tuple[int, str]]:
    candidates: list[tuple[int, str]] = []
    for page in pages[:limit]:
        page_no = int(page.get("page_no") or 0)
        for line in _lines(page)[:400]:
            candidates.append((page_no, line))
    return candidates


def _title_line(text: str) -> bool:
    if not (4 <= len(text) <= 60):
        return False
    if not CJK_RE.search(text) or STANDARD_RE.search(text):
        return False
    if any(marker in text for marker in ("发布", "实施", "年", "月", "日", "ICS")):
        return False
    return not text.replace(" ", "").isdigit()


def resolve_document_meta(
    pages: list[dict[str, Any]], *, description: str = ""
) -> dict[str, Any] | None:
    """Find the standard number/title on the cover, when the feedback asks for it."""
    if not any(keyword in description for keyword in META_KEYWORDS):
        return None
    candidates = _page_candidates(pages, limit=3)
    standard_no = ""
    standard_name = ""
    quote = ""
    page_no = 0
    for index, (current_page, line) in enumerate(candidates):
        match = STANDARD_RE.search(line)
        if not match:
            continue
        standard_no = match.group(0).strip()
        page_no = current_page
        quote = line
        after = candidates[index + 1 : index + 6]
        before = list(reversed(candidates[max(0, index - 3) : index]))
        for _, nearby in after + before:
            text = nearby.strip()
            if _title_line(text):
                standard_name = text
                break
        break
    if not standard_no and not standard_name:
        return None
    return {
        "source": "cover",
        "standard_no": standard_no,
        "standard_name": standard_name,
        "page_no": page_no,
        "quote": quote or standard_name,
        "expected": standard_no or standard_name,
    }


def _keywords(description: str, properties: list[str]) -> list[str]:
    keywords: list[str] = [keyword for keyword in CLAUSE_KEYWORDS if keyword in description]
    for prop in properties:
        if prop:
            keywords.append(prop)
            chinese = property_name(prop)
            if chinese:
                keywords.append(chinese)
    for token in CJK_RE.findall(description):
        if 2 <= len(token) <= 12:
            keywords.append(token)
    return list(dict.fromkeys(keywords))


def resolve_clause(
    pages: list[dict[str, Any]],
    *,
    description: str = "",
    properties: list[str] | None = None,
) -> dict[str, Any] | None:
    """Return the best clause line stating a requirement for the target property."""
    keywords = _keywords(description, properties or [])
    if not keywords:
        return None
    best: tuple[int, int, str, str, int] | None = None
    for page_no, line in _page_candidates(pages):
        if _is_table_row(line) or len(line) < 4:
            continue
        matched = next((keyword for keyword in keywords if keyword in line), "")
        if not matched:
            continue
        score = 2
        if any(marker in line for marker in REQUIREMENT_MARKERS):
            score += 2
        if 8 <= len(line) <= 120:
            score += 1
        candidate = (score, -page_no, line, matched, page_no)
        if best is None or candidate[:2] > best[:2]:
            best = candidate
    if best is None or best[0] < 3:
        return None
    score, _, line, matched, page_no = best
    return {
        "source": "clause",
        "expected": line,
        "keyword": matched,
        "page_no": page_no,
        "quote": line,
        "score": score,
    }


def resolve_expected(
    pages: list[dict[str, Any]],
    *,
    description: str,
    properties: list[str] | None = None,
) -> dict[str, Any] | None:
    """Cover metadata first, then clause text."""
    meta = resolve_document_meta(pages, description=description)
    if meta is not None:
        return meta
    return resolve_clause(pages, description=description, properties=properties)
