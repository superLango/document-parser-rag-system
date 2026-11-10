"""Document ingestion and page splitting.

``.md`` input is split into pages by ``# Page N`` markers. ``.pdf`` input only
builds document metadata here; rasterization and page OCR belong to the OCR
adapter, so PDF ingestion returns no pages.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from .contracts import DocumentMeta, Page

PAGE_RE = re.compile(
    r"^(?:#\s*Page\s+(\d+)|<!--\s*page:\s*(\d+)\s*-->)\s*$",
    re.MULTILINE | re.IGNORECASE,
)
# Technical agreements carry their own document number instead of a national
# standard number. It is the identity users search by, so it becomes the
# standard_no fallback when no GB/GJB/Q number exists.
FILE_NUMBER_RE = re.compile(
    r"(?:文件编号|文档编号|文件号|文档号)\s*[:：]?\s*"
    r"([A-Za-z0-9][A-Za-z0-9._/\-]{2,})",
    re.IGNORECASE,
)
HEADING_RE = re.compile(r"^#{1,3}\s+(.+?)\s*$", re.MULTILINE)
FILE_NUMBER_STEM_RE = re.compile(
    r"^[A-Z]{2,}[A-Z0-9]*(?:[-_][A-Z0-9]+){2,}$", re.IGNORECASE
)
STANDARD_PATTERNS = [
    (
        re.compile(r"GB\s*[/\-—]?\s*T\s*([0-9.]+)\s*[-—]\s*(\d{4})", re.IGNORECASE),
        "GB/T",
    ),
    (re.compile(r"GB\s*([0-9.]+)\s*[-—]\s*(\d{4})", re.IGNORECASE), "GB"),
    (re.compile(r"GJB\s*([0-9]+[A-Z]?)\s*[-—]\s*(\d{4})", re.IGNORECASE), "GJB"),
    (
        re.compile(r"Q\s*[/\-—]?\s*Du\s*([0-9.]+)\s*[-—]\s*(\d{4})", re.IGNORECASE),
        "Q/Du",
    ),
    (
        re.compile(
            r"Q\s*[/\-—]?\s*S\s*([0-9]+(?:[-—][0-9]+)?)\s*[-—]\s*(\d{4})",
            re.IGNORECASE,
        ),
        "Q/S",
    ),
    (re.compile(r"JX\s*[-—]\s*([0-9]+)\s*[-—]\s*(\d+)", re.IGNORECASE), "JX"),
    # International / foreign standards. Filenames and covers use several
    # separators (ISO 5832-3-2021, ASTM B348_B348M-25, ASME SB338-2025,
    # YST 1077-2015, NB-T 47019.8-2011, AWS A5.16-A5.16M-2023).
    (
        re.compile(r"ASME\s*([A-Z]{1,3}[0-9][A-Z0-9./\-]*)\s*[-—]\s*(\d{4})", re.IGNORECASE),
        "ASME",
    ),
    (
        re.compile(r"ASTM\s*([A-Z][0-9]+(?:[/_][A-Z]?[0-9]+[A-Z]?)*)\s*[-—]\s*(\d{2,4})", re.IGNORECASE),
        "ASTM",
    ),
    (
        re.compile(r"ISO\s*([0-9]+(?:[-.][0-9]+)*)\s*[-—]\s*(\d{4})", re.IGNORECASE),
        "ISO",
    ),
    (
        re.compile(r"AWS\s*([A-Z0-9.]+(?:[/\-][A-Z0-9.]+)*)\s*[-—]\s*(\d{4})", re.IGNORECASE),
        "AWS",
    ),
    (
        re.compile(r"HB\s*([0-9]+(?:\.[0-9]+)?)\s*[-—]\s*(\d{2,4})", re.IGNORECASE),
        "HB",
    ),
    (
        re.compile(r"NB\s*[-/]?\s*T\s*([0-9.]+)\s*[-—]\s*(\d{4})", re.IGNORECASE),
        "NB/T",
    ),
    (
        re.compile(r"YS\s*[-/]?\s*T\s*([0-9.]+)\s*[-—]\s*(\d{4})", re.IGNORECASE),
        "YS/T",
    ),
    (
        re.compile(r"YY\s*[-/]?\s*T\s*([0-9.]+)\s*[-—]\s*(\d{4})", re.IGNORECASE),
        "YY/T",
    ),
    (
        re.compile(r"YB\s*([0-9]+(?:\.[0-9]+)?)\s*[-—]\s*(\d{2,4})", re.IGNORECASE),
        "YB",
    ),
]
# AMS revisions use a trailing letter and no year (AMS4901V); SAE aerospace
# standards are bare numbers (AS4076).
AMS_STANDARD_RE = re.compile(r"(?<![A-Z])AMS\s*([0-9]{3,5}[A-Z]?)\b", re.IGNORECASE)
AS_STANDARD_RE = re.compile(r"(?<![A-Z])AS\s*([0-9]{3,5})\b", re.IGNORECASE)
GENERIC_FILE_NUMBER_RE = re.compile(r"[A-Z]{2,}[0-9]*(?:[-_][A-Z0-9]+)+")

TITLE_BOILERPLATE_RE = re.compile(
    r"^(?:"
    r"中华人民共和国[^\n，。;；]{0,30}标准|"
    r"中华[^，。;；\n]{0,12}标准|"
    r"国家(?:军用)?标准|行业标准|团体标准|企业标准|地方标准|国际标准|"
    r"ICS\b|CCS\b|代替|本标准|前言|目\s*次|引\s*言|"
    r"rationale|foreword|contents|table of contents|scope|"
    r"introduction|references|bibliography|international standard|"
    r"composition|nominal thickness|millimeters|mechanical properties|"
    r"properties|requirements|quality assurance|preparation for delivery|"
    r"sampling|tolerances|dimensions|tensile strength|yield strength|"
    r"elongation|reduction of area|hardness|number of|"
    r"需方单位|供方单位|编号\s*[:：]|注\s*[:：]|表\s*\d+|"
    r"代表签字|签字|签名|编制|审核|批准|会签|"
    r"applicable documents|superseding|issued|revised|reaffirmed|"
    r"a\s*erospace\s+material\s+specification|"
    r"copyright\b|all rights reserved|licensed to|sae international|"
    r"printed in|no reproduction|"
    r"\d+(?:\.\d+)*\.?\s+(?:scope|foreword|rationale|contents|"
    r"applicable documents|introduction|general)\b"
    r")",
    re.IGNORECASE,
)
CONNECTOR_TAIL_RE = re.compile(r"(?:for|of|and|&|—|-|、|与|及)$", re.IGNORECASE)
CONTINUATION_START_RE = re.compile(r"^[a-z(—\-–,;:]")
TITLE_VOCAB_RE = re.compile(
    "钢|铁|合金|钛|铝|铜|镍|镁|锌|管|棒|板|丝|带|箔|线|材|型|锻|铸|"
    "轧|焊|热|冷|耐|腐|蚀|不|锈|高|温|低|结|构|弹|簧|轴|承|工|具|模|"
    "标|准|技|术|规|范|条|件|试|验|方|法|分|类|尺|寸|外|形|重|量|要|求|"
    "检|验|包|装|标|志|优|质|特|殊|精|密|无|缝|压|力|容|器|锅|炉|船|舶|"
    "航|空|航|天|医|用|外|科|植|入|换|器"
)
SCOPE_TITLE_RE = re.compile(
    r"本(?:标准|条件|规范|文件)(?:规定|适用于|规定了|适用于制造)\s*(?:了)?\s*"
    r"([^，。；;：:\n]{2,50}?)"
    r"(?:的)?(?:尺寸|外形|技术要求|分类|代号|订货|要求|试验方法|"
    r"检验规则|标记|包装|范围|规范|条件|规定)"
)
SCOPE_SENTENCE_RE = re.compile(
    r"本(?:标准|条件|规范|文件)(?:规定|适用于)\s*(?:了)?\s*([^，。；;：:\n]{2,50})"
)
HTML_CELL_RE = re.compile(
    # Some SAE covers omit ``</td>``; stop at the next cell/row instead of
    # swallowing the real title into the metadata cell.
    r"<t[dh][^>]*colspan=[\"']?\d+[\"']?[^>]*>(.*?)(?=</t[dh]>|<t[dh][\s>]|</tr>)",
    re.IGNORECASE | re.DOTALL,
)
# ASTM PDFs use typographic ligatures in the cover title ("Speciﬁcation").
STANDARD_FOR_RE = re.compile(
    r"Standard\s+Speci(?:f|ﬁ)cation"
    r"\s+for\s+(?P<title>[A-Z][^\n]{4,180})",
    re.IGNORECASE,
)


def split_pages(text: str) -> list[Page]:
    matches = list(PAGE_RE.finditer(text))
    if not matches:
        return [Page(page_no=1, markdown=text.strip())]

    pages: list[Page] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        number = match.group(1) or match.group(2)
        pages.append(Page(page_no=int(number), markdown=text[start:end].strip()))
    return pages


def parse_standard_no(file_name: str) -> str | None:
    normalized = file_name.replace("∕", "/").replace("／", "/").replace(" ", "")
    for pattern, prefix in STANDARD_PATTERNS:
        match = pattern.search(normalized)
        if match:
            if prefix == "JX":
                return f"JX-{match.group(1)}-{match.group(2)}"
            number = match.group(1)
            if prefix in {"ASTM", "AWS"}:
                number = number.replace("_", "/")
            return f"{prefix} {number}-{match.group(2)}"
    match = AMS_STANDARD_RE.search(normalized)
    if match:
        return f"AMS {match.group(1).upper()}"
    match = AS_STANDARD_RE.search(normalized)
    if match:
        return f"AS {match.group(1)}"
    stem = Path(file_name).stem.replace(" ", "")
    if GENERIC_FILE_NUMBER_RE.fullmatch(stem) or FILE_NUMBER_STEM_RE.fullmatch(stem):
        return re.sub(r"^([A-Z]{2,})(\d)", r"\1 \2", stem)
    return None


def _clean_title(candidate: str) -> str:
    text = re.sub(r"<[^>]+>", " ", candidate)
    # ASTM OCR renders the cover footnote as a TeX-style superscript.
    text = re.sub(r"\$\s*\^\{?\d+\}?\s*\$", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" #-—\t,")
    # OCR often inserts a space between every Chinese character ("不 锈 钢 棒").
    text = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", text)
    # ASTM titles carry a footnote digit ("... Billets1").
    text = re.sub(r"(?<=[A-Za-z\)])\d{1,2}$", "", text).strip()
    return text


def _title_acceptable(text: str) -> bool:
    if not text or len(text) > 300:
        return False
    if text.startswith("```") or text.lower() in {"markdown", "table", "json"}:
        return False
    if TITLE_BOILERPLATE_RE.match(text):
        return False
    if re.fullmatch(r"[\d\s._/\-—:()]+", text):
        return False
    # Reject OCR gibberish ("! \" # $ % ..." / rare-CJK walls).
    if not re.search(r"[A-Za-z]{2,}", text) and not TITLE_VOCAB_RE.search(text):
        return False
    # A real title is a noun phrase: sentence punctuation means the fallback
    # picked body text or a table note.
    if re.search(r"[。；;]", text) or text.endswith(("：", ":")):
        return False
    # Chinese titles do not carry a field separator; "代表签字：..." does.
    if "：" in text and re.search(r"[\u4e00-\u9fff]", text):
        return False
    # List enumerators ("b) 合金牌号：") are clause text, not titles.
    if re.match(r"^[a-zA-Z][)）.、]\s*\S", text):
        return False
    # Clause headings ("3. TECHNICAL REQUIREMENTS") are structure, not titles,
    # regardless of length ("8.6 Purchase documents should specify ...").
    if re.match(r"^\d+(?:\.\d+)*\.?\s+\S", text) or re.match(r"^\d+\.\d+", text):
        return False
    if re.search(r"(?:GB\s*/?\s*T|GJB(?:\s*/\s*[A-Z])?|ISO|ASTM|ASME|AMS|AWS|HB|"
                 r"NB\s*/?\s*T|YS\s*/?\s*T|YY\s*/?\s*T|YB)\s*[-—]?\s*\d",
                 text, re.IGNORECASE):
        return False
    return True


def _join_title_continuation(lines: list[str], index: int, heading: str) -> str:
    candidate = heading
    for step in range(1, 4):
        following = next(
            (
                line.strip()
                for line in lines[index + step : index + step + 3]
                if line.strip() and not line.lstrip().startswith(("#", "<", "|"))
            ),
            None,
        )
        if not following:
            break
        connector = bool(CONNECTOR_TAIL_RE.search(candidate))
        continuation = bool(CONTINUATION_START_RE.match(following))
        # A connector only pulls the next line when the heading is still short
        # ("Standard Specification for" + title). A long candidate that already
        # ends in a dash is followed by the second-language title, not more of
        # the English title.
        if connector and len(candidate.split()) >= 5 and not continuation:
            break
        if not connector and not continuation:
            break
        if not _title_acceptable(_clean_title(following)):
            break
        candidate = f"{candidate} {following}"
    return _clean_title(re.sub(r"[—\-、]\s*$", "", candidate).strip())


def parse_scope_title(text: str) -> str | None:
    """Derive the product title from the "范围" clause when the cover is garbled."""

    for pattern in (SCOPE_TITLE_RE, SCOPE_SENTENCE_RE):
        for match in pattern.finditer(text):
            candidate = re.sub(r"^(?:了|的)+", "", _clean_title(match.group(1)))
            candidate = re.sub(
                r"\s*[（(]\s*以下简称[^）)]*[）)]", "", candidate
            )
            candidate = candidate.strip(" 的了")
            if len(candidate) >= 2 and _title_acceptable(candidate):
                return candidate
    return None


def _cell_title(raw: str) -> str:
    """Pick the title lines out of a spanning cover cell.

    AMS covers put the product title and the chemical composition in one cell;
    collapsing the whole cell produced a 300+ character string that failed
    validation, so a section heading such as "Composition" won instead.
    """

    parts: list[str] = []
    for line in raw.splitlines():
        text = _clean_title(line)
        if not text:
            continue
        if re.match(r"^\d", text):
            break
        parts.append(text)
        if len(" ".join(parts)) > 140:
            break
    return _clean_title(" ".join(parts))


EN_SCOPE_RE = re.compile(
    r"this specification covers\s+(?:an?|the)?\s*(?P<body>[^.]{10,220})\.",
    re.IGNORECASE,
)


def parse_scope_title_en(text: str) -> str | None:
    """Build a product title from an English "This specification covers ..."."""

    match = EN_SCOPE_RE.search(text)
    if match is None:
        return None
    body = re.sub(r"\s+", " ", match.group("body")).strip()
    material, separator, form = body.partition(" in the form of ")
    if not separator:
        candidate = body
    else:
        form = re.split(r"\s+\d|\s+and\b|[,;]", form)[0].strip()
        candidate = f"{material.strip()} {form}".strip()
    candidate = re.sub(r"^(?:an?|the)\s+", "", candidate, flags=re.IGNORECASE)
    candidate = candidate[:1].upper() + candidate[1:]
    return candidate if _title_acceptable(candidate) else None


def _english_cover_title(text: str) -> str | None:
    """Read the ASTM/ASME cover line "Standard Specification for <title>"."""

    head = "\n".join(text.splitlines()[:60])
    match = STANDARD_FOR_RE.search(head)
    if match is None:
        return None
    candidate = _clean_title(match.group(0))
    if len(candidate) >= 5 and _title_acceptable(candidate):
        return candidate
    return None


def parse_heading_title(text: str) -> str | None:
    lines = text.splitlines()
    cover_title = _english_cover_title(text)
    if cover_title:
        return cover_title
    heading_re = re.compile(r"^#{1,3}\s+(.+?)\s*$")
    for index, line in enumerate(lines):
        match = heading_re.match(line.strip())
        if match is None:
            continue
        candidate = _join_title_continuation(lines, index, match.group(1))
        if _title_acceptable(candidate):
            return candidate
    # AMS covers put the material description in a spanning table cell.
    for match in HTML_CELL_RE.finditer(text):
        candidate = _cell_title(match.group(1))
        if len(candidate) >= 8 and _title_acceptable(candidate):
            return candidate
    scope_title = parse_scope_title_en(text)
    if scope_title:
        return scope_title
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "<", "|")):
            continue
        candidate = _clean_title(stripped)
        if len(candidate) >= 6 and _title_acceptable(candidate):
            return candidate
    return None


def parse_title(text: str, fallback: str) -> str:
    lines = text.splitlines()
    std_index = 0
    for index, line in enumerate(lines[:80]):
        if re.search(r"(GB/?T|GJB|Q/?Du|Q/?S|JX)\s*[0-9]", line, re.IGNORECASE):
            std_index = index
            break

    for line in lines[std_index : std_index + 24]:
        match = HEADING_RE.match(line.strip())
        if match is None:
            continue
        candidate = _clean_title(match.group(1))
        if candidate.lower().startswith("page"):
            continue
        if candidate and _title_acceptable(candidate):
            return candidate
    return Path(fallback).stem


def parse_file_number(text: str | None) -> str | None:
    """Read ``文件编号:LSAM-JD01-0006-2021`` from cover text or a title."""

    if not text:
        return None
    match = FILE_NUMBER_RE.search(text)
    if match is None:
        return None
    return match.group(1).strip("._/-") or None


def _is_generated_title(title: str | None, file_name: str) -> bool:
    text = (title or "").strip()
    if not text:
        return True
    stem = Path(file_name).stem
    return text == stem or bool(re.fullmatch(r"[0-9a-f]{16,}", text))


def apply_page_identity(document: DocumentMeta, pages: list[Page]) -> DocumentMeta:
    """Fill standard number and title from the OCR text of a PDF.

    ``build_pdf_meta`` only knows the uploaded file name. Uploads are stored
    under a hash name, so a technical agreement ends up with a hash title and
    no standard number even though its cover prints both. The cover text is
    available after OCR and is the authoritative source.
    """

    head = "\n".join(page.markdown or "" for page in pages[:2])
    title_head = "\n".join(page.markdown or "" for page in pages[:8])
    standard_no = document.standard_no
    if not standard_no:
        stem = Path(document.file_name).stem
        standard_no = (
            parse_file_number(head)
            or parse_file_number(document.file_name)
            or (stem if FILE_NUMBER_STEM_RE.fullmatch(stem) else None)
        )
    title = document.title
    if _is_generated_title(title, document.file_name):
        heading = parse_heading_title(title_head)
        if heading is None:
            # Scanned covers sometimes OCR to symbol soup; the scope clause
            # still names the product ("本标准规定了不锈钢棒的尺寸...").
            heading = parse_scope_title(title_head)
        if heading:
            title = re.sub(r"\s+", " ", heading)
    version = document.version
    if standard_no and not version:
        match = re.search(r"(\d{4})$", standard_no)
        if match:
            version = match.group(1)
    if (
        standard_no == document.standard_no
        and title == document.title
        and version == document.version
    ):
        return document
    return document.model_copy(
        update={"standard_no": standard_no, "title": title, "version": version}
    )


def build_meta(path: Path, text: str, pages: list[Page]) -> DocumentMeta:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    standard_no = parse_standard_no(path.name)
    version = None
    if standard_no:
        match = re.search(r"(\d{4})$", standard_no)
        if match:
            version = match.group(1)
    return DocumentMeta(
        doc_id=make_doc_id(standard_no or path.stem, digest),
        source_path=str(path),
        file_name=path.name,
        standard_no=standard_no,
        title=parse_title(text, path.name),
        version=version,
        page_count=len(pages),
        sha256=digest,
    )


def make_doc_id(label: str, digest: str) -> str:
    safe = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "-", label).strip("-").lower()
    return f"{safe or 'doc'}-{digest[:8]}"


def build_pdf_meta(path: Path) -> DocumentMeta:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    standard_no = parse_standard_no(path.name)
    version = None
    if standard_no:
        match = re.search(r"(\d{4})$", standard_no)
        if match:
            version = match.group(1)
    title = re.sub(r"^\s*\d+[.、\s]+", "", path.stem).strip() or path.stem
    return DocumentMeta(
        doc_id=make_doc_id(standard_no or path.stem, digest),
        source_path=str(path),
        file_name=path.name,
        standard_no=standard_no,
        title=title,
        version=version,
        page_count=0,
        sha256=digest,
    )


def ingest(path: str | Path) -> tuple[DocumentMeta, list[Page]]:
    doc_path = Path(path)
    if not doc_path.exists():
        raise FileNotFoundError(doc_path)
    suffix = doc_path.suffix.lower()
    if suffix == ".pdf":
        return build_pdf_meta(doc_path), []
    if suffix != ".md":
        raise ValueError(f"unsupported input type: {doc_path.suffix}")
    text = doc_path.read_text(encoding="utf-8", errors="ignore")
    pages = split_pages(text)
    return build_meta(doc_path, text, pages), pages
