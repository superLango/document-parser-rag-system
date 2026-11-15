"""Deterministic clause extraction from OCR markdown.

Standard library only: this file is copied into the sandbox runtime image.

Clauses are heading-delimited blocks.  The extractor keeps the clause id/title,
classifies the clause kind, and pulls the requirement / direction / sampling /
method fields used by the item inventory and the final projection layer.  Every
field keeps an evidence id so the web UI can trace it back to the page text.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

try:  # imported as a package (tests)
    from .builtin import _normalize_doc_text, _standard_numbers
except ImportError:  # flat runtime image (/engine)
    from builtin import _normalize_doc_text, _standard_numbers

SCHEMA_VERSION = "document-clauses/1"
TABLE_RE = re.compile(r"<table\b.*?</table>", re.IGNORECASE | re.DOTALL)
PAGE_RE = re.compile(r"^\s*#\s*Page\s+\d+\s*$", re.IGNORECASE)
TABLE_CAPTION_RE = re.compile(r"^(?:续)?表\s*\d+")
TOC_ENTRY_RE = re.compile(r"(?:\.{3,}|…{2,}|·{3,})\s*\d+\s*$")
HEADING_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?"
    r"(?P<id>[A-Z](?:\.\s*\d{1,3}){1,4}"
    r"|\d{1,2}(?:\.\s*\d{1,3}){1,4}"
    r"|\d{1,2}(?=\s))"
    r"\.?(?:\s+|(?=[\u4e00-\u9fff])|$)(?P<title>.*)$"
)
REQUIREMENT_MARKERS = (
    "应符合",
    "应按",
    "按照",
    "应不",
    "应在",
    "应经",
    "应附",
    "应进行",
    "应检验",
    "应检测",
    "应测量",
    "应逐",
    "应打",
    "应采用",
    "应注明",
    "应满足",
    "应保证",
    "应均匀",
    "应完整",
    "应填写",
    "应清楚",
    "应供",
    "可采用",
    "不允许",
    "不得",
    "不准",
    "不应",
    "禁止",
    "应无",
    "需记录",
    "shall",
    "should",
    "must",
    "is required",
    "are required",
    "not permitted",
    "prohibited",
)
APPENDIX_REF_RE = re.compile(r"按\s*附\s*录\s*([A-Z])")
TEMPERATURE_RE = re.compile(
    r"(?:试验温度|温度)\s*[:：为]?\s*(?P<value>[−\-]?\d+(?:\.\d+)?\s*℃|室温|高温|低温)"
)
SAMPLING_LOCATION_RE = re.compile(r"(?:在|于)(?P<loc>[^。；;]{2,40}?)(?:切取|截取|取样)")
SAMPLING_QUANTITY_RE = re.compile(
    r"(?:切取|截取|取样|抽取)\s*"
    r"(?P<qty>[一二两三四五六七八九十\d]+(?:\.\d+)?)\s*"
    r"(?P<unit>个|件|支|根|块|张|组)"
)
SAMPLING_FREQUENCY_RE = re.compile(
    r"(每一?锻件|每张钢板|每炉钢?液?|每批|每件|每根|每支|"
    r"同一炉|同一批|逐件|逐批|全检|抽检)"
)
DIRECTION_TERMS = (
    "垂直流线方向",
    "顺流线方向",
    "纵向",
    "横向",
    "弦向",
    "径向",
    "切向",
    "轴向",
)
DIRECTION_PAREN_RE = re.compile(r"(横向|纵向)\s*[（(](?P<extra>[^）)]{1,6})[）)]")
BODY_LIMIT = 1600
REQUIREMENT_LIMIT = 400

SKIP_KINDS = {"scope", "normative_reference", "terms"}


def _clean(text: Any) -> str:
    value = _normalize_doc_text(text)
    return re.sub(r"\s+", " ", value).strip()


def _document_pages(ocr: dict[str, Any]) -> list[tuple[int, str]]:
    pages: list[tuple[int, str]] = []
    for index, page in enumerate(ocr.get("pages") or [], start=1):
        if not isinstance(page, dict):
            continue
        markdown = str(page.get("markdown") or "")
        if not markdown.strip():
            continue
        pages.append((int(page.get("page_no") or index), markdown))
    if pages:
        return pages
    markdown = str(ocr.get("markdown") or "")
    return [(0, markdown)] if markdown.strip() else []


def _blocks(pages: list[tuple[int, str]]) -> list[dict[str, Any]]:
    """Split every page into heading-delimited blocks.

    Continuation text on a later page still belongs to the clause opened on the
    previous page, so blocks are merged across page boundaries instead of being
    dropped with each page reset.
    """
    blocks: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for page_no, markdown in pages:
        text = TABLE_RE.sub("\n", markdown)
        for raw_line in text.splitlines():
            # OCR often prints full-width digits/punctuation (６．１).  NFKC
            # makes headings and standard numbers match the ASCII patterns.
            line = unicodedata.normalize("NFKC", raw_line).strip()
            if not line or PAGE_RE.match(line):
                continue
            caption = line.strip("*").strip()
            if TABLE_CAPTION_RE.match(caption):
                continue
            if re.fullmatch(r"\d{1,3}", line):
                continue
            match = HEADING_RE.match(line)
            if match:
                clause_id = unicodedata.normalize(
                    "NFKC", re.sub(r"\s+", "", match.group("id"))
                ).rstrip(".")
                title = _clean(match.group("title"))
                if TOC_ENTRY_RE.search(title):
                    # "3.5 低倍组织 ..... 3" is a contents entry, not a clause.
                    continue
                if not _heading_is_valid(clause_id, title):
                    if current is not None:
                        current["body"].append(caption)
                    continue
                if current is not None:
                    blocks.append(current)
                current = {
                    "clause_id": clause_id,
                    "title": "",
                    "body": [],
                    "page_no": page_no,
                }
                current["title"], inline_body = _split_inline_title(title)
                if inline_body:
                    current["body"].append(inline_body)
            elif current is not None:
                current["body"].append(caption)
    if current is not None:
        blocks.append(current)
    return blocks


def _heading_is_valid(clause_id: str, title: str) -> bool:
    if "." in clause_id:
        return True
    if not title or len(title) > 40:
        return False
    if any(marker in title for marker in "。；;，,"):
        return False
    return True


def _split_inline_title(title: str) -> tuple[str, str]:
    if "。" in title and len(title) >= 6:
        return "", title
    return title, ""


def _reassign_leading_bodies(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Move leading sentences back to a previous heading that has no body."""
    result = [dict(block, body=list(block["body"])) for block in blocks]
    for index in range(len(result) - 1):
        prev = result[index]
        nxt = result[index + 1]
        prev_body = " ".join(prev["body"]).strip()
        next_body = " ".join(nxt["body"]).strip()
        if prev_body or not next_body or not prev["title"] or not nxt["title"]:
            continue
        parts = re.split(r"(?<=[。；;])", next_body)
        moved: list[str] = []
        while parts:
            part = parts[0].strip()
            if not part:
                parts.pop(0)
                continue
            if prev["title"] in part and nxt["title"] not in part:
                moved.append(part)
                parts.pop(0)
            else:
                break
        if moved:
            prev["body"] = ["".join(moved)]
            nxt["body"] = ["".join(parts)]
    return result


def _kind(title: str, body: str) -> str:
    text = f"{title} {body}"
    if "范围" in title:
        return "scope"
    if "规范性引用文件" in title:
        return "normative_reference"
    if "术语" in title:
        return "terms"
    if "取样数量" in title or "试样数量" in title:
        return "inspection"
    if "取样" in title:
        return "sampling"
    if any(marker in title for marker in ("试验方法", "检验方法", "方向", "试验温度")):
        return "test_method"
    if "检验" in title and ("数量" in title or "项目" in title):
        return "inspection"
    if "包装" in title:
        return "packaging"
    if "交货" in title:
        return "delivery"
    if any(marker in text for marker in ("应符合", "应按", "技术要求")):
        return "technical_requirement"
    return "other"


def _sentence(
    text: str, keywords: tuple[str, ...], split_on_list: bool = True
) -> str:
    pattern = r"(?<=[。；;])" if split_on_list else r"(?<=[。])"
    for part in (item.strip() for item in re.split(pattern, text)):
        if part and any(keyword in part for keyword in keywords):
            return part
    return ""


def _direction_term(text: str) -> str:
    if not any(
        marker in text for marker in ("拉伸", "力学性能", "取样", "试样", "方向")
    ):
        return ""
    paired = DIRECTION_PAREN_RE.search(text)
    if paired:
        return f"{paired.group(1)}（{paired.group('extra')}）"
    terms = [term for term in DIRECTION_TERMS if term in text]
    return terms[0] if len(terms) == 1 else ""


def _method_standard(text: str, kind: str) -> str:
    if kind in SKIP_KINDS:
        return ""
    appendix = APPENDIX_REF_RE.search(text)
    if appendix:
        return f"附录{appendix.group(1)}"
    if "按" not in text and kind != "test_method":
        return ""
    numbers = _standard_numbers(text)
    return numbers[0] if numbers else ""


def _value(raw: str, evidence_id: str) -> dict[str, str]:
    return {"raw": raw, "evidence_id": evidence_id}


def _build_clause(
    block: dict[str, Any], evidence_id: str
) -> dict[str, Any] | None:
    clause_id = str(block.get("clause_id") or "")
    title = _clean(block.get("title"))
    body = _clean(" ".join(block.get("body") or ""))
    if not clause_id or (not title and not body):
        return None
    kind = _kind(title, body)
    fields: dict[str, dict[str, str]] = {}

    requirement_text = body if any(m in body for m in REQUIREMENT_MARKERS) else title
    requirement = _sentence(requirement_text, REQUIREMENT_MARKERS)
    if requirement and body:
        table_sentence = _sentence(body, ("表",), split_on_list=False)
        if (
            table_sentence
            and re.search(r"表\s*[A-Za-z]?\.?\s*\d", table_sentence)
            and table_sentence not in requirement
        ):
            requirement = f"{requirement}；{table_sentence}"
    if requirement:
        fields["requirement"] = _value(requirement[:REQUIREMENT_LIMIT], evidence_id)

    direction = _direction_term(f"{title} {body}")
    if direction:
        fields["direction"] = _value(direction, evidence_id)

    if "取样数量" in title or "试样数量" in title or "取样数量" in body:
        sentence = _sentence(body or title, ("取样数量", "试样数量", "每批", "取样"))
        if sentence:
            fields["sample_quantity"] = _value(sentence, evidence_id)
    if "sample_quantity" not in fields and kind not in SKIP_KINDS:
        frequency = SAMPLING_FREQUENCY_RE.search(f"{title} {body}")
        if frequency:
            fields["sample_quantity"] = _value(frequency.group(1), evidence_id)

    if "取样位置" in title or ("取样" in title and "数量" not in title):
        sentence = _sentence(
            body or title, ("图", "头", "尾", "端", "部位", "按GB/T", "取样"), False
        )
        if sentence:
            fields["sample_location"] = _value(sentence, evidence_id)
    if "sample_location" not in fields and kind not in SKIP_KINDS:
        located = SAMPLING_LOCATION_RE.search(f"{title} {body}")
        if located:
            fields["sample_location"] = _value(located.group("loc").strip(), evidence_id)

    if "sample_quantity" not in fields and kind not in SKIP_KINDS:
        quantity = SAMPLING_QUANTITY_RE.search(f"{title} {body}")
        if quantity:
            fields["sample_quantity"] = _value(
                f"{quantity.group('qty')}{quantity.group('unit')}", evidence_id
            )

    method = _method_standard(body or title, kind)
    if method:
        fields["method_standard"] = _value(method, evidence_id)

    temperature = TEMPERATURE_RE.search(f"{title} {body}")
    if temperature:
        fields["test_temperature"] = _value(
            temperature.group("value").strip(), evidence_id
        )

    judgment = _sentence(body, ("判为不合格", "合格"), split_on_list=False)
    if judgment:
        fields["judgment"] = _value(judgment, evidence_id)

    return {
        "clause_id": clause_id,
        "title": title,
        "kind": kind,
        "page_no": int(block.get("page_no") or 0),
        "text": body[:BODY_LIMIT],
        "fields": fields,
        "evidence": (
            [
                {
                    "evidence_id": evidence_id,
                    "page_no": int(block.get("page_no") or 0),
                    "quote": next(iter(fields.values()))["raw"],
                }
            ]
            if fields
            else []
        ),
    }


def extract_clauses(ocr: dict[str, Any]) -> dict[str, Any]:
    """Return the versioned clause payload for one OCR document."""
    seen: dict[str, dict[str, Any]] = {}
    clauses: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    evidence_ids: set[str] = set()
    for block in _reassign_leading_bodies(_blocks(_document_pages(ocr))):
        evidence_id = f"ev-clause-{block['clause_id']}"
        clause = _build_clause(block, evidence_id)
        if clause is None:
            continue
        existing = seen.get(clause["clause_id"])
        if existing is not None:
            for key, value in clause["fields"].items():
                existing["fields"].setdefault(key, value)
            for item in clause["evidence"]:
                if item["evidence_id"] not in {
                    entry["evidence_id"] for entry in existing["evidence"]
                }:
                    existing["evidence"].append(item)
            continue
        seen[clause["clause_id"]] = clause
        clauses.append(clause)
        for item in clause["evidence"]:
            if item["evidence_id"] not in evidence_ids:
                evidence_ids.add(item["evidence_id"])
                evidence.append(item)

    kinds: dict[str, int] = {}
    field_counts = {
        "requirement": 0,
        "direction": 0,
        "sample_quantity": 0,
        "sample_location": 0,
        "method_standard": 0,
        "test_temperature": 0,
    }
    for clause in clauses:
        kind = str(clause.get("kind") or "other")
        kinds[kind] = kinds.get(kind, 0) + 1
        for name in field_counts:
            if clause["fields"].get(name):
                field_counts[name] += 1
    return {
        "schema_version": SCHEMA_VERSION,
        "clauses": clauses,
        "evidence": evidence,
        "stats": {
            "clauses": len(clauses),
            "kinds": dict(sorted(kinds.items())),
            "fields": field_counts,
        },
    }
