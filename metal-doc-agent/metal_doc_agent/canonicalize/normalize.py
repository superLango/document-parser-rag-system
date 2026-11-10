"""Text normalization for business-dictionary matching."""

from __future__ import annotations

import re
import unicodedata

DASHES = ("—", "–", "−", "－")
SYNONYMS = {
    "常温": "室温",
    "室温": "室温",
    "常温拉伸": "室温拉伸",
    "常温冲击": "室温冲击",
    "室温拉伸试验": "室温拉伸",
    "瞬时拉伸性能": "室温拉伸",
    "瞬时拉伸": "室温拉伸",
    "侧向膨胀值": "侧膨胀值",
    "侧向膨胀": "侧膨胀",
}
ITEM_SUFFIXES = ("检验", "试验", "检测", "检查")
STD_RE = re.compile(
    r"(?P<body>(?:GB/T|GB|GJB|JB/T|YB/T|HB|ASTM|ISO|AMS|Q/[A-Za-z]+)\s*"
    r"[A-Z]?\s*[0-9.\-]+)",
    re.IGNORECASE,
)


def normalize_text(value: str | None) -> str:
    text = unicodedata.normalize("NFKC", value or "")
    text = text.replace("Ⅰ", "1").replace("Ⅱ", "2").replace("Ⅲ", "3")
    text = text.replace("Ⅳ", "4").replace("Ⅴ", "5")
    for dash in DASHES:
        text = text.replace(dash, "-")
    text = text.lower()
    text = re.sub(r"\s+", "", text)
    text = text.replace("（", "(").replace("）", ")")
    text = text.strip("()[]{}:：,，;；、")
    return text


def normalize_item_name(value: str | None) -> str:
    text = normalize_text(value)
    changed = True
    while changed:
        changed = False
        for suffix in ITEM_SUFFIXES:
            if text.endswith(suffix) and len(text) > len(suffix):
                text = text[: -len(suffix)]
                changed = True
    text = text.replace("*", "").replace("'", "")
    return SYNONYMS.get(text, text)


def normalize_standard_no(value: str | None) -> str:
    text = unicodedata.normalize("NFKC", value or "").upper()
    for dash in DASHES:
        text = text.replace(dash, "-")
    text = re.sub(r"\s+", "", text)
    return text.strip(".,;；、")


def standard_base(value: str | None) -> str:
    text = normalize_standard_no(value)
    # Strip both four-digit and legacy two-digit edition years so editions of
    # the same standard share one base (GB/T 228-99 / GB/T 228-2010).
    return re.sub(r"(?:-(?:19|20)\d{2}|[-:]\d{2})$", "", text)


def extract_standards(value: str | None) -> list[str]:
    text = unicodedata.normalize("NFKC", value or "")
    for dash in DASHES:
        text = text.replace(dash, "-")
    return [
        normalize_standard_no(match.group("body"))
        for match in STD_RE.finditer(text)
    ]


def item_tokens(value: str | None) -> set[str]:
    text = normalize_item_name(value)
    return set(re.findall(r"[a-z]+|[0-9]+(?:\.[0-9]+)?|[\u4e00-\u9fff]", text))


def similarity(left: str, right: str) -> float:
    left_norm = normalize_item_name(left)
    right_norm = normalize_item_name(right)
    if not left_norm or not right_norm:
        return 0.0
    if left_norm == right_norm:
        return 1.0
    overlap = item_tokens(left_norm) & item_tokens(right_norm)
    union = item_tokens(left_norm) | item_tokens(right_norm)
    token_score = len(overlap) / len(union) if union else 0.0
    from difflib import SequenceMatcher

    char_score = SequenceMatcher(None, left_norm, right_norm).ratio()
    return max(token_score, char_score)
