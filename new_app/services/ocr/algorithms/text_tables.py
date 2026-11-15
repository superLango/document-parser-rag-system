"""Tier-1 borderless table detection from text coordinates.

``page.find_tables()`` only understands drawn borders, and its ``strategy="text"``
mode splits every word into a column.  This module clusters words into rows by
vertical overlap and into columns by "whitespace lanes" that no word crosses,
then validates the grid (numeric ratio + domain header keywords) before it is
handed to :mod:`table_grid`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html import escape

TABLE_HEADER_KEYWORDS = (
    "牌号", "钢号", "钢级", "元素", "化学成分", "力学性能", "抗拉", "屈服",
    "伸长", "收缩", "硬度", "冲击", "成分", "规格", "厚度", "直径", "尺寸",
    "试验", "温度", "方向", "状态", "取样", "热处理",
    "grade", "tensile", "yield", "elongation", "hardness", "impact",
    "composition", "element", "thickness", "diameter", "temperature",
    "specimen", "condition",
)


@dataclass
class TextTable:
    """A table recovered from word coordinates."""

    html: str
    y0: float
    rows: list[list[str]] = field(default_factory=list)

    @property
    def n_rows(self) -> int:
        return len(self.rows)

    @property
    def n_cols(self) -> int:
        return len(self.rows[0]) if self.rows else 0


def build_table(
    words,
    bbox: list[float] | None = None,
    *,
    min_rows: int = 4,
    min_cols: int = 3,
    min_numeric_ratio: float = 0.2,
    min_header_hits: int = 1,
) -> TextTable | None:
    """Return a validated :class:`TextTable` or ``None``.

    ``words`` uses the PyMuPDF layout ``(x0, y0, x1, y1, text, ...)``.  ``bbox``
    is optional and expected in the same coordinate system.
    """
    items = _normalize_words(words, bbox)
    if len(items) < min_rows * min_cols:
        return None
    rows = _cluster_rows(items)
    if len(rows) < min_rows:
        return None
    heights = sorted(float(word["h"]) for word in items)
    median_height = heights[len(heights) // 2] if heights else 0.0
    band = _table_band(rows, median_height, min_rows=min_rows, min_cols=min_cols)
    if band is None:
        return None
    rows = band
    columns = _column_lanes([word for row in rows for word in row])
    if len(columns) < min_cols:
        return None
    grid = _fill_grid(rows, columns)
    if _numeric_ratio(grid) < min_numeric_ratio:
        return None
    if _header_hits(grid[:3]) < min_header_hits:
        return None
    parts = ["<table>"]
    for row in grid:
        cells = "".join(f"<td>{escape(cell)}</td>" for cell in row)
        parts.append(f"<tr>{cells}</tr>")
    parts.append("</table>")
    return TextTable(
        html="".join(parts),
        y0=min(float(word["y0"]) for row in rows for word in row),
        rows=grid,
    )


def build_table_html(words, bbox: list[float] | None = None, **kwargs) -> str:
    table = build_table(words, bbox, **kwargs)
    return table.html if table else ""


def _normalize_words(
    words, bbox: list[float] | None
) -> list[dict[str, float | str]]:
    items: list[dict[str, float | str]] = []
    for item in words:
        if len(item) < 5:
            continue
        text = str(item[4]).strip()
        if not text:
            continue
        x0, y0, x1, y1 = (float(value) for value in item[:4])
        if x1 <= x0 or y1 <= y0:
            continue
        if bbox is not None and len(bbox) >= 4:
            cx = (x0 + x1) / 2
            cy = (y0 + y1) / 2
            if not (bbox[0] <= cx <= bbox[2] and bbox[1] <= cy <= bbox[3]):
                continue
        items.append(
            {
                "x0": x0,
                "y0": y0,
                "x1": x1,
                "y1": y1,
                "h": y1 - y0,
                "text": text,
            }
        )
    return items


def _cluster_rows(items: list[dict]) -> list[list[dict]]:
    ordered = sorted(items, key=lambda word: ((word["y0"] + word["y1"]) / 2, word["x0"]))
    rows: list[list[dict]] = []
    centers: list[float] = []
    for word in ordered:
        center = (word["y0"] + word["y1"]) / 2
        tolerance = 0.6 * max(float(word["h"]), 1e-9)
        for index in range(len(rows) - 1, max(-1, len(rows) - 4), -1):
            if abs(center - centers[index]) <= tolerance:
                rows[index].append(word)
                centers[index] = (centers[index] * (len(rows[index]) - 1) + center) / len(
                    rows[index]
                )
                break
        else:
            rows.append([word])
            centers.append(center)
    return [sorted(row, key=lambda word: word["x0"]) for row in rows]


def _table_band(
    rows: list[list[dict]], min_gutter: float, *, min_rows: int, min_cols: int
) -> list[list[dict]] | None:
    """Longest run of consecutive rows that already look like table rows.

    Prose paragraphs above/below a borderless table would otherwise add words
    that cross every column lane and collapse the grid into one column.
    """
    flags = [_gap_count(row, min_gutter) + 1 >= min_cols for row in rows]
    best_length, best_start = 0, 0
    start: int | None = None
    for index, flag in enumerate([*flags, False]):
        if flag and start is None:
            start = index
        elif not flag and start is not None:
            if index - start > best_length:
                best_length, best_start = index - start, start
            start = None
    if best_length < min_rows:
        return None
    end = best_start + best_length
    # A header row often uses merged cells and has one gap fewer; keep up to
    # three preceding rows while they still carry column separations.
    extended = 0
    while (
        best_start > 0
        and extended < 3
        and _gap_count(rows[best_start - 1], min_gutter) >= 1
    ):
        best_start -= 1
        extended += 1
    return rows[best_start:end]


def _gap_count(row: list[dict], min_gutter: float) -> int:
    intervals = sorted((float(word["x0"]), float(word["x1"])) for word in row)
    merged: list[list[float]] = []
    for x0, x1 in intervals:
        if merged and x0 <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], x1)
        else:
            merged.append([x0, x1])
    return sum(
        1
        for index in range(1, len(merged))
        if merged[index][0] - merged[index - 1][1] >= min_gutter
    )


def _column_lanes(items: list[dict]) -> list[tuple[float, float]]:
    """Vertical whitespace lanes: x ranges no word crosses."""
    intervals = sorted((float(word["x0"]), float(word["x1"])) for word in items)
    merged: list[list[float]] = []
    for x0, x1 in intervals:
        if merged and x0 <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], x1)
        else:
            merged.append([x0, x1])
    # A word gap inside one cell ("抗拉强度 Rm") is narrower than a column
    # gutter; only gaps at least one glyph high become column splits.
    heights = sorted(float(word["h"]) for word in items)
    median_height = heights[len(heights) // 2] if heights else 0.0
    min_gutter = 1.0 * median_height
    lanes: list[list[float]] = []
    for x0, x1 in merged:
        if lanes and x0 - lanes[-1][1] < min_gutter:
            lanes[-1][1] = max(lanes[-1][1], x1)
        else:
            lanes.append([x0, x1])
    return [(lane[0], lane[1]) for lane in lanes]


def _fill_grid(
    rows: list[list[dict]], columns: list[tuple[float, float]]
) -> list[list[str]]:
    grid = [["" for _ in columns] for _ in rows]
    for row_index, row in enumerate(rows):
        for word in row:
            center = (float(word["x0"]) + float(word["x1"])) / 2
            column = _column_index(columns, center)
            if column is None:
                continue
            current = grid[row_index][column]
            grid[row_index][column] = f"{current} {word['text']}".strip()
    return grid


def _column_index(columns: list[tuple[float, float]], x: float) -> int | None:
    for index, (x0, x1) in enumerate(columns):
        if x0 <= x <= x1:
            return index
    return None


def _numeric_ratio(grid: list[list[str]]) -> float:
    cells = [cell for row in grid for cell in row if cell]
    if not cells:
        return 0.0
    numeric = sum(1 for cell in cells if re.search(r"\d", cell))
    return numeric / len(cells)


def _header_hits(rows: list[list[str]]) -> int:
    hits = 0
    for row in rows:
        for cell in row:
            lowered = cell.lower()
            if any(keyword in lowered for keyword in TABLE_HEADER_KEYWORDS):
                hits += 1
    return hits
