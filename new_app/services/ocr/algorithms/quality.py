"""Table-level quality scoring.

The document-level ``assess_quality`` only checks empty pages; routing needs a
per-table signal so prose fragments and hallucinated mini-tables do not reach a
recipe.  The score is intentionally simple and explainable: every deduction has
a flag that is persisted with the OCR artifact.
"""

from __future__ import annotations

import re

from ..contracts import TableGrid

NUMERIC_CELL_RE = re.compile(r"^[<>≤≥~～]?\s*[-+]?\d+(?:\.\d+)?\s*(?:%|℃)?$")


def score_table(table: TableGrid) -> tuple[float, list[str]]:
    flags: list[str] = []
    rows = table.rows or []
    header_rows = max(0, table.header_rows)
    data = rows[header_rows:] if header_rows else rows
    n_cols = table.n_cols or max((len(row) for row in rows), default=0)

    headers: list[str] = []
    for path in table.header_paths or []:
        headers.append(" ".join(str(part).strip() for part in path if str(part).strip()))
    if not headers and rows:
        headers = [str(cell) for cell in rows[0]]
    header_ratio = len([item for item in headers if item]) / max(1, n_cols)

    cells = [str(cell).strip() for row in data for cell in row if str(cell).strip()]
    numeric_ratio = sum(1 for cell in cells if NUMERIC_CELL_RE.match(cell)) / max(
        1, len(cells)
    )
    average_length = sum(len(cell) for cell in cells) / max(1, len(cells))
    width_ratio = sum(1 for row in data if len(row) == n_cols) / max(1, len(data))
    unique_rows = {tuple(str(cell).strip() for cell in row) for row in data}
    duplicate_ratio = 1 - len(unique_rows) / max(1, len(data))

    score = 1.0
    if not data:
        flags.append("no_data_rows")
        score -= 0.6
    elif len(data) < 2:
        flags.append("single_row")
        score -= 0.1
    if header_ratio < 0.5:
        flags.append("missing_header")
        score -= 0.35
    if n_cols <= 1:
        flags.append("single_column")
        score -= 0.3
    if cells and numeric_ratio < 0.1:
        flags.append("no_numeric_cells")
        score -= 0.2
    if n_cols <= 2 and average_length > 20:
        flags.append("prose_fragment")
        score -= 0.35
    if duplicate_ratio > 0.5:
        flags.append("repeated_rows")
        score -= 0.15
    if width_ratio < 0.8:
        flags.append("ragged_rows")
        score -= 0.1
    return round(max(0.0, min(1.0, score)), 3), flags


def score_tables(tables: list[TableGrid]) -> list[TableGrid]:
    for table in tables:
        table.quality, table.quality_flags = score_table(table)
    return tables
