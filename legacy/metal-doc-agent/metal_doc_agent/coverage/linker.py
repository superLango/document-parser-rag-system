"""Table-to-clause linking (M1.7).

Linking answers where a table belongs in the document structure. Explicit
references (``见表3``/``按表B.3``) win; otherwise the nearest preceding heading
is used as a navigational fallback. The result is evidence for coverage, not a
normative interpretation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..contracts import Page, TableClauseLink, TableGrid, TableLinkResult
from ..tablegrid.normalize import clean_text
from .outline import clause_id_from_title

HEADING_RE = re.compile(r"^\s*(#{1,6})\s+(.+)$")
TABLE_LABEL_RE = re.compile(r"表\s*(?P<label>[A-Z]?\.?\s*\d+(?:\.\s*\d+)?)")
TABLE_REF_RE = re.compile(
    r"(?:见|按|参见|详见|符合|满足|执行|依据)\s*表\s*"
    r"(?P<label>[A-Z]?\.?\s*\d+(?:\.\s*\d+)?)"
)


@dataclass
class HeadingBlock:
    clause_id: str | None
    title: str
    page_no: int
    line_no: int
    body: str

    @property
    def order(self) -> tuple[int, int]:
        return (self.page_no, self.line_no)


def extract_heading_blocks(pages: list[Page]) -> list[HeadingBlock]:
    blocks: list[HeadingBlock] = []
    current: HeadingBlock | None = None
    body: list[str] = []
    for page in pages:
        for line_no, raw_line in enumerate(page.markdown.splitlines()):
            line = raw_line.strip()
            heading = HEADING_RE.match(line)
            if heading:
                if current is not None:
                    current.body = clean_text(" ".join(body))
                    blocks.append(current)
                text = clean_text(heading.group(2))
                current = HeadingBlock(
                    clause_id=clause_id_from_title(text),
                    title=text,
                    page_no=page.page_no,
                    line_no=line_no,
                    body="",
                )
                body = []
                continue
            appendix_id = (
                clause_id_from_title(line)
                if line.startswith("附") and len(line) <= 20
                else None
            )
            if appendix_id:
                if current is not None:
                    current.body = clean_text(" ".join(body))
                    blocks.append(current)
                current = HeadingBlock(
                    clause_id=appendix_id,
                    title=line,
                    page_no=page.page_no,
                    line_no=line_no,
                    body="",
                )
                body = []
                continue
            plain_id = (
                clause_id_from_title(line)
                if len(line) <= 60 and not line.startswith(("表", "图", "注"))
                else None
            )
            if plain_id and "." in plain_id:
                if current is not None:
                    current.body = clean_text(" ".join(body))
                    blocks.append(current)
                current = HeadingBlock(
                    clause_id=plain_id,
                    title=line,
                    page_no=page.page_no,
                    line_no=line_no,
                    body="",
                )
                body = []
                continue
            if current is not None and line and not line.startswith("## Table"):
                body.append(line)
    if current is not None:
        current.body = clean_text(" ".join(body))
        blocks.append(current)
    return blocks


def build_links(
    doc_id: str, pages: list[Page], tables: list[TableGrid]
) -> TableLinkResult:
    blocks = extract_heading_blocks(pages)
    positions = {
        table.table_id: _table_position(table, pages) for table in tables
    }
    table_labels = {
        table.table_id: _table_label(table.caption) for table in tables
    }
    links: dict[str, TableClauseLink] = {}

    for table in tables:
        if _has_parent(table):
            continue
        links[table.table_id] = _link_table(
            table, blocks, positions[table.table_id], table_labels
        )

    for table in tables:
        if not _has_parent(table):
            continue
        parent = links.get(table.continuation_of)
        if parent is not None and parent.clause_id:
            links[table.table_id] = TableClauseLink(
                table_id=table.table_id,
                clause_id=parent.clause_id,
                clause_title=parent.clause_title,
                page_no=table.page_no,
                basis="continuation",
                confidence=parent.confidence,
                evidence=f"continuation_of:{table.continuation_of}",
            )
            continue
        links[table.table_id] = _link_table(
            table, blocks, positions[table.table_id], table_labels
        )

    ordered = [links[table.table_id] for table in tables]
    orphans = [
        {
            "table_id": link.table_id,
            "page_no": link.page_no,
            "reason": "未找到表引用或前置条款",
        }
        for link in ordered
        if link.clause_id is None
    ]
    explicit = sum(1 for link in ordered if link.basis == "explicit")
    nearest = sum(1 for link in ordered if link.basis in {"nearest", "section"})
    continuation = sum(1 for link in ordered if link.basis == "continuation")
    linked = sum(1 for link in ordered if link.clause_id)
    return TableLinkResult(
        doc_id=doc_id,
        links=ordered,
        orphans=orphans,
        coverage={
            "tables": len(ordered),
            "linked": linked,
            "explicit": explicit,
            "nearest": nearest,
            "continuation": continuation,
            "unlinked": len(ordered) - linked,
            "link_rate": round(linked / len(ordered), 4) if ordered else 0.0,
            "explicit_rate": round(explicit / len(ordered), 4) if ordered else 0.0,
        },
    )


def _has_parent(table: TableGrid) -> bool:
    return bool(table.continuation_of and table.continuation_of != table.table_id)


def _link_table(
    table: TableGrid,
    blocks: list[HeadingBlock],
    position: tuple[int, int],
    table_labels: dict[str, str | None],
) -> TableClauseLink:
    label = table_labels.get(table.table_id)
    if label:
        explicit = _explicit_block(blocks, label, position)
        if explicit is not None:
            return TableClauseLink(
                table_id=table.table_id,
                clause_id=explicit.clause_id,
                clause_title=explicit.title,
                page_no=table.page_no,
                basis="explicit",
                confidence=1.0,
                evidence=f"表{label}",
            )

    nearest = _nearest_block(blocks, position)
    if nearest is not None:
        basis = "nearest"
        confidence = 0.5
        if label:
            basis = "caption"
            confidence = 0.7
        return TableClauseLink(
            table_id=table.table_id,
            clause_id=nearest.clause_id,
            clause_title=nearest.title,
            page_no=table.page_no,
            basis=basis,
            confidence=confidence,
            evidence=nearest.title,
        )

    return TableClauseLink(
        table_id=table.table_id,
        page_no=table.page_no,
        basis="none",
        confidence=0.0,
    )


def _explicit_block(
    blocks: list[HeadingBlock], label: str, position: tuple[int, int]
) -> HeadingBlock | None:
    candidates = [
        block
        for block in blocks
        if block.clause_id
        and _block_references(block, label)
        and block.order <= position
    ]
    if not candidates:
        candidates = [
            block
            for block in blocks
            if block.clause_id and _block_references(block, label)
        ]
    if not candidates:
        return None
    return max(candidates, key=lambda block: (block.order, _level(block)))


def _block_references(block: HeadingBlock, label: str) -> bool:
    for match in TABLE_REF_RE.finditer(f"{block.title} {block.body}"):
        if _normalize_label(match.group("label")) == label:
            return True
    return False


def _nearest_block(
    blocks: list[HeadingBlock], position: tuple[int, int]
) -> HeadingBlock | None:
    before = [
        block for block in blocks if block.clause_id and block.order <= position
    ]
    if before:
        return max(before, key=lambda block: (block.order, _level(block)))
    after = [block for block in blocks if block.clause_id]
    if after:
        return min(after, key=lambda block: block.order)
    return None


def _level(block: HeadingBlock) -> int:
    return block.clause_id.count(".") if block.clause_id else 0


def _table_label(caption: str | None) -> str | None:
    text = clean_text(caption)
    match = TABLE_LABEL_RE.search(text)
    if not match:
        return None
    return _normalize_label(match.group("label"))


def _normalize_label(value: str) -> str:
    return re.sub(r"\s+", "", value).upper()


def _table_position(
    table: TableGrid, pages: list[Page]
) -> tuple[int, int]:
    page = next((item for item in pages if item.page_no == table.page_no), None)
    if page is not None and table.caption:
        caption = _compact(table.caption)
        for line_no, line in enumerate(page.markdown.splitlines()):
            if caption and caption in _compact(line):
                return (table.page_no, line_no)
    return (table.page_no, 0)


def _compact(value: str | None) -> str:
    return re.sub(r"\s+", "", clean_text(value))
