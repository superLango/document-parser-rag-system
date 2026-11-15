"""Reference graph and method binding for one OCR document.

Standard library only.

The normative-reference section names the standards the document depends on;
clauses then cite them inline ("按 GB/T 228.1 进行").  This module builds that
graph, marks citations that never appear in the normative list, and derives a
``feature -> method`` binding used to fill empty ``试验方法`` cells.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

SCHEMA_VERSION = "document-references/1"
STANDARD_RE = re.compile(
    r"(?P<org>GB\s*/\s*T|GBIT|GB\s*厅|GBT|GB|GJB\s*/\s*Z|GJB|JB\s*/\s*T|JB|"
    r"YB\s*/\s*T|YB|YS\s*/\s*T|YST|YS|HB\s*/\s*Z|HB|ASTM|ASME|ISO|AMS(?:-STD)?|"
    r"EN|DIN|QJ|NB\s*/\s*T|API|Q\s*/\s*[A-Za-z0-9]+)\s*"
    r"(?P<num>[A-Z]?\s*\d+(?:\.\s*\d+)*(?:\s*[-—–:]\s*\d{4})?)"
    r"(?:\s+(?P<year>\d{4}))?"
)
NORMATIVE_HEADING_RE = re.compile(
    r"^\s*#{0,6}\s*2(?:\.0)?\s*[、.．]?\s*"
    r"(?:规范性引用文件|引用标准|引用文件|normative\s+references)\s*$",
    re.IGNORECASE,
)
HEADING_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?\d{1,2}(?:\.\s*\d{1,3})*\.?\s+[\u4e00-\u9fffA-Za-z]"
)
CUE_RE = re.compile(r"按|见|符合|执行|依据|遵守|遵照|采用|引用")
SKIP_LINE_RE = re.compile(r"代替|历次版本|起草|编制|归口|提出|发布|实施|修订|相比")
RELATION_PRIORITY = {"normative": 3, "table_note": 2, "method": 2, "clause": 1, "other": 0}
METHOD_FAMILIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("化学成分", ("化学成分", "化学分析", "成分分析")),
    ("高温拉伸", ("高温拉伸",)),
    ("室温拉伸", ("拉伸试验", "室温拉伸", "拉伸")),
    ("夏比冲击", ("冲击试验", "夏比")),
    ("布氏硬度", ("布氏硬度", "布氏")),
    ("洛氏硬度", ("洛氏硬度", "洛氏")),
    ("维氏硬度", ("维氏硬度", "维氏")),
    ("断裂韧度", ("断裂韧", "断裂韧性")),
    ("弯曲", ("弯曲试验", "弯曲")),
    ("晶粒度", ("晶粒度", "晶粒")),
    ("低倍", ("低倍组织", "低倍")),
    ("高倍组织", ("高倍组织", "显微组织", "显微结构")),
    ("非金属夹杂", ("非金属夹杂", "夹杂物", "洁净度")),
    ("超声波检测", ("超声",)),
    ("铁素体", ("铁素体",)),
    ("高温持久", ("持久", "蠕变")),
)
SKIP_CLAUSE_KINDS = {"scope", "normative_reference", "terms"}


def _clean(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    return re.sub(r"\s+", " ", text).strip()


def _pages(ocr: dict[str, Any]) -> list[tuple[int, str]]:
    pages: list[tuple[int, str]] = []
    for index, page in enumerate(ocr.get("pages") or [], start=1):
        if not isinstance(page, dict):
            continue
        markdown = str(page.get("markdown") or "")
        if markdown.strip():
            pages.append((int(page.get("page_no") or index), markdown))
    if pages:
        return pages
    markdown = str(ocr.get("markdown") or "")
    return [(0, markdown)] if markdown.strip() else []


def _standard(org: str, number: str, year: str = "") -> tuple[str, str]:
    head = re.sub(r"\s+", "", unicodedata.normalize("NFKC", org or "")).upper()
    head = (
        head.replace("GBIT", "GB/T")
        .replace("GB厅", "GB/T")
        .replace("GBT", "GB/T")
        .replace("YST", "YS/T")
    )
    tail = re.sub(r"\s+", "", unicodedata.normalize("NFKC", number or ""))
    tail = tail.replace("－", "-").replace("—", "-").replace("–", "-").replace(":", "-")
    edition = re.sub(r"\s+", "", year or "")
    if not edition:
        match = re.search(r"-(\d{4})$", tail)
        if match and 1900 <= int(match.group(1)) <= 2099:
            edition = match.group(1)
            tail = tail[: match.start()]
    return f"{head} {tail}".strip(), edition


def _entry(
    match: re.Match[str],
    raw: str,
    relation: str,
    page_no: int = 0,
    clause_id: str = "",
    title: str = "",
) -> dict[str, Any] | None:
    standard_no, edition = _standard(
        match.group("org"), match.group("num"), match.group("year") or ""
    )
    if not standard_no:
        return None
    return {
        "raw": _clean(raw)[:240],
        "standard_no": standard_no,
        "title": _clean(title)[:160],
        "edition": edition,
        "dated": bool(edition),
        "relation": relation,
        "clause_id": clause_id,
        "page_no": page_no,
        "resolved": relation == "normative",
        "source": "normative_list" if relation == "normative" else "clause",
    }


def _normative_entries(pages: list[tuple[int, str]]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    in_section = False
    for page_no, markdown in pages:
        for raw_line in markdown.splitlines():
            line = _clean(raw_line).lstrip("# ").strip()
            if not line:
                continue
            if NORMATIVE_HEADING_RE.match(line):
                in_section = True
                continue
            if in_section and HEADING_RE.match(line):
                in_section = False
                continue
            if not in_section or SKIP_LINE_RE.search(line):
                continue
            match = STANDARD_RE.search(line)
            if match is None:
                continue
            suffix = line[match.end() :].lstrip(":：，,、 ")
            entry = _entry(
                match, line, relation="normative", page_no=page_no, title=suffix
            )
            if entry is not None:
                entries.append(entry)
    return entries


def _clause_entries(clauses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for clause in clauses:
        kind = str(clause.get("kind") or "")
        if kind in SKIP_CLAUSE_KINDS:
            continue
        clause_id = str(clause.get("clause_id") or "")
        page_no = int(clause.get("page_no") or 0)
        title = _clean(clause.get("title"))
        text = _clean(clause.get("text"))
        fields = clause.get("fields") or {}
        method = _clean((fields.get("method_standard") or {}).get("raw"))
        if method:
            match = STANDARD_RE.search(method)
            if match is not None:
                entry = _entry(
                    match,
                    f"{title} {method}".strip(),
                    relation="method",
                    page_no=page_no,
                    clause_id=clause_id,
                    title=title,
                )
                if entry is not None:
                    entries.append(entry)
        probe = f"{title} {text}"
        if not CUE_RE.search(probe):
            continue
        for match in STANDARD_RE.finditer(probe):
            entry = _entry(
                match,
                probe[max(0, match.start() - 24) : match.end() + 48],
                relation="clause",
                page_no=page_no,
                clause_id=clause_id,
                title=title,
            )
            if entry is not None:
                entries.append(entry)
    return entries


def _table_entries(inspections: list[dict[str, str]]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for item in inspections:
        method = _clean(item.get("method"))
        if not method:
            continue
        for match in STANDARD_RE.finditer(method):
            entry = _entry(
                match,
                f"{_clean(item.get('item'))} {method}".strip(),
                relation="table_note",
                title=_clean(item.get("item")),
            )
            if entry is not None:
                entries.append(entry)
    return entries


def _merge(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for entry in entries:
        key = entry["standard_no"]
        existing = merged.get(key)
        if existing is None:
            merged[key] = entry
            continue
        if RELATION_PRIORITY.get(entry["relation"], 0) > RELATION_PRIORITY.get(
            existing["relation"], 0
        ):
            existing["relation"] = entry["relation"]
        if not existing["title"] and entry["title"]:
            existing["title"] = entry["title"]
        if not existing["edition"] and entry["edition"]:
            existing["edition"] = entry["edition"]
            existing["dated"] = True
        if not existing["clause_id"] and entry["clause_id"]:
            existing["clause_id"] = entry["clause_id"]
        if not existing["page_no"] and entry["page_no"]:
            existing["page_no"] = entry["page_no"]
    return list(merged.values())


def _family(text: str) -> str:
    value = _clean(text)
    for family, keywords in METHOD_FAMILIES:
        if any(keyword in value for keyword in keywords):
            return family
    return ""


def _bindings(
    references: list[dict[str, Any]], clauses: list[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    best: dict[str, tuple[int, dict[str, Any]]] = {}

    def offer(family: str, score: int, payload: dict[str, Any]) -> None:
        if not family:
            return
        current = best.get(family)
        if current is None or score > current[0]:
            best[family] = (score, payload)

    for clause in clauses:
        kind = str(clause.get("kind") or "")
        if kind in SKIP_CLAUSE_KINDS:
            continue
        fields = clause.get("fields") or {}
        method = _clean((fields.get("method_standard") or {}).get("raw"))
        if not method:
            continue
        title = _clean(clause.get("title"))
        text = _clean(clause.get("text"))
        family = _family(title)
        score = 40 if family else 0
        if not family:
            family = _family(text)
            score = 20
        offer(
            family,
            score,
            {
                "method": method,
                "source": "clause",
                "clause_id": str(clause.get("clause_id") or ""),
                "page_no": int(clause.get("page_no") or 0),
                "quote": _clean(f"{title} {text}")[:200],
            },
        )
    for reference in references:
        family = _family(reference.get("title") or "")
        if not family:
            continue
        score = 30 if reference.get("relation") == "normative" else 10
        offer(
            family,
            score,
            {
                "method": reference["standard_no"],
                "source": reference.get("source") or "reference",
                "clause_id": reference.get("clause_id") or "",
                "page_no": int(reference.get("page_no") or 0),
                "quote": (reference.get("title") or reference.get("raw") or "")[:200],
            },
        )
    return {family: payload for family, (_, payload) in sorted(best.items())}


def extract_references(
    ocr: dict[str, Any],
    clauses_payload: dict[str, Any],
    inspections: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    clauses = clauses_payload.get("clauses") or []
    normative = _normative_entries(_pages(ocr))
    entries = _merge(
        [*normative, *_clause_entries(clauses), *_table_entries(inspections or [])]
    )
    normative_index = {
        entry["standard_no"] for entry in entries if entry["relation"] == "normative"
    }
    for entry in entries:
        if entry["relation"] != "normative":
            entry["resolved"] = entry["standard_no"] in normative_index
    entries.sort(
        key=lambda item: (
            -RELATION_PRIORITY.get(str(item.get("relation")), 0),
            str(item.get("standard_no")),
        )
    )
    unresolved = [entry for entry in entries if not entry.get("resolved")]
    bindings = _bindings(entries, clauses)
    return {
        "schema_version": SCHEMA_VERSION,
        "references": entries,
        "unresolved": [
            {
                "standard_no": entry["standard_no"],
                "edition": entry.get("edition") or "",
                "relation": entry.get("relation") or "",
                "clause_id": entry.get("clause_id") or "",
                "page_no": entry.get("page_no") or 0,
            }
            for entry in unresolved
        ],
        "bindings": bindings,
        "stats": {
            "total": len(entries),
            "normative": len(normative_index),
            "citations": sum(
                1 for entry in entries if entry["relation"] != "normative"
            ),
            "unresolved": len(unresolved),
            "resolution_rate": round(
                (len(entries) - len(unresolved)) / len(entries), 4
            )
            if entries
            else 0.0,
            "bindings": len(bindings),
        },
    }
