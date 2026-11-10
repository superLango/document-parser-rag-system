"""Unified table IR (P6-B).

``TableGrid`` is a faithful grid: rows, header paths, merges, raw HTML. Every
extractor then re-derives the same facts from it — column roles come from
column bindings, value semantics are re-parsed inside each extractor, and
evidence ids are rebuilt by hand. That duplication is where table-specific
bugs hide.

This module builds one semantic view on top of the grid: each non-empty cell
carries its header path, column role, property, unit, value type and the
evidence id extraction would use. ``TableIR`` is derived state, never a second
source of truth: :func:`table_grid_from_ir` rebuilds the grid so the legacy
path can keep running unchanged while both are compared.

The adapter is lossless for everything extraction depends on (cell text,
header paths, header row count, units, footnotes, blocks, continuation
 metadata). ``raw_html`` intentionally stays only on ``TableGrid`` because it
is an audit payload, not semantics.
"""

from __future__ import annotations

import re

from ..contracts import (
    ColumnBindingResult,
    Merge,
    TableBlock,
    TableGrid,
    TableIR,
    TableIRBlock,
    TableIRCell,
)
from .normalize import (
    canonical_element,
    canonical_property,
    clean_text,
    is_footnote_row,
    parse_unit,
)

NA_VALUES = {"-", "--", "—", "——", "－", "/", "／"}
PLACEHOLDER_MARKERS = (
    "提供数据",
    "提供实测",
    "实测",
    "报出",
    "记录",
    "余量",
    "不规定",
    "协商确定",
    "协商",
    "协议",
)
CELL_VALUE_RE = re.compile(
    r"^\s*(>=|<=|≥|≤|>|<)?\s*(\d+(?:\.\d+)?)"
    r"(?:\s*[~～-]\s*(\d+(?:\.\d+)?))?\s*(?:[A-Za-z%℃°]{0,8})?\s*$"
)
ROW_KEY_MARKERS = ("牌号", "钢级", "合金牌号", "元素", "名称", "项目")
ROW_INDEX_MARKERS = ("序号",)
CONDITION_MARKERS = (
    "温度",
    "厚度",
    "直径",
    "方向",
    "状态",
    "规格",
    "等级",
    "位置",
    "条件",
    "试样",
    "炉号",
)


def build_table_ir(
    table: TableGrid,
    *,
    binding: ColumnBindingResult | None = None,
    doc_id: str | None = None,
) -> TableIR:
    """Project ``table`` (and optional column bindings) into the IR."""

    columns = _column_semantics(table, binding)
    spans = {(merge.row, merge.col): merge for merge in table.merges}
    element_rows = table.orientation == "element_rows"
    cells: list[TableIRCell] = []
    for row_index, row in enumerate(table.rows):
        header_row = row_index < table.header_rows
        footnote_row = not header_row and (
            is_footnote_row(row)
            or bool(row and clean_text(row[0]).startswith("*"))
        )
        for col_index, raw in enumerate(row):
            if not clean_text(raw):
                continue
            # Keep the source string verbatim: the IR is also the round-trip
            # grid adapter, and ``—`` must not be rewritten to ``-`` before an
            # evidence quote is recorded. Consumers normalize on read.
            text = str(raw)
            path = (
                [clean_text(part) for part in table.header_paths[col_index] if clean_text(part)]
                if col_index < len(table.header_paths)
                else []
            )
            role, prop, unit = columns.get(col_index, ("unknown", None, None))
            if header_row:
                raw_role = "header"
                cell_role = "header"
                value_type, comparator = "unknown", "unknown"
            elif footnote_row:
                raw_role = "footnote"
                cell_role = "footnote"
                value_type, comparator = "text", "text"
            else:
                raw_role = "data"
                cell_role = role
                value_type, comparator = classify_cell_value(text)
                if element_rows and col_index > 0:
                    # In a transposed chemistry table the row label *is* the
                    # property: 熔炼分析/成品分析 are both value columns even
                    # though neither column header names an element. Column
                    # bindings cannot see this, the IR can.
                    cell_role = "measure"
                    prop = canonical_element(clean_text(row[0])) or prop
                    unit = unit or (
                        "%" if table.profile == "chemical_composition" else None
                    )
            span = spans.get((row_index, col_index))
            cells.append(
                TableIRCell(
                    row=row_index,
                    col=col_index,
                    text=text,
                    raw_role=raw_role,
                    role=cell_role,
                    header_path=path,
                    property=prop if raw_role == "data" else None,
                    unit=unit if raw_role == "data" else None,
                    value_type=value_type,
                    comparator=comparator,
                    rowspan=span.rowspan if span else 1,
                    colspan=span.colspan if span else 1,
                    evidence_id=(
                        f"ev:{doc_id}:{table.table_id}:r{row_index}:c{col_index}"
                        if doc_id and raw_role != "header"
                        else ""
                    ),
                )
            )
    return TableIR(
        table_id=table.table_id,
        page_no=table.page_no,
        caption=table.caption,
        profile=table.profile,
        orientation=table.orientation,
        header_rows=table.header_rows,
        n_rows=max(table.n_rows, len(table.rows)),
        n_cols=max(table.n_cols, max((len(row) for row in table.rows), default=0)),
        header_paths=[
            [clean_text(part) for part in path if clean_text(part)]
            for path in table.header_paths
        ],
        cells=cells,
        blocks=[
            TableIRBlock(
                block_id=block.block_id,
                start_row=block.start_row,
                header_rows=block.header_rows,
                header_paths=block.header_paths,
            )
            for block in table.blocks
        ],
        units=list(table.units),
        footnotes=list(table.footnotes),
        continuation_of=table.continuation_of,
        merged_pages=list(table.merged_pages),
    )


def table_grid_from_ir(ir: TableIR) -> TableGrid:
    """Rebuild the extractable grid from the IR (used by the dual-run gate)."""

    rows = [["" for _ in range(ir.n_cols)] for _ in range(ir.n_rows)]
    merges: list[Merge] = []
    for cell in ir.cells:
        if cell.row >= len(rows) or cell.col >= ir.n_cols:
            continue
        rows[cell.row][cell.col] = cell.text
        if cell.rowspan > 1 or cell.colspan > 1:
            merges.append(
                Merge(
                    row=cell.row,
                    col=cell.col,
                    rowspan=cell.rowspan,
                    colspan=cell.colspan,
                    text=cell.text,
                    is_header=cell.raw_role == "header",
                )
            )
    blocks: list[TableBlock] = []
    for block in ir.blocks:
        end = _block_end(ir, block)
        blocks.append(
            TableBlock(
                block_id=block.block_id,
                start_row=block.start_row,
                header_rows=block.header_rows,
                header_paths=block.header_paths,
                rows=rows[block.start_row : end],
            )
        )
    return TableGrid(
        table_id=ir.table_id,
        page_no=ir.page_no,
        caption=ir.caption,
        n_rows=ir.n_rows,
        n_cols=ir.n_cols,
        header_rows=ir.header_rows,
        rows=rows,
        header_paths=ir.header_paths,
        merges=merges,
        units=list(ir.units),
        footnotes=list(ir.footnotes),
        profile=ir.profile,
        orientation=ir.orientation,
        blocks=blocks,
        continuation_of=ir.continuation_of,
        merged_pages=list(ir.merged_pages),
    )


def classify_cell_value(text: str) -> tuple[str, str]:
    """Return ``(value_type, comparator)`` for one data cell.

    This is a *description* of the raw cell, not an extraction decision: a
    bare number stays ``eq`` because the document did not print a comparator.
    Extractors still apply property defaults (``Rm`` is a minimum, impurity
    chemistry is a maximum) before emitting a value.
    """

    value = clean_text(text)
    if not value:
        return "unknown", "unknown"
    if value in NA_VALUES:
        return "na", "na"
    if any(marker in value for marker in PLACEHOLDER_MARKERS):
        return "placeholder", "text"
    match = CELL_VALUE_RE.match(value)
    if match is None:
        return "text", "text"
    marker = (match.group(1) or "").replace(">=", "≥").replace("<=", "≤")
    if match.group(3) is not None:
        return "range", "range"
    if marker in {"≥", ">"}:
        return "number", "min"
    if marker in {"≤", "<"}:
        return "number", "max"
    return "number", "eq"


def _column_semantics(
    table: TableGrid, binding: ColumnBindingResult | None
) -> dict[int, tuple[str, str | None, str | None]]:
    if binding is not None and binding.bindings:
        return {
            item.column: (item.role, item.property, item.unit)
            for item in binding.bindings
        }
    return _fallback_columns(table)


def _fallback_columns(
    table: TableGrid,
) -> dict[int, tuple[str, str | None, str | None]]:
    """Role inference for callers that have no column bindings.

    Kept intentionally narrow: a column is only called a measure when its
    header names a known property/element. Everything else stays ``unknown``
    so an unbound table cannot silently produce records.
    """

    columns: dict[int, tuple[str, str | None, str | None]] = {}
    for col, path in enumerate(table.header_paths):
        text = clean_text(" ".join(path))
        prop = None
        if table.profile == "chemical_composition":
            prop = canonical_element(text)
        prop = prop or canonical_property(text)
        if prop:
            columns[col] = ("measure", prop, parse_unit(text))
            continue
        if any(marker in text for marker in ROW_INDEX_MARKERS):
            columns[col] = ("row_index", None, None)
        elif any(marker in text for marker in ROW_KEY_MARKERS):
            columns[col] = ("row_key", None, None)
        elif any(marker in text for marker in CONDITION_MARKERS):
            columns[col] = ("condition", None, None)
        else:
            columns[col] = ("unknown", None, None)
    return columns


def _block_end(ir: TableIR, block: TableIRBlock) -> int:
    starts = sorted(item.start_row for item in ir.blocks)
    later = [value for value in starts if value > block.start_row]
    return later[0] if later else ir.n_rows
