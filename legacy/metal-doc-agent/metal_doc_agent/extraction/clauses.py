"""Deterministic clause extraction from OCR markdown.

Clauses are heading-delimited blocks. The extractor keeps the clause id/title,
classifies the clause kind, and pulls the common field sentences used by the
golden set (requirement / direction / sample_quantity / sample_location).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..contracts import ClauseRecord, DocumentMeta, Evidence, ExtractedValue, Page
from ..tablegrid.normalize import clean_text

TABLE_RE = re.compile(r"<table\b.*?</table>", re.IGNORECASE | re.DOTALL)
HEADING_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?"
    r"(?P<id>[A-Z](?:\.\s*\d{1,3}){1,4}"
    r"|\d{1,2}(?:\.\s*\d{1,3}){1,4}"
    r"|\d{1,2}(?=\s))"
    r"\.?(?:\s+|(?=[\u4e00-\u9fff])|$)(?P<title>.*)$"
)
PAGE_RE = re.compile(r"^\s*#\s*Page\s+\d+\s*$", re.IGNORECASE)
TABLE_CAPTION_RE = re.compile(r"^(?:续)?表\s*\d+")
# Table-of-contents lines are headings followed by dot leaders and a page
# number. They shadow the real clause body because clause ids are deduplicated
# on first sight, so they are skipped before block assembly.
TOC_ENTRY_RE = re.compile(r"(?:\.{3,}|…{2,}|·{3,})\s*\d+\s*$")
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
STD_RE = re.compile(
    r"(?:GB/T|GB|GJB|JB/T|YB/T|NB/T|HB|ASTM|ISO|AMS|Q/[A-Za-z]+)"
    r"\s*[A-Z]?\s*[0-9.\-]+",
    re.IGNORECASE,
)
APPENDIX_REF_RE = re.compile(r"按\s*附\s*录\s*([A-Z])")
TEMPERATURE_RE = re.compile(
    r"(?:试验温度|温度)\s*[:：为]?\s*(?P<value>[−\-]?\d+(?:\.\d+)?\s*℃|室温|高温|低温)"
)
SAMPLING_LOCATION_RE = re.compile(
    r"(?:在|于)(?P<loc>[^。；;]{2,40}?)(?:切取|截取|取样)"
)
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


@dataclass
class ClauseOutput:
    clauses: list[ClauseRecord] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)


def extract_clauses(pages: list[Page], document: DocumentMeta) -> ClauseOutput:
    output = ClauseOutput()
    seen: dict[str, ClauseRecord] = {}
    for page in pages:
        text = TABLE_RE.sub("\n", page.markdown)
        blocks = _reassign_leading_bodies(_blocks(text))
        for clause_id, title, body in blocks:
            clause = _build_clause(clause_id, title, body, page.page_no, document, output.evidence)
            if clause is None:
                continue
            existing = seen.get(clause_id)
            if existing is not None:
                for key, value in clause.fields.items():
                    existing.fields.setdefault(key, value)
                for evidence_id in clause.evidence:
                    if evidence_id not in existing.evidence:
                        existing.evidence.append(evidence_id)
                continue
            seen[clause_id] = clause
            output.clauses.append(clause)
    return output


def _blocks(text: str) -> list[tuple[str, str, str]]:
    blocks: list[tuple[str, str, str]] = []
    current_id: str | None = None
    current_title = ""
    current_body: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or PAGE_RE.match(line):
            continue
        caption_line = line.strip("*").strip()
        if TABLE_CAPTION_RE.match(caption_line):
            continue
        if re.fullmatch(r"\d{1,3}", line):
            continue
        match = HEADING_RE.match(line)
        if match:
            clause_id = re.sub(r"\s+", "", match.group("id")).rstrip(".")
            title = clean_text(match.group("title"))
            if TOC_ENTRY_RE.search(title):
                # "3.5 低倍组织 ..... 3" is a contents entry, never a clause
                # body. Keeping it would shadow the real 3.5 heading later.
                continue
            if not _heading_is_valid(clause_id, title):
                if current_id is not None:
                    current_body.append(clean_text(line))
                continue
            if current_id is not None:
                blocks.append((current_id, current_title, " ".join(current_body)))
            current_id = clause_id
            current_title, inline_body = _split_inline_title(title)
            current_body = [inline_body] if inline_body else []
        elif current_id is not None:
            current_body.append(clean_text(line))
    if current_id is not None:
        blocks.append((current_id, current_title, " ".join(current_body)))
    return blocks


def _heading_is_valid(clause_id: str, title: str) -> bool:
    """Reject numbered list items that look like top-level headings.

    OCR emits list markers on their own line prefix (``1 类件应每批…``); only
    bare chapter numbers (``1 范围``) are headings, so sentence punctuation or a
    long run of text disqualifies the match.
    """
    if "." in clause_id:
        return True
    if not title or len(title) > 40:
        return False
    if any(marker in title for marker in "。；;，,"):
        return False
    return True


def _split_inline_title(title: str) -> tuple[str, str]:
    """Move a sentence glued to the clause id out of the title.

    Some OCR lines read ``5. 2.3.4.1 在…切取1个试样。``; the sentence is the
    clause body, not its title.
    """
    if "。" in title and len(title) >= 6:
        return "", title
    return title, ""


def _reassign_leading_bodies(
    blocks: list[tuple[str, str, str]]
) -> list[tuple[str, str, str]]:
    """Move leading sentences back to a previous heading that has no body.

    OCR occasionally emits two headings in a row and puts the first heading's
    sentence after the second one (e.g. 5.2.6.6 形状和尺寸 before 5.2.6.7 表面质量).
    """

    result = list(blocks)
    for index in range(len(result) - 1):
        prev_id, prev_title, prev_body = result[index]
        next_id, next_title, next_body = result[index + 1]
        if prev_body or not next_body or not prev_title or not next_title:
            continue
        parts = re.split(r"(?<=[。；;])", next_body)
        moved: list[str] = []
        while parts:
            part = parts[0].strip()
            if not part:
                parts.pop(0)
                continue
            if prev_title in part and next_title not in part:
                moved.append(part)
                parts.pop(0)
            else:
                break
        if moved:
            result[index] = (prev_id, prev_title, "".join(moved))
            result[index + 1] = (next_id, next_title, "".join(parts))
    return result


def _build_clause(
    clause_id: str,
    title: str,
    body: str,
    page_no: int,
    document: DocumentMeta,
    evidence_sink: list[Evidence],
) -> ClauseRecord | None:
    if not clause_id or (not title and not body):
        return None
    body_text = clean_text(body)
    title_text = clean_text(title)
    kind = _kind(title, body)
    fields: dict[str, ExtractedValue] = {}
    evidence_id = f"ev:{document.doc_id}:clause:{clause_id}"

    requirement_text = (
        body_text
        if any(marker in body_text for marker in REQUIREMENT_MARKERS)
        else title_text
    )
    requirement = _sentence(requirement_text, REQUIREMENT_MARKERS)
    if requirement and body_text:
        table_sentence = _sentence(
            body_text, ("表",), split_on_list=False
        )
        if (
            table_sentence
            and re.search(r"表\s*[A-Za-z]?\.?\s*\d", table_sentence)
            and table_sentence not in requirement
        ):
            # “检验结果满足表5-4 要求” carries the acceptance table reference;
            # without it the requirement cannot be resolved to the limits table.
            requirement = f"{requirement}；{table_sentence}"
    if requirement:
        fields["requirement"] = _value(requirement, evidence_id)
    direction_text = body_text or title_text
    precise_direction = _direction_term(f"{title_text} {body_text}")
    if precise_direction:
        fields["direction"] = _value(precise_direction, evidence_id)
    elif not direction_text.startswith("表") and "## Table" not in direction_text:
        direction = _sentence(
            direction_text, ("取横向", "取纵向", "方向"), split_on_list=False
        )
        if direction:
            fields["direction"] = _value(_direction_text(direction), evidence_id)
    if "取样数量" in title or "试样数量" in title or "取样数量" in body:
        sentence = _sentence(body_text or title_text, ("取样数量", "试样数量", "每批", "取样"))
        if sentence:
            fields["sample_quantity"] = _value(sentence, evidence_id)
    if "sample_quantity" not in fields and kind not in {
        "scope",
        "normative_reference",
        "terms",
    }:
        frequency = SAMPLING_FREQUENCY_RE.search(f"{title_text} {body_text}")
        if frequency:
            fields["sample_quantity"] = _value(frequency.group(1), evidence_id)
    if "取样位置" in title or ("取样" in title and "数量" not in title):
        sentence = _sentence(
            body_text or title_text,
            ("图", "头", "尾", "端", "部位", "按GB/T", "取样"),
            split_on_list=False,
        )
        if sentence:
            fields["sample_location"] = _value(_sample_location_text(sentence), evidence_id)
    if "sample_location" not in fields and kind not in {
        "scope",
        "normative_reference",
        "terms",
    }:
        located = SAMPLING_LOCATION_RE.search(f"{title_text} {body_text}")
        if located:
            fields["sample_location"] = _value(clean_text(located.group("loc")), evidence_id)
    if "sample_quantity" not in fields and kind not in {
        "scope",
        "normative_reference",
        "terms",
    }:
        quantity_match = SAMPLING_QUANTITY_RE.search(f"{title_text} {body_text}")
        if quantity_match:
            fields["sample_quantity"] = _value(
                f"{quantity_match.group('qty')}{quantity_match.group('unit')}",
                evidence_id,
            )

    method = _method_standard(body_text or title_text, kind)
    if method:
        fields["method_standard"] = _value(method, evidence_id)
    temperature = TEMPERATURE_RE.search(f"{title_text} {body_text}")
    if temperature:
        fields["test_temperature"] = _value(
            temperature.group("value").strip(), evidence_id
        )
    judgment = _sentence(body_text, ("判为不合格", "合格"), split_on_list=False)
    if judgment:
        fields["judgment"] = _value(judgment, evidence_id)

    if not fields:
        if not body_text:
            return ClauseRecord(
                clause_id=clause_id,
                title=title_text or None,
                page_no=page_no,
                kind=kind,
                fields={},
                evidence=[],
                status="found",
            )
        fields["text"] = _value(body_text, evidence_id)

    if not any(item.evidence_id == evidence_id for item in evidence_sink):
        evidence_sink.append(
            Evidence(
                evidence_id=evidence_id,
                page_no=page_no,
                table_id=None,
                row=None,
                col=None,
                quote=next(iter(fields.values())).raw,
                artifact_uri="pages.json",
            )
        )
    return ClauseRecord(
        clause_id=clause_id,
        title=title_text or None,
        page_no=page_no,
        kind=kind,
        fields=fields,
        evidence=[evidence_id],
        status="found",
    )


def _value(raw: str, evidence_id: str) -> ExtractedValue:
    return ExtractedValue(
        raw=raw,
        text=raw,
        comparator="text",
        evidence_id=evidence_id,
    )


def _method_standard(text: str, kind: str) -> str | None:
    if kind in {"scope", "normative_reference", "terms"}:
        return None
    appendix = APPENDIX_REF_RE.search(text)
    if appendix:
        return f"附录{appendix.group(1)}"
    if "按" not in text and kind != "test_method":
        return None
    normalized = re.sub(r"-\s+(?=\d)", "-", text)
    match = STD_RE.search(normalized)
    return re.sub(r"\s+", "", match.group(0)) if match else None


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
) -> str | None:
    pattern = r"(?<=[。])" if not split_on_list else r"(?<=[。；;])"
    parts = [part.strip() for part in re.split(pattern, text) if part.strip()]
    for part in parts:
        if any(keyword in part for keyword in keywords):
            return part
    return None


def _direction_text(sentence: str) -> str:
    text = sentence.replace("对于", "")
    text = re.sub(r"[，,]\s*拉伸试验取", "取", text)
    text = text.replace("拉伸试验取", "取")
    text = text.replace("的取", "取")
    text = text.replace("试样", "")
    return text.rstrip("。")


def _direction_term(text: str) -> str | None:
    """Pick the sampling direction from clauses phrased without ``取…``."""
    if not any(
        marker in text for marker in ("拉伸", "力学性能", "取样", "试样", "方向")
    ):
        return None
    paired = DIRECTION_PAREN_RE.search(text)
    if paired:
        return f"{paired.group(1)}（{paired.group('extra')}）"
    terms = [term for term in DIRECTION_TERMS if term in text]
    return terms[0] if len(terms) == 1 else None


def _sample_location_text(sentence: str) -> str:
    text = re.sub(r"^.*?[:：]\s*", "", sentence, count=1)
    text = re.sub(r"[a-dA-D][)）]\s*", "", text)
    text = text.replace("对于", "")
    text = re.sub(r"[，,]\s*按", "按", text)
    text = re.sub(r"的规定", "", text)
    text = re.sub(r"\s*([；;，,。])\s*", r"\1", text)
    return clean_text(text.rstrip("。"))
