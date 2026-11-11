"""Reference parsing for M1.5.

Parses the normative-reference section and inline standard references into a
ReferenceGraph. Version resolution and constraint merging are later M1.5
steps; this module only builds the graph and gap list.
"""

from __future__ import annotations

import re

from .contracts import DocumentMeta, Page, ReferenceEdge, ReferenceGraph
from .tablegrid.normalize import clean_text

STANDARD_RE = re.compile(
    r"(?P<org>GB/T|GB|GJB/Z|GJB|JB/T|YB/T|HB/Z|HB|ASTM|ISO|AMS-STD|AMS|QJ|"
    r"Q/(?:[A-Za-z]+|[A-Za-z0-9]*[A-Za-z])|JX|MAS|MFS)\s*"
    r"(?P<num>-?\d+(?:\.\d+)*(?:-\d+)?[A-Z]?|[A-Z]\s?\d+[A-Za-z]?)"
    r"(?:\s*[-—–:]\s*(?P<year>\d{4}))?"
)
NORMATIVE_HEADING_RE = re.compile(
    r"^\s*#{0,6}\s*2(?:\.0)?\s*[、.．]?\s*(?:规范性引用文件|引用标准|引用文件)\s*$"
)
HEADING_RE = re.compile(r"^\s*#{1,6}\s+\S")
TABLE_RE = re.compile(r"<table\b.*?</table>", re.IGNORECASE | re.DOTALL)
YEAR_SUFFIX_RE = re.compile(r"-\d{4}$")
FRONT_MATTER_RE = re.compile(r"^\s*#{0,6}\s*(?:前\s*言|目\s*次|引\s*言)\s*$", re.MULTILINE)
CUE_RE = re.compile(r"按|见|符合|执行|依据|遵守|遵照|采用|引用")
SKIP_LINE_RE = re.compile(
    r"代替|历次版本|起草|编制|归口|提出|发布|实施|修订|基础上|相比"
)


def extract_references(pages: list[Page], document: DocumentMeta) -> ReferenceGraph:
    self_no = _self_standard_no(document)
    edges: list[ReferenceEdge] = []
    for page in pages:
        text = page.markdown
        edges.extend(_normative_section(text, page.page_no, self_no))
        if not _is_front_matter(text):
            edges.extend(_inline_references(text, page.page_no, self_no))
    merged = _merge(edges)
    gaps = sorted(
        {
            f"{edge.standard_no}-{edge.edition}" if edge.edition else edge.standard_no
            for edge in merged
            if not edge.resolved
        }
    )
    return ReferenceGraph(doc_id=document.doc_id, references=merged, gaps=gaps)


def _self_standard_no(document: DocumentMeta) -> str | None:
    if not document.standard_no:
        return None
    text = clean_text(document.standard_no).replace(" ", "")
    return YEAR_SUFFIX_RE.sub("", text) or None


def _normative_section(
    text: str, page_no: int, self_no: str | None = None
) -> list[ReferenceEdge]:
    lines = text.splitlines()
    edges: list[ReferenceEdge] = []
    in_section = False
    for line in lines:
        stripped = line.strip()
        if NORMATIVE_HEADING_RE.match(stripped):
            in_section = True
            continue
        if in_section and HEADING_RE.match(stripped):
            break
        if not in_section or not stripped:
            continue
        match = STANDARD_RE.search(stripped)
        if not match:
            continue
        edge = _edge(match, page_no, relation="normative", clause_id="2")
        if edge is None or _is_self(edge, self_no):
            continue
        suffix = clean_text(stripped[match.end() :]).lstrip("：:，,、 ")
        edge.title = suffix or None
        edges.append(edge)
    return edges


def _inline_references(
    text: str, page_no: int, self_no: str | None = None
) -> list[ReferenceEdge]:
    plain = TABLE_RE.sub(" ", text)
    edges: list[ReferenceEdge] = []
    clause_id: str | None = None
    for line in plain.splitlines():
        heading = HEADING_RE.match(line)
        if heading:
            match = re.match(r"\s*#{1,6}\s*(\d+(?:\.\d+)*)", line)
            clause_id = match.group(1) if match else None
        if SKIP_LINE_RE.search(line) or not CUE_RE.search(line):
            continue
        for match in STANDARD_RE.finditer(line):
            edge = _edge(match, page_no, relation="clause", clause_id=clause_id)
            if edge is not None and not _is_self(edge, self_no):
                edges.append(edge)
    return edges


def _is_front_matter(text: str) -> bool:
    if FRONT_MATTER_RE.search(text):
        return True
    return "发布" in text and "实施" in text


def _is_self(edge: ReferenceEdge, self_no: str | None) -> bool:
    if not self_no or not edge.standard_no:
        return False
    return edge.standard_no.replace(" ", "") == self_no


def _edge(
    match: re.Match[str],
    page_no: int,
    relation: str,
    clause_id: str | None = None,
) -> ReferenceEdge | None:
    org = clean_text(match.group("org"))
    number = re.sub(r"\s+", "", clean_text(match.group("num")))
    year = clean_text(match.group("year"))
    if not org or not number:
        return None
    if not year:
        suffix = re.search(r"-(\d{4})$", number)
        if (
            suffix
            and suffix.start() > 0
            and 1900 <= int(suffix.group(1)) <= 2099
        ):
            year = suffix.group(1)
            number = number[: suffix.start()]
        else:
            legacy = re.search(r"-(\d{2})$", number)
            if legacy and legacy.start() > 0:
                year = f"19{legacy.group(1)}"
                number = number[: legacy.start()]
    if number.startswith("-"):
        standard_no = f"{org}{number}"
    else:
        standard_no = f"{org} {number}"
    return ReferenceEdge(
        raw=clean_text(match.group(0)),
        standard_no=standard_no,
        title=None,
        edition=year or None,
        dated=bool(year),
        relation=relation,  # type: ignore[arg-type]
        clause_id=clause_id,
        page_no=page_no,
        resolved=False,
        resolved_doc_id=None,
    )


def _merge(edges: list[ReferenceEdge]) -> list[ReferenceEdge]:
    priority = {"normative": 3, "table_note": 2, "clause": 1, "other": 0}
    merged: dict[tuple[str | None, str | None], ReferenceEdge] = {}
    for edge in edges:
        key = (edge.standard_no, edge.edition)
        existing = merged.get(key)
        if existing is None:
            existing = next(
                (
                    candidate
                    for (number, edition), candidate in merged.items()
                    if number == edge.standard_no
                    and (edition is None or edge.edition is None)
                ),
                None,
            )
            if existing is None:
                merged[key] = edge
                continue
            merged.pop((existing.standard_no, existing.edition), None)
            if existing.edition is None and edge.edition:
                existing.edition = edge.edition
                existing.dated = True
        if priority.get(edge.relation, 0) > priority.get(existing.relation, 0):
            existing.relation = edge.relation
        if not existing.title and edge.title:
            existing.title = edge.title
        merged[(existing.standard_no, existing.edition)] = existing
    return list(merged.values())
