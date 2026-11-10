"""HTML table -> TableGrid.

The OCR markdown already contains HTML tables, not pipe tables. This parser
expands rowspan/colspan into a rectangular grid, reconstructs header paths,
captures units/footnotes, and splits repeated header blocks (e.g. GB/T 40303
chemistry table with three grade levels).
"""

from __future__ import annotations

import re
from typing import Iterable

from lxml import html as lxml_html

from ..contracts import Merge, Page, TableBlock, TableGrid
from .normalize import (
    clean_text,
    is_footnote_row,
    is_numeric_like,
    looks_like_grade,
    parse_unit,
)
from .profile import annotate_table

TABLE_RE = re.compile(r"<table\b.*?</table>", re.IGNORECASE | re.DOTALL)
CAPTION_RE = re.compile(r"(?:^|\n)\s*#{0,6}\s*(表\s*[A-Za-z]?\.?\s*\d+(?:\.\d+)?)\s*([^\n]*)")
TABLE_NUMBER_RE = re.compile(r"表\s*([A-Za-z]?\.?\s*\d+(?:\.\d+)?)")
REPEATED_HEADER_KEYS = {
    "级别",
    "牌号",
    "新牌号",
    "原牌号",
    "合金牌号",
    "Grade",
    "grade",
    "元素",
    "主要元素",
}
HEADER_FIRST_MARKERS = (
    "牌号", "级别", "钢级", "质量等级", "合金牌号", "元素", "化学成分",
    "检验项目", "序号", "名称", "项目", "交货状态", "热处理状态",
    "试样状态", "试验温度", "取样方向", "公称厚度", "公称直径",
    "厚度", "直径", "偏差",
)
RANGE_HEADER_RE = re.compile(
    r"^(?:(?:<=|>=|[<>≤≥])\s*)?\d+(?:\.\d+)?"
    r"(?:\s*[~～]\s*\d+(?:\.\d+)?)?\s*[a-zA-Z%℃]*$"
)
HEADER_MARKERS = REPEATED_HEADER_KEYS | {"钢级", "质量等级", "钢号", "材质", "材料"}
FOOTNOTE_INLINE_RE = re.compile(
    r"\$\s*([^$]*?)\s*\^\s*\{[^}]*\}\s*\$"
)
FOOTNOTE_MARK_RE = re.compile(
    r"\$\s*\^\s*\{[^}]*\}\s*\$"
    r"|\$\s*\^\s*[A-Za-z0-9]\s*\$"
    r"|\^\{[^}]*\}"
)


def extract_tables(pages: Iterable[Page]) -> list[TableGrid]:
    tables: list[TableGrid] = []
    counter = 0
    previous_tail = ""
    for page in pages:
        for match in TABLE_RE.finditer(page.markdown):
            counter += 1
            local_context = page.markdown[max(0, match.start() - 320) : match.start()]
            context = (previous_tail + "\n" + local_context)[-640:]
            after_context = _after_context(page.markdown, match.end())
            local_caption = find_caption(local_context) or find_caption(after_context)
            previous_caption = find_caption(previous_tail)
            table = parse_table(
                raw_html=match.group(0),
                table_id=f"T{counter}",
                page_no=page.page_no,
                caption=local_caption,
                context=context,
                after_context=after_context,
            )
            if not table.caption and previous_caption:
                if not tables or _caption_compatible(tables[-1], table):
                    table.caption = previous_caption
                    annotate_table(table)
            if not _is_footnote_table(table):
                tables.append(table)
        previous_tail = page.markdown[-500:]
    return merge_continuations(tables)


def _is_footnote_table(table: TableGrid) -> bool:
    """A one/two-row pseudo table whose content is only footnote text."""
    if table.n_rows > 2:
        return False
    cells = [clean_text(cell) for row in table.rows for cell in row if clean_text(cell)]
    if not cells:
        return False
    text = " ".join(cells)
    return bool(re.match(r"^[a-z][.、)]", text)) and len(text) >= 40


def _after_context(markdown: str, end: int, limit: int = 400) -> str:
    tail = markdown[end : end + limit]
    next_table = TABLE_RE.search(tail)
    return tail[: next_table.start()] if next_table else tail


def find_caption(context: str) -> str | None:
    lines = [clean_text(line.lstrip("# ").strip()) for line in context.splitlines() if line.strip()]
    for line in reversed(lines):
        line = line.strip("*").strip()
        if line == "Table":
            continue
        match = CAPTION_RE.search(line)
        if match:
            suffix = clean_text(match.group(2))
            base = clean_text(match.group(1))
            return f"{base} {suffix}".strip() if suffix else base
    return None


def parse_table(
    raw_html: str,
    table_id: str,
    page_no: int,
    caption: str | None = None,
    context: str = "",
    after_context: str = "",
) -> TableGrid:
    root = lxml_html.fromstring(raw_html)
    table_nodes = [root] if getattr(root, "tag", "").lower() == "table" else root.xpath("//table")
    if not table_nodes:
        raise ValueError("no <table> element found")
    node = table_nodes[0]

    rows, merges = _expand_grid(node)
    if not rows:
        return TableGrid(
            table_id=table_id,
            page_no=page_no,
            caption=caption,
            context=context[-1000:] or None,
            raw_html=raw_html[:50000],
        )

    n_cols = max(len(row) for row in rows)
    rows = [row + [""] * (n_cols - len(row)) for row in rows]
    header_rows = _detect_header_rows(rows)
    header_paths = _build_header_paths(rows, header_rows)
    rows, header_paths, n_cols = _repair_collapsed_columns(
        node, rows, header_paths, header_rows, n_cols, merges
    )
    rows = _strip_repeated_header_prefix(rows, header_rows, n_cols)
    header_paths = _build_header_paths(rows, header_rows)
    n_cols = max((len(row) for row in rows), default=n_cols)
    units = _collect_units(header_paths, context)
    footnotes = _collect_footnotes(node, rows, after_context)

    table = TableGrid(
        table_id=table_id,
        page_no=page_no,
        caption=caption,
        context=context[-1000:] or None,
        n_rows=len(rows),
        n_cols=n_cols,
        header_rows=header_rows,
        rows=rows,
        header_paths=header_paths,
        merges=merges,
        units=units,
        footnotes=footnotes,
        raw_html=raw_html[:50000],
    )
    table = annotate_table(table)
    table.blocks = _split_blocks(table)
    return table


def rebuild_table(table: TableGrid) -> TableGrid:
    """Recompute derived fields after an explicit hard-table repair."""
    table.n_rows = len(table.rows)
    table.n_cols = max((len(row) for row in table.rows), default=0)
    table.header_paths = _build_header_paths(table.rows, table.header_rows)
    table.blocks = _split_blocks(table)
    return table


def _strip_repeated_header_prefix(
    rows: list[list[str]], header_rows: int, n_cols: int
) -> list[list[str]]:
    """Drop header labels that OCR repeats at the start of a data row.

    GB/T 3077 table 3 renders the first data row as
    ``钢组 | 序号 | 牌号 | 试样毛坯尺寸 | Mn | 1 | 20Mn2 | ...``; without this
    shift every downstream column binding is one block to the right.
    """

    if header_rows < 1 or len(rows) <= header_rows:
        return rows
    labels = [clean_text(cell) for cell in rows[0]]
    if sum(1 for label in labels if label) < 2:
        return rows
    stripped = [list(row) for row in rows]
    for index in range(header_rows, len(stripped)):
        row = stripped[index]
        prefix = 0
        for cell, label in zip(row, labels):
            if label and clean_text(cell) == label:
                prefix += 1
            else:
                break
        if prefix < 2:
            continue
        # A full repeated header row (block boundary) has no payload to keep.
        if not any(clean_text(cell) for cell in row[prefix:]):
            continue
        shifted = row[prefix:] + [""] * prefix
        stripped[index] = shifted[:n_cols] + [""] * max(0, n_cols - len(shifted))
    return stripped


def _repair_collapsed_columns(
    node,
    rows: list[list[str]],
    header_paths: list[list[str]],
    header_rows: int,
    n_cols: int,
    merges: list[Merge],
) -> tuple[list[list[str]], list[list[str]], int]:
    """Normalize tables where header spans bleed into data rows.

    GB/T 1591 table 1 has a ``rowspan=5 colspan=13`` header cell that the
    expanded grid copies into data rows ("不大于" repeated across columns), a
    ``colspan=14`` chemistry header that is one column short, and a
    ``colspan=2`` C subheader that is one column too wide. Re-expand header and
    data rows separately so header rowspans never leak into data rows.
    """
    if not rows:
        return rows, header_paths, n_cols

    trs = node.xpath(".//tr")
    data_rows = rows[header_rows:]
    polluted = sum(
        1
        for row in data_rows
        if sum(1 for cell in row if clean_text(cell) == "不大于") >= 3
    )
    spilled = _header_spills_past_data(rows, header_rows)
    shifted = _header_grade_shifted(header_paths, merges, header_rows)
    if header_rows < 3 or (polluted < 2 and not spilled and not shifted) or len(trs) <= header_rows:
        return rows, header_paths, n_cols

    wide_header, _, _ = _expand_rows(trs[:header_rows], n_cols)
    n_cols = _implied_width(wide_header) or n_cols
    header_grid, _, overflow = _expand_rows(trs[:header_rows], n_cols)
    _distribute_header_overflow(header_grid, overflow)
    data_grid, spans, _ = _expand_rows(trs[header_rows:], n_cols)
    header_paths = _build_header_paths(header_grid, len(header_grid))
    _duplicate_collapsed_cells(data_grid, spans, header_paths, n_cols)
    return header_grid + data_grid, header_paths, n_cols


def _header_spills_past_data(rows: list[list[str]], header_rows: int) -> bool:
    """A header cell sits to the right of every populated data column."""
    data_rows = rows[header_rows:]
    last = max(
        (
            index
            for row in data_rows
            for index, cell in enumerate(row)
            if clean_text(cell)
        ),
        default=-1,
    )
    if last < 0:
        return False
    return any(
        clean_text(row[index])
        for row in rows[:header_rows]
        for index in range(last + 1, len(row))
    )


def _header_grade_shifted(
    header_paths: list[list[str]], merges: list[Merge], header_rows: int
) -> bool:
    """A rowspan grade cell was cleared, shifting the subheader left by one.

    ``_expand_grid`` drops inherited cells when a row's own cells fill the width
    (the overstated-rowspan case). Only trust this signal when the first column
    really is a grade cell spanning *all* header rows; otherwise the extra path
    element is a data row that was misdetected as a header (e.g. GB/T 3191 T6).
    """
    grade_markers = {"牌号", "新牌号", "原牌号", "旧牌号", "钢级", "合金牌号"}
    first = header_paths[0] if header_paths else []
    if len(first) < 2 or clean_text(first[0]) not in grade_markers:
        return False
    return any(
        merge.row == 0
        and merge.col == 0
        and merge.rowspan >= header_rows
        and clean_text(merge.text) == clean_text(first[0])
        for merge in merges
    )


def _implied_width(rows: list[list[str]]) -> int:
    """Pick the column count from the most informative header row."""
    if not rows:
        return 0
    markers = {"不大于", "不小于"}
    best = max(
        rows,
        key=lambda row: sum(
            1 for cell in row if clean_text(cell) and clean_text(cell) not in markers
        ),
    )
    return max(
        (index + 1 for index, cell in enumerate(best) if clean_text(cell)), default=0
    )


def _expand_rows(
    trs, n_cols: int
) -> tuple[list[list[str]], list[list[tuple[int, int]]], list[tuple[int, str]]]:
    """Expand rows into a fixed-width grid, recording colspan/rowspan spans.

    Cells that no longer fit (because an earlier colspan was too wide) are
    returned as overflow so callers can redistribute them into a duplicate
    header group.
    """
    rows: list[list[str]] = []
    spans: list[list[tuple[int, int]]] = []
    overflow: list[tuple[int, str]] = []
    pending: dict[int, tuple[int, str, int, int]] = {}
    for row_index, tr in enumerate(trs):
        row: list[str | None] = [None] * n_cols
        row_spans: list[tuple[int, int]] = [(1, 1)] * n_cols
        for col, (remaining, text, colspan, rowspan) in list(pending.items()):
            if col < n_cols:
                row[col] = text
                row_spans[col] = (colspan, rowspan)
            if remaining <= 1:
                del pending[col]
            else:
                pending[col] = (remaining - 1, text, colspan, rowspan)
        col = 0
        for cell in tr.xpath("./td|./th"):
            text = _cell_text(cell)
            colspan = max(1, _int_attr(cell, "colspan", 1))
            rowspan = max(1, _int_attr(cell, "rowspan", 1))
            while col < n_cols and row[col] is not None:
                col += 1
            if col >= n_cols:
                overflow.append((row_index, text))
                continue
            for offset in range(colspan):
                target = col + offset
                if target >= n_cols:
                    overflow.append((row_index, text))
                    break
                row[target] = text
                row_spans[target] = (colspan, rowspan)
                if rowspan > 1:
                    pending[target] = (rowspan - 1, text, colspan, rowspan)
            col += colspan
        rows.append([value or "" for value in row])
        spans.append(row_spans)
    return rows, spans, overflow


def _distribute_header_overflow(
    rows: list[list[str]], overflow: list[tuple[int, str]]
) -> None:
    """Put an overflowing subheader into the second column of its group."""
    markers = {"不大于", "不小于"}
    for row_index, text in overflow:
        text = clean_text(text)
        if not text or row_index >= len(rows):
            continue
        row = rows[row_index]
        for col in range(len(row) - 1):
            value = clean_text(row[col])
            if value and value == clean_text(row[col + 1]) and value not in markers:
                row[col + 1] = text
                break


def _duplicate_collapsed_cells(
    data_rows: list[list[str]],
    spans: list[list[tuple[int, int]]],
    header_paths: list[list[str]],
    n_cols: int,
) -> None:
    """Duplicate a single C value into its two thickness subcolumns."""
    start = _duplicate_group_start(header_paths)
    if start is None or start + 1 >= n_cols:
        return
    for index, row in enumerate(data_rows):
        if index >= len(spans):
            break
        colspan, rowspan = spans[index][start]
        if colspan == 1 and rowspan > 1 and clean_text(row[start]):
            data_rows[index] = (
                row[: start + 1]
                + [row[start]]
                + row[start + 1 : n_cols - 1]
            )


def _duplicate_group_start(header_paths: list[list[str]]) -> int | None:
    for start in range(2, len(header_paths) - 1):
        signature = _column_signature(header_paths, start)
        if not signature or signature != _column_signature(header_paths, start + 1):
            continue
        if start + 2 < len(header_paths) and signature == _column_signature(
            header_paths, start + 2
        ):
            continue
        return start
    return None


def _column_signature(header_paths: list[list[str]], index: int) -> str:
    if index >= len(header_paths):
        return ""
    path = header_paths[index]
    if not path:
        return ""
    key = clean_text(path[1]) if len(path) > 1 else clean_text(path[0])
    if not key or key in {"不大于", "不小于"}:
        return ""
    if re.fullmatch(r"[\d.~<>≤≥%\-/]+", key):
        return ""
    return key


def _expand_grid(node) -> tuple[list[list[str]], list[Merge]]:
    grid: list[list[str | None]] = []
    merges: list[Merge] = []
    pending: dict[int, tuple[int, str, int]] = {}

    for r, tr in enumerate(node.xpath(".//tr")):
        while len(grid) <= r:
            grid.append([])
        row = grid[r]
        for col, (remaining, text, rowspan) in list(pending.items()):
            while len(row) <= col:
                row.append(None)
            row[col] = text
            if remaining <= 1:
                del pending[col]
            else:
                pending[col] = (remaining - 1, text, rowspan)

        cells = tr.xpath("./td|./th")
        width = max((len(previous) for previous in grid[:r]), default=0)
        prefilled = sum(1 for cell in row if cell is not None)
        overflow = prefilled + len(cells) - width
        # Some OCR HTML overstates rowspan (e.g. rowspan=6 over five data rows),
        # so the next block's first row inherits stale grade cells *and* brings a
        # full-width row of its own. Only that case leaves as much overflow as
        # prefilled columns; a row with one extra cell keeps the inherited spans.
        # Header cells (牌号 etc.) mean the rowspan is genuine: keep them, even
        # when the sub-header row is one cell short of the previous width.
        # A data row that inherits a header cell is still overstated rowspan.
        inherited = [cell for cell in row if cell is not None]
        header_like = any(clean_text(cell) in HEADER_MARKERS for cell in inherited)
        incoming_numeric = any(is_numeric_like(_cell_text(cell)) for cell in cells)
        if (
            prefilled
            and width
            and overflow >= prefilled
            and not (header_like and not incoming_numeric)
        ):
            for col in range(len(row)):
                row[col] = None
            pending.clear()

        c = 0
        for cell in cells:
            while c < len(row) and row[c] is not None:
                c += 1
            text = _cell_text(cell)
            rowspan = _int_attr(cell, "rowspan", 1)
            colspan = _int_attr(cell, "colspan", 1)
            is_header = cell.tag.lower() == "th"

            for dc in range(colspan):
                cc = c + dc
                while len(row) <= cc:
                    row.append(None)
                row[cc] = text
                if rowspan > 1:
                    pending[cc] = (rowspan - 1, text, rowspan)

            merges.append(
                Merge(
                    row=r,
                    col=c,
                    rowspan=rowspan,
                    colspan=colspan,
                    text=text,
                    is_header=is_header,
                )
            )
            c += colspan

    return [[cell if cell is not None else "" for cell in row] for row in grid], merges


def _cell_text(cell) -> str:
    """Cell text without footnote/superscript markers.

    Handles both ``C$^{a}$`` and ``$S^{c}$`` forms. A genuine element cell such
    as ``Ca`` (calcium) is kept as-is because it carries no superscript group.
    """
    raw = "".join(cell.itertext())
    raw = FOOTNOTE_INLINE_RE.sub(lambda match: match.group(1), raw)
    return clean_text(FOOTNOTE_MARK_RE.sub("", raw))


def _int_attr(cell, name: str, default: int) -> int:
    try:
        value = int(cell.get(name, default) or default)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _looks_like_data_row(row: list[str]) -> bool:
    non_empty = [cell for cell in row if clean_text(cell)]
    if len(non_empty) < 2:
        return False
    numeric = sum(1 for cell in row[1:] if is_numeric_like(cell))
    if numeric >= 1:
        return True
    first = clean_text(row[0]) if row else ""
    # Indexed inspection tables start with 1, 2, 3...
    if re.fullmatch(r"\d{1,3}", first) and len(non_empty) >= 3:
        return True
    # OCR emits circled item numbers as ``textcircled9``; the row is still data.
    if re.fullmatch(r"(?:text)?circled\d+", first, re.IGNORECASE) and len(non_empty) >= 3:
        return True
    # A grade-like first cell plus several populated columns is also data.
    return bool(first and len(non_empty) >= 3 and looks_like_grade(first))


def _is_header_like(row: list[str]) -> bool:
    first = clean_text(row[0]) if row else ""
    if not first:
        return False
    if not any(marker in first for marker in HEADER_FIRST_MARKERS):
        return False
    # A row carrying a bare number is data even when its first cell looks like
    # a header keyword (GB/T 2965 表6 starts with "化学成分a | 每批1份 | 3.2").
    # Range labels (≤40h, >40) stay headers.
    return not any(
        re.fullmatch(r"\d+(?:\.\d+)?", clean_text(cell))
        for cell in row[1:]
        if clean_text(cell)
    )


def _looks_like_range_header(row: list[str]) -> bool:
    non_empty = [clean_text(cell) for cell in row if clean_text(cell)]
    if len(non_empty) < 2:
        return False
    if (
        row
        and looks_like_grade(row[0])
        and clean_text(row[0]) not in HEADER_MARKERS
    ):
        return False
    matches = sum(1 for cell in non_empty if RANGE_HEADER_RE.match(cell))
    if matches < max(2, len(non_empty) - 1):
        return False
    # A plain number in the first cell is a data row (GB/T 3191 T6 starts
    # with 1060 / H112 / ≤150), not a range-header label such as ≤40h.
    first = clean_text(row[0]) if row else ""
    return not re.fullmatch(r"\d+(?:\.\d+)?", first)


def _detect_header_rows(rows: list[list[str]]) -> int:
    if len(rows) <= 1:
        return 1
    max_scan = min(8, len(rows) - 1)
    saw_header = False
    for r in range(1, max_scan + 1):
        row = rows[r]
        if _is_header_like(row):
            saw_header = True
            continue
        first = clean_text(row[0]) if row else ""
        if _looks_like_data_row(row) and not _looks_like_range_header(row):
            return max(1, r)
        if saw_header and _looks_like_range_header(row) and not looks_like_grade(first):
            continue
        if _looks_like_data_row(row):
            return max(1, r)
    return 1


def _detect_block_header_rows(rows: list[list[str]]) -> int:
    if len(rows) <= 1:
        return 1
    max_scan = min(4, len(rows) - 1)
    for r in range(1, max_scan + 1):
        if _looks_like_data_row(rows[r]):
            return max(1, r)
    return 1


def _build_header_paths(rows: list[list[str]], header_rows: int) -> list[list[str]]:
    if not rows:
        return []
    n_cols = max(len(row) for row in rows)
    paths: list[list[str]] = []
    for c in range(n_cols):
        parts: list[str] = []
        for r in range(min(header_rows, len(rows))):
            text = clean_text(rows[r][c]) if c < len(rows[r]) else ""
            if text and text not in parts:
                parts.append(text)
        paths.append(parts)
    return _backfill_truncated_header(paths)


def _backfill_truncated_header(paths: list[list[str]]) -> list[list[str]]:
    """Restore a parent header cell whose colspan is one column short.

    GB/T 1591 table 11 declares ``colspan=9`` over ten temperature/direction
    subcolumns, so the last column loses its top-level "KV2/J" header. When a
    column shares the previous column's parent chain but is one level short,
    inherit the missing parents.
    """
    for index in range(1, len(paths)):
        path = paths[index]
        previous = paths[index - 1]
        missing = len(previous) - len(path)
        if (
            len(path) >= 2
            and len(previous) > len(path)
            and path[:-1] == previous[missing:-1]
        ):
            paths[index] = previous[:missing] + path
    return paths


def _collect_units(header_paths: list[list[str]], context: str) -> list[str]:
    units: list[str] = []
    for path in header_paths:
        unit = parse_unit(" ".join(path))
        if unit and unit not in units:
            units.append(unit)
    if "单位为毫米" in clean_text(context) and "mm" not in units:
        units.append("mm")
    return units


def _collect_footnotes(
    node, rows: list[list[str]], after_context: str = ""
) -> list[str]:
    notes: list[str] = []
    for text in node.xpath(".//sup//text()"):
        cleaned = clean_text(text)
        if cleaned and cleaned not in notes:
            notes.append(cleaned)
    for row in rows:
        if is_footnote_row(row):
            cleaned = max(
                (clean_text(cell) for cell in row if clean_text(cell)),
                key=len,
                default="",
            )
            if cleaned and cleaned not in notes:
                notes.append(cleaned)
            continue
        for cell in row:
            cleaned = clean_text(cell)
            if cleaned.startswith("注") and len(cleaned) > 2 and cleaned not in notes:
                notes.append(cleaned)
    for line in after_context.splitlines():
        cleaned = clean_text(line.lstrip("*#> ").strip())
        if cleaned.startswith("注") and len(cleaned) > 2 and cleaned not in notes:
            notes.append(cleaned)
    return notes


def _is_repeated_header_row(row: list[str]) -> bool:
    if not row:
        return False
    first = clean_text(row[0])
    if first not in REPEATED_HEADER_KEYS:
        return False
    non_empty = [clean_text(cell) for cell in row if clean_text(cell)]
    if len(non_empty) < 3:
        return False
    return not any(is_numeric_like(cell) for cell in row[1:])


def _table_number(caption: str | None) -> str:
    if not caption:
        return ""
    match = TABLE_NUMBER_RE.search(caption)
    return clean_text(match.group(1)).lower() if match else ""


def _header_signature(table: TableGrid) -> tuple[str, ...]:
    return tuple(clean_text(path[-1]) if path else "" for path in table.header_paths)


def _caption_compatible(previous: TableGrid, current: TableGrid) -> bool:
    if previous.n_cols != current.n_cols:
        return False
    return _header_similar(_header_signature(previous), _header_signature(current))


def _header_similar(left: tuple[str, ...], right: tuple[str, ...]) -> bool:
    if not left or len(left) != len(right):
        return False
    compared = [index for index, value in enumerate(left) if value and right[index]]
    if not compared:
        return False
    matches = sum(1 for index in compared if left[index] == right[index])
    return matches / len(compared) >= 0.6


def _is_continuation(previous: TableGrid, current: TableGrid) -> bool:
    if current.page_no != previous.page_no + 1:
        return False
    previous_no = _table_number(previous.caption)
    current_no = _table_number(current.caption)
    if previous_no and current_no and previous_no != current_no:
        return False
    if not previous_no and not current_no:
        return False
    continued = "续" in (current.caption or "")
    if previous_no and not current_no and not continued:
        return False
    if not previous_no and current_no and not continued:
        return False
    if continued and not current_no:
        current_no = previous_no
    if previous.n_cols != current.n_cols:
        return False
    return _header_similar(_header_signature(previous), _header_signature(current))


def _continuation_drop_rows(table: TableGrid) -> int:
    if table.header_rows <= 0:
        return 0
    if table.rows and _looks_like_data_row(table.rows[0]) and not _is_header_like(table.rows[0]):
        return 0
    return table.header_rows


def _append_continuation(previous: TableGrid, current: TableGrid) -> None:
    drop = _continuation_drop_rows(current)
    offset = len(previous.rows)
    for row in current.rows[drop:]:
        padded = list(row) + [""] * (previous.n_cols - len(row))
        previous.rows.append(padded[: previous.n_cols])
    for merge in current.merges:
        if merge.row < drop:
            continue
        previous.merges.append(
            Merge(
                row=merge.row - drop + offset,
                col=merge.col,
                rowspan=merge.rowspan,
                colspan=merge.colspan,
                text=merge.text,
                is_header=merge.is_header,
            )
        )
    previous.n_rows = len(previous.rows)
    previous.continuation_of = previous.continuation_of or previous.table_id
    previous.merged_pages = (
        previous.merged_pages or [previous.page_no]
    ) + [current.page_no]
    if not previous.caption and current.caption:
        previous.caption = current.caption
    if current.context:
        previous.context = ((previous.context or "") + "\n" + current.context)[-2000:]
    for unit in current.units:
        if unit not in previous.units:
            previous.units.append(unit)
    for note in current.footnotes:
        if note not in previous.footnotes:
            previous.footnotes.append(note)
    previous.raw_html = (previous.raw_html + current.raw_html)[:50000]
    previous.blocks = _split_blocks(previous)


def merge_continuations(tables: list[TableGrid]) -> list[TableGrid]:
    merged: list[TableGrid] = []
    for table in tables:
        if merged and _is_continuation(merged[-1], table):
            _append_continuation(merged[-1], table)
        else:
            merged.append(table)
    return merged


def _split_blocks(table: TableGrid) -> list[TableBlock]:
    if not table.rows:
        return []
    starts = [0]
    for r in range(table.header_rows + 1, len(table.rows)):
        if not _is_repeated_header_row(table.rows[r]):
            continue
        if r > 0 and _is_repeated_header_row(table.rows[r - 1]):
            continue
        starts.append(r)

    blocks: list[TableBlock] = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(table.rows)
        block_rows = table.rows[start:end]
        header_rows = table.header_rows if start == 0 else _detect_block_header_rows(block_rows)
        header_rows = max(1, min(header_rows, len(block_rows)))
        header_paths = _build_header_paths(block_rows, header_rows)
        blocks.append(
            TableBlock(
                block_id=f"{table.table_id}-B{index + 1}",
                start_row=start,
                header_rows=header_rows,
                header_paths=header_paths,
                rows=block_rows,
            )
        )
    return blocks
