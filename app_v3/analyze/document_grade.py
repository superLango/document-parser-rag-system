"""文档级牌号推断（英文标准常见的标题/范围牌号）。"""
from __future__ import annotations

import re
from collections import Counter

from app_v3.normalize.grade import normalize_grade

# 6Al-4V / Ti-6Al-4V / 6 Al 4 V / Ti 6Al 4V
ALLOY_RE = re.compile(
    r"(?:Ti[- ]?)?(\d{1,2})\s*Al[- ]?(\d{1,2})\s*V(?![A-Za-z])",
    re.IGNORECASE,
)
GRADE_WORD_RE = re.compile(r"\bGrade\s*(\d{1,2}[A-Za-z]?)\b", re.IGNORECASE)


def infer_document_grades(pages_markdown: list[str], max_candidates: int = 5) -> list[dict]:
    """从文档文本推断牌号候选，返回 [{grade, aliases, count}]。

    只做候选，不强行应用到不唯一的文档。
    """
    counter: Counter[str] = Counter()
    aliases: dict[str, set[str]] = {}
    for text in pages_markdown:
        value = str(text or "")
        for match in ALLOY_RE.finditer(value):
            number_al = match.group(1)
            number_v = match.group(2)
            candidate = normalize_grade(f"{number_al}Al-{number_v}V")
            if match.group(0).lower().startswith("ti"):
                prefixed = f"Ti-{candidate['grade']}"
                counter[prefixed] += 1
                aliases.setdefault(prefixed, set()).add(candidate["grade"])
            else:
                counter[candidate["grade"]] += 1
                aliases.setdefault(candidate["grade"], set()).update(candidate.get("aliases") or [])
        for match in GRADE_WORD_RE.finditer(value):
            candidate = normalize_grade(f"Grade {match.group(1)}")
            counter[candidate["grade"]] += 1
            aliases.setdefault(candidate["grade"], set()).update(candidate.get("aliases") or [])
    result = []
    for grade, count in counter.most_common(max_candidates):
        result.append({"grade": grade, "aliases": sorted(aliases.get(grade, set())), "count": count})
    return result
