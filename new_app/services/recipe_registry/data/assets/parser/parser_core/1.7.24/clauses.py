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
from html import unescape
from typing import Any

try:  # imported as a package (tests)
    from .builtin import _normalize_doc_text, _standard_numbers
except ImportError:  # flat runtime image (/engine)
    from builtin import _normalize_doc_text, _standard_numbers

SCHEMA_VERSION = "document-clauses/1"
TABLE_RE = re.compile(r"<table\b.*?</table>", re.IGNORECASE | re.DOTALL)
TABLE_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
TABLE_CELL_RE = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.IGNORECASE | re.DOTALL)
TABLE_HEADING_ID_RE = re.compile(
    r"^(?:\d{1,2}(?:\.\s*\d{1,3}){1,4}|[A-Z](?:\.\s*\d{1,3}){1,4})$"
)


def _table_heading_lines(table_html: str) -> list[str]:
    """Recover clause headings that OCR wrapped in a one-row table.

    GLM-OCR often prints ``5.5 β转变温度`` as ``<table><tr><td>5.5</td>
    <td>β</td><td>转变温度</td></tr></table>``.  Replacing the whole table with
    a newline would drop the heading and every requirement under it.
    """
    rows = TABLE_ROW_RE.findall(table_html)
    if not rows or len(rows) > 3:
        return []
    lines: list[str] = []
    for row in rows:
        cells = [
            re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", cell))).strip()
            for cell in TABLE_CELL_RE.findall(row)
        ]
        cells = [cell for cell in cells if cell]
        if len(cells) < 2:
            continue
        clause_id = re.sub(r"\s+", "", cells[0]).rstrip(".")
        if not TABLE_HEADING_ID_RE.fullmatch(clause_id):
            continue
        title = " ".join(cells[1:]).strip()
        # 数据行“5.5 | 4.0 | 5.0”不是标题。
        if not title or re.fullmatch(r"[\d.,%≤≥~\-\s]+", title):
            continue
        lines.append(f"{clause_id} {title}")
    return lines


def _table_to_text(match: re.Match[str]) -> str:
    lines = _table_heading_lines(match.group(0))
    return ("\n".join(lines) + "\n") if lines else "\n"


PAGE_RE = re.compile(r"^\s*#\s*Page\s+\d+\s*$", re.IGNORECASE)
TABLE_CAPTION_RE = re.compile(r"^(?:续)?表\s*\d+")
TOC_ENTRY_RE = re.compile(r"(?:\.{3,}|…{2,}|·{3,})\s*\d+\s*$")
HEADING_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?"
    r"(?P<id>[A-Z](?:\.\s*\d{1,3}){1,4}"
    r"|\d{1,2}(?:\.\s*\d{1,3}){1,4}"
    # ASTM/ISO print top-level headings as "6. Chemical Requirements".
    r"|\d{1,2}\.(?=\s)"
    r"|\d{1,2}(?=\s))"
    r"\.?(?:\s+|(?=[\u4e00-\u9fff])|$)(?P<title>.*)$"
)
# GJB 的 OCR 常把子条款写成“3.5 , 1 锻件流线……”。
OCR_CLAUSE_COMMA_RE = re.compile(
    r"^(?P<id>\d{1,2}(?:\.\s*\d{1,3})+)\s*[,，]\s*(?P<sub>\d{1,3})(?=\s|[\u4e00-\u9fff])"
)
# ". " 只在下一个句子以大写字母/引号/括号开头时断句；否则
# “不低于4. 0级”“ASTM No. 5”这类小数/编号会被截断。
SENTENCE_SPLIT_RE = re.compile(r"(?<=[。；;])|(?<=[.!?])\s+(?=[A-Z\"'“‘(（])")
SENTENCE_SPLIT_STRICT_RE = re.compile(r"(?<=[。])|(?<=[.!?])\s+(?=[A-Z\"'“‘(（])")
CJK_GAP_RE = re.compile(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])")
DECIMAL_GAP_RE = re.compile(r"(?<=\d)\.\s+(?=\d)")
METHOD_CUE_RE = re.compile(
    r"按|见|符合|执行|依据|遵守|遵照|采用|引用"
    r"|in\s+accordance\s+with|according\s+to|per\b|conform(?:s|ing)?\s+to"
    r"|comply\s+with|specified\s+in|referenced\s+in",
    re.IGNORECASE,
)
_EN_TITLE_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "that",
    "this",
    "these",
    "those",
    "shall",
    "should",
    "must",
    "may",
    "are",
    "was",
    "were",
    "which",
    "their",
    "than",
    "into",
    "when",
    "other",
    "such",
    "each",
    "requirements",
    "requirement",
}
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
    "可按",
    "可提供",
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
    r"同一炉|同一批|逐件|逐批|全检|抽检"
    r"|each\s+(?:heat|lot|plate|bar|forging|cast|batch|coil|piece)"
    r"|per\s+(?:heat|lot|plate|bar|forging|batch|coil|piece)"
    r"|every\s+(?:heat|lot|plate|bar|forging|batch))",
    re.IGNORECASE,
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
    # OCR 常把中文词拆成“晶 间腐蚀”，也会把“4. 0级”拆开；先还原再压缩空白。
    value = DECIMAL_GAP_RE.sub(".", value)
    value = CJK_GAP_RE.sub("", value)
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
        text = TABLE_RE.sub(_table_to_text, markdown)
        for raw_line in text.splitlines():
            # OCR often prints full-width digits/punctuation (６．１).  NFKC
            # makes headings and standard numbers match the ASCII patterns.
            line = unicodedata.normalize("NFKC", raw_line).strip()
            if not line or PAGE_RE.match(line):
                continue
            # “3.5 , 1 锻件流线……”还原为标准子条款号“3.5.1”。
            comma_match = OCR_CLAUSE_COMMA_RE.match(line)
            if comma_match:
                clause_id = re.sub(r"\s+", "", comma_match.group("id"))
                line = f"{clause_id}.{comma_match.group('sub')}{line[comma_match.end():]}"
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
    if not title:
        return False
    # A bare page number ("2 6") is not a clause heading.
    if re.fullmatch(r"[\d\s]+", title):
        return False
    if any(marker in title for marker in "。；;，") or title.endswith("."):
        return False
    if re.search(r"[A-Za-z]", title):
        # "8. Workmanship, Finish, and Appearance" is a heading; a long
        # sentence such as "10 This specification covers..." is not.
        if len(title) > 80:
            return False
        if len(title) > 30 and re.search(
            r"\b(?:shall|should|must|is|are|was|were|has|have)\b", title, re.I
        ):
            return False
        return True
    return len(title) <= 40


def _split_inline_title(title: str) -> tuple[str, str]:
    if "。" in title and len(title) >= 6:
        return "", title
    # "3.2.1 Plate shall receive no further straightening..." is a requirement
    # sentence that OCR kept on the heading line, not a clause title.
    if len(title) >= 30 and re.search(r"\b(?:shall|should|must)\b", title, re.I):
        return "", title
    if re.match(
        r"^(?:perform|determine|measure|test|inspect|examine|use|report|conduct)\b",
        title,
        re.I,
    ):
        return "", title
    if re.search(r"\b(?:is|are)\s+(?:not\s+)?permitted\b", title, re.I):
        return "", title
    if title.endswith(".") and len(title) >= 60:
        return "", title
    return title, ""


def _title_tokens(title: str) -> list[str]:
    tokens: list[str] = []
    for raw in re.split(r"[\s,，、;；:：/()（）\[\].\-—–]+", title):
        token = raw.strip().lower()
        if not token:
            continue
        if re.fullmatch(r"[a-z]+", token):
            if len(token) >= 4 and token not in _EN_TITLE_STOPWORDS:
                tokens.append(token)
        elif re.fullmatch(r"[\u4e00-\u9fff]+", token):
            tokens.append(token)
            if len(token) >= 4:
                tokens.extend((token[:2], token[-2:]))
    return [token for token in tokens if token]


def _requirement_sentence(text: str, title: str) -> str:
    parts = [
        part
        for part in (chunk.strip() for chunk in SENTENCE_SPLIT_RE.split(text))
        if part
    ]
    candidates = [
        part
        for part in parts
        if any(marker in part.lower() for marker in REQUIREMENT_MARKERS)
        or re.match(
            r"^(?:perform|determine|measure|test|inspect|examine|use|report|conduct)\b",
            part,
            re.I,
        )
    ]
    if not candidates:
        return ""
    tokens = _title_tokens(title)
    for part in candidates:
        lowered = part.lower()
        if tokens and any(token in lowered for token in tokens):
            return part
    return candidates[0]


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
    lower = title.lower()
    stripped = lower.strip(" .:：")
    if "范围" in title or stripped == "scope":
        return "scope"
    if (
        "规范性引用文件" in title
        or "引用文件" in title
        or "normative reference" in lower
        or "referenced document" in lower
        or re.fullmatch(r"(?:applicable\s+)?documents?", stripped)
    ):
        return "normative_reference"
    if (
        "术语" in title
        or "terms and definitions" in lower
        or stripped in {"definitions", "terms"}
    ):
        return "terms"
    if "取样数量" in title or "试样数量" in title:
        return "inspection"
    if "取样" in title or "sampling" in lower:
        return "sampling"
    if (
        any(marker in title for marker in ("试验方法", "检验方法", "方向", "试验温度"))
        or "test methods" in lower
        or stripped in {"testing", "test method"}
    ):
        return "test_method"
    if (
        ("检验" in title and ("数量" in title or "项目" in title))
        or "inspection" in lower
        or "acceptance tests" in lower
        or "classification of tests" in lower
    ):
        return "inspection"
    if (
        "包装" in title
        or "packag" in lower
        or "packing" in lower
        or "marking" in lower
        or "identification" in lower
    ):
        return "packaging"
    if (
        "交货" in title
        or "订货" in title
        or "delivery" in lower
        or "ordering information" in lower
        or "purchase documents" in lower
    ):
        return "delivery"
    if (
        any(marker in text for marker in ("应符合", "应按", "技术要求"))
        or title.strip() in {"要求", "技术条件"}
        or "technical requirements" in lower
        or stripped in {"requirements", "technical requirements"}
        or any(
            marker in lower
            for marker in (
                "quality",
                "tolerances",
                "properties",
                "composition",
                "condition",
                "heat treatment",
                "microstructure",
                "workmanship",
                "dimensions",
            )
        )
        or re.search(r"\b(?:shall|should|must|is required|are required)\b", text, re.I)
    ):
        return "technical_requirement"
    return "other"


def _sentence(
    text: str, keywords: tuple[str, ...], split_on_list: bool = True
) -> str:
    pattern = SENTENCE_SPLIT_RE if split_on_list else SENTENCE_SPLIT_STRICT_RE
    for part in (item.strip() for item in pattern.split(text)):
        if part and any(keyword in part.lower() for keyword in keywords):
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
    if not METHOD_CUE_RE.search(text) and kind != "test_method":
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

    requirement_text = (
        body
        if any(marker in body.lower() for marker in REQUIREMENT_MARKERS)
        or re.match(
            r"^(?:perform|determine|measure|test|inspect|examine|use|report|conduct)\b",
            body,
            re.I,
        )
        else title
    )
    requirement = _requirement_sentence(requirement_text, title)
    if requirement and body:
        table_sentence = _sentence(body, ("表", "Table"), split_on_list=False)
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
        # OCR sometimes prints an unrelated paragraph with an already used
        # clause number ("5.2" for a 5.1 bullet list).  Merging fields there
        # contaminates the real clause, so keep it as a distinct clause.
        if (
            existing is not None
            and (
                not existing.get("title")
                or not clause.get("title")
                or _clean(existing["title"]) == _clean(clause["title"])
            )
        ):
            for key, value in clause["fields"].items():
                existing["fields"].setdefault(key, value)
            for item in clause["evidence"]:
                if item["evidence_id"] not in {
                    entry["evidence_id"] for entry in existing["evidence"]
                }:
                    existing["evidence"].append(item)
            continue
        if existing is not None:
            suffix = 2
            while f"{clause['clause_id']}-{suffix}" in seen:
                suffix += 1
            clause["clause_id"] = f"{clause['clause_id']}-{suffix}"
            for item in clause["evidence"]:
                item["evidence_id"] = f"ev-clause-{clause['clause_id']}"
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
