"""Document outline construction.

The outline is a navigational artifact, not a normative interpretation. It is
used by CoveragePlan to point at candidate clauses/tables and by the review UI to
jump back to the source page.
"""

from __future__ import annotations

import re

from ..contracts import DocumentMeta, OutlineGraph, OutlineNode, Page
from ..tablegrid.normalize import clean_text

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")
CLAUSE_ID_RE = re.compile(
    r"^(?P<clause_id>"
    r"[A-Z](?:\.\s*\d{1,3}){1,3}"
    r"|\d{1,2}(?:\.\s*\d{1,3}){0,3}"
    r")"
    r"(?:\s+|(?=[^\d.\s]))(?P<title>.*)$"
)
TABLE_CAPTION_RE = re.compile(r"^表\s*[A-Za-z]?\.?\s*\d+(?:\.\d+)?")
FIGURE_CAPTION_RE = re.compile(r"^图\s*\d+")
APPENDIX_RE = re.compile(r"^附\s*录\s*(?P<letter>[A-Z])(?:\s|$|[（(])")


def clause_id_from_title(text: str) -> str | None:
    cleaned = clean_text(text)
    appendix = APPENDIX_RE.match(cleaned)
    if appendix:
        return f"附录{appendix.group('letter')}"
    match = CLAUSE_ID_RE.match(cleaned)
    if not match:
        return None
    return re.sub(r"\s+", "", match.group("clause_id")).rstrip(".")


def build_outline(document: DocumentMeta, pages: list[Page]) -> OutlineGraph:
    nodes: list[OutlineNode] = [
        OutlineNode(
            node_id="doc",
            kind="document",
            title=document.title or document.file_name,
            level=0,
        )
    ]
    stack: list[OutlineNode] = [nodes[0]]
    counter = 0

    for page in pages:
        page_node = OutlineNode(
            node_id=f"page:{page.page_no}",
            kind="page",
            title=f"Page {page.page_no}",
            page_no=page.page_no,
            level=1,
            parent_id="doc",
        )
        nodes.append(page_node)

        for line in page.markdown.splitlines():
            stripped = line.strip()
            if not stripped:
                continue

            heading = HEADING_RE.match(stripped)
            if heading:
                text = clean_text(heading.group(2))
                if text.lower().startswith("page") or text == "Table":
                    continue
                level = len(heading.group(1))
                while len(stack) > 1 and stack[-1].level >= level:
                    stack.pop()
                parent = stack[-1]
                counter += 1
                kind = "clause"
                if "附录" in text:
                    kind = "appendix"
                elif text.startswith("表"):
                    kind = "table"
                elif text.startswith("图"):
                    kind = "figure"
                clause_id = clause_id_from_title(text)
                node = OutlineNode(
                    node_id=f"clause:{clause_id or counter}",
                    kind=kind,
                    title=text,
                    clause_id=clause_id,
                    page_no=page.page_no,
                    level=level,
                    parent_id=parent.node_id,
                    normative=not any(key in text for key in ("前言", "引言", "资料性附录")),
                )
                nodes.append(node)
                stack.append(node)
                continue

            caption_line = stripped.strip("*").strip()
            if TABLE_CAPTION_RE.match(caption_line):
                counter += 1
                nodes.append(
                    OutlineNode(
                        node_id=f"table:{page.page_no}:{counter}",
                        kind="table",
                        title=clean_text(caption_line),
                        page_no=page.page_no,
                        level=2,
                        parent_id=page_node.node_id,
                    )
                )
            elif FIGURE_CAPTION_RE.match(stripped):
                counter += 1
                nodes.append(
                    OutlineNode(
                        node_id=f"figure:{page.page_no}:{counter}",
                        kind="figure",
                        title=clean_text(stripped),
                        page_no=page.page_no,
                        level=2,
                        parent_id=page_node.node_id,
                    )
                )

    return OutlineGraph(doc_id=document.doc_id, nodes=nodes)
