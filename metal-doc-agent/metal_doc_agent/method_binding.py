"""Fill missing test methods in the projected schema from document prose.

Table extraction only sees method columns. Many standards instead put the
method in a sentence ("拉伸试验应按 GB/T 228.1 的规定进行") or in a normative
references list. This module scans the OCR pages once and fills only empty
``试验方法`` cells, leaving explicit values untouched.
"""

from __future__ import annotations

import re
from typing import Any

from .contracts import Page
from .references import STANDARD_RE

# Ordered: specific families must be checked before the generic ones. 持久/
# 蠕变 precede 室温拉伸 because "金属拉伸蠕变及持久试验方法" contains both
# words; high/low temperature tensile is handled separately below so that
# "高温持久" is not mistaken for "高温拉伸".
FAMILY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("持久", ("持久",)),
    ("蠕变", ("蠕变",)),
    ("腐蚀", ("腐蚀",)),
    ("疲劳", ("疲劳",)),
    ("断裂韧性", ("断裂韧性",)),
    ("铁素体", ("铁素体",)),
    ("室温拉伸", ("室温拉伸", "室温", "常温", "拉伸")),
    ("夏比冲击", ("夏比冲击", "冲击")),
    ("布氏硬度", ("布氏硬度", "布氏")),
    ("洛氏硬度", ("洛氏硬度", "洛氏")),
    ("维氏硬度", ("维氏硬度", "维氏")),
    ("低倍", ("低倍",)),
    ("高倍组织", ("高倍组织", "高倍", "显微组织")),
    ("晶粒度", ("晶粒度", "晶粒")),
    ("非金属夹杂", ("非金属夹杂", "夹杂物")),
    ("超声波检测", ("超声波检测", "超声波", "超声")),
    ("弯曲", ("弯曲",)),
    ("硬度", ("硬度",)),
)

FEATURE_METHOD_KEYS: dict[str, tuple[str, ...]] = {
    "室温拉伸": ("室温拉伸", "拉伸"),
    "高温拉伸": ("高温拉伸", "拉伸"),
    "低温拉伸": ("低温拉伸", "拉伸"),
    "夏比冲击": ("夏比冲击",),
    "布氏硬度": ("布氏硬度", "硬度"),
    "洛氏硬度": ("洛氏硬度", "硬度"),
    "维氏硬度": ("维氏硬度", "硬度"),
    "低倍": ("低倍",),
    "高倍组织": ("高倍组织",),
    "显微组织": ("高倍组织",),
    "晶粒度": ("晶粒度",),
    "非金属夹杂": ("非金属夹杂",),
    "超声波检测": ("超声波检测",),
    "弯曲": ("弯曲",),
    "持久": ("持久",),
    "高温光滑持久": ("持久",),
    "蠕变": ("蠕变",),
    "腐蚀": ("腐蚀",),
    "疲劳": ("疲劳",),
    "断裂韧性": ("断裂韧性",),
    "铁素体": ("铁素体",),
}

METHOD_VERBS = ("进行", "执行", "检验", "试验", "检测", "测定", "评定")


def _join_broken_numbers(text: str) -> str:
    """Repair OCR line breaks inside standard numbers (``228.\\n1``)."""

    text = re.sub(r"(?<=\d)\.\s*\n\s*(?=\d)", ".", text)
    text = re.sub(r"[ \t]*\n[ \t]*", " ", text)
    return text


def _standard_in(sentence: str) -> str | None:
    match = STANDARD_RE.search(sentence)
    if match is None:
        return None
    org = re.sub(r"\s+", "", match.group("org"))
    number = re.sub(r"\s+", "", match.group("num"))
    year = re.sub(r"\s+", "", match.group("year") or "")
    if not org or not number:
        return None
    return f"{org} {number}-{year}" if year else f"{org} {number}"


def _family_for(sentence: str) -> str | None:
    if "高温" in sentence and "拉伸" in sentence:
        return "高温拉伸"
    if "低温" in sentence and "拉伸" in sentence:
        return "低温拉伸"
    for family, keywords in FAMILY_RULES:
        if any(keyword in sentence for keyword in keywords):
            return family
    return None


REFERENCE_HINTS = (
    "试验方法",
    "检验方法",
    "测定方法",
    "测定法",
    "试验法",
    "分析方法",
    "检验法",
)


def _reference_methods(pages: list[Page]) -> dict[str, dict[str, Any]]:
    """Read the normative-reference list line by line.

    The sentence pass flattens newlines, so a reference list becomes one
    over-long sentence and only its first entry is ever read. Reference lines
    carry no verb either; a line-oriented pass is the only reliable source for
    methods such as ``GB/T 4338 金属材料高温拉伸试验方法``.
    """

    found: dict[str, dict[str, Any]] = {}
    for page in pages:
        for raw_line in (page.markdown or "").splitlines():
            line = raw_line.strip().lstrip("-•· ").strip()
            if len(line) < 8 or len(line) > 180:
                continue
            if not any(hint in line for hint in REFERENCE_HINTS):
                continue
            if not re.match(
                r"^(?:GB|GJB|JB|YB|NB|YS|Q\s*/|ASTM|ISO|AMS|EN|DIN)\b",
                line,
                re.IGNORECASE,
            ):
                # Reference entries start with the standard code. This keeps
                # table rows such as "<td>GB/T 4334.2</td>" out.
                continue
            method = _standard_in(line)
            if method is None:
                continue
            family = _family_for(line)
            if family is None:
                continue
            found.setdefault(
                family,
                {
                    "method": method,
                    "page": page.page_no,
                    "quote": re.sub(r"\s+", " ", line)[:160],
                },
            )
    return found


def extract_document_methods(pages: list[Page]) -> dict[str, dict[str, Any]]:
    """Return ``family -> {method, page, quote}`` from page text."""

    found: dict[str, dict[str, Any]] = {}
    for page in pages:
        text = _join_broken_numbers(page.markdown or "")
        for raw in re.split(r"[。；;]", text):
            sentence = raw.strip()
            if len(sentence) < 6 or len(sentence) > 220:
                continue
            if not any(verb in sentence for verb in METHOD_VERBS) and "试验方法" not in sentence:
                continue
            method = _standard_in(sentence)
            if method is None:
                continue
            if len(list(STANDARD_RE.finditer(sentence))) > 1:
                # Newlines were flattened, so a reference list arrives as one
                # sentence with several standards. Reading it here would bind
                # the first code to whichever family appears last; the
                # line-oriented reference pass below handles entries correctly.
                continue
            family = _family_for(sentence)
            if family is None:
                continue
            found.setdefault(
                family,
                {
                    "method": method,
                    "page": page.page_no,
                    "quote": re.sub(r"\s+", " ", sentence)[:160],
                },
            )
    for family, value in _reference_methods(pages).items():
        found.setdefault(family, value)
    return found


ROOM_TENSILE_METHOD_RE = re.compile(r"GB\s*/?\s*T?\s*228(?:\.\d+)?")
TENSILE_FEATURES = {"高温拉伸", "低温拉伸"}


def fill_projected_methods(
    payload: dict[str, Any], pages: list[Page]
) -> dict[str, Any]:
    """Fill empty ``试验方法`` cells in a projected schema payload.

    A schema row may already carry the room-temperature tensile standard
    (``GB/T 228``) because the document's prose only cites that one. When the
    normative-reference list names a temperature-specific method (``GB/T
    4338`` for high temperature), the generic value is corrected instead of
    being left in place.
    """

    methods = extract_document_methods(pages)
    updated = 0
    filled: dict[str, int] = {}
    corrected: dict[str, int] = {}
    for category in payload.get("categories") or []:
        feature = str(category.get("feature") or "")
        keys = FEATURE_METHOD_KEYS.get(feature)
        if not keys:
            continue
        chosen = next((methods[key] for key in keys if key in methods), None)
        for row in category.get("records") or []:
            current = str(row.get("试验方法") or "").strip()
            if current:
                if (
                    feature in TENSILE_FEATURES
                    and feature in methods
                    and ROOM_TENSILE_METHOD_RE.search(current)
                    and methods[feature]["method"] != current
                ):
                    row["试验方法"] = methods[feature]["method"]
                    corrected[feature] = corrected.get(feature, 0) + 1
                    updated += 1
                continue
            if chosen is None:
                continue
            row["试验方法"] = chosen["method"]
            updated += 1
            filled[feature] = filled.get(feature, 0) + 1
    return {
        "updated": updated,
        "filled": filled,
        "corrected": corrected,
        "methods": {family: value["method"] for family, value in methods.items()},
        "sources": methods,
    }
