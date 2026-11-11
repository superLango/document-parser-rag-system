"""Multi-axis inspection table modeling.

Some acceptance standards describe sampling on several axes at once: forging
class (I/II/III/IV), supplier vs. purchaser, and single piece vs. batch. None
of the value columns is named ``取样数量``, so the generic inspection extractor
sees no quantity column and drops the whole table.

``TableFrame`` keeps the axis path of every value column and emits the rules
grouped by the first axis (the forging class), which is what the schema's
``类别`` column can represent. The remaining axes stay readable inside the
sampling note.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..contracts import TableGrid
from .normalize import clean_text, is_footnote_row

CLASS_ROOT_RE = re.compile(r"^(?:I{1,3}|IV|[ⅠⅡⅢⅣ])\s*类(?:锻件|件|别)?$")
ITEM_MARKERS = ("检验项目", "试验项目")
NOISE_MARKERS = ("序号", "备注")
AUX_MARKERS = ("取样部位", "试验方法", "检验方法", "抽样规定")
BLANK_VALUES = {"-", "--", "—", "——", "－", "／", "/"}
QUANTITY_HINTS = (
    "%",
    "％",
    "炉号",
    "抽检",
    "全检",
    "每批",
    "逐件",
    "每件",
    "不少于",
    "不大于",
    "多于",
    "按批",
)
QUANTITY_UNIT_RE = re.compile(r"\d+\s*(?:件|根|个|支|套|块|张)")
FOOTNOTE_SUFFIX_RE = re.compile(r"(?<=[\u4e00-\u9fff\)）])\s*[a-z]$")


@dataclass(frozen=True)
class TableAxis:
    column: int
    parts: tuple[str, ...]

    @property
    def root(self) -> str:
        return self.parts[0]

    @property
    def label(self) -> str:
        return " / ".join(self.parts)

    @property
    def sublabel(self) -> str:
        return " / ".join(self.parts[1:])


@dataclass
class TableFrame:
    item_columns: list[int]
    axes: list[TableAxis]
    header_rows: int


@dataclass
class FrameRow:
    row_index: int
    item: str
    item_column: int
    quantities: dict[str, str] = field(default_factory=dict)


def detect_multi_axis_inspection(table: TableGrid) -> TableFrame | None:
    """Return the axis frame when ``table`` is a class-based inspection table."""

    if table.header_rows < 3 or len(table.rows) <= table.header_rows:
        return None
    paths = _header_paths(table)
    if not paths:
        return None

    item_headers = [index for index, path in enumerate(paths) if _is_item_header(path)]
    if not item_headers:
        return None
    n_cols = max(
        table.n_cols,
        max((len(row) for row in table.rows), default=0),
    )
    start = max(item_headers) + 1
    first_value = _first_value_column(table, start, n_cols)
    if first_value is None:
        return None

    header_start = next(
        (
            index
            for index in range(start, len(paths))
            if _is_axis_header(paths[index])
        ),
        None,
    )
    if header_start is None:
        return None
    shift = max(0, first_value - header_start)

    noise_columns = {
        index
        for index, path in enumerate(paths)
        if any(marker in " ".join(path) for marker in NOISE_MARKERS)
    }
    axes: list[TableAxis] = []
    for column in range(first_value, n_cols):
        if column in noise_columns:
            continue
        index = column - shift
        if index < 0 or index >= len(paths):
            break
        path = paths[index]
        if _is_aux_header(path):
            continue
        parts = _axis_parts(path)
        if not parts:
            continue
        axes.append(TableAxis(column=column, parts=tuple(parts)))

    if len(axes) < 4:
        return None
    roots = {axis.root for axis in axes}
    if len(roots) < 2:
        return None
    if all("数量" in axis.label for axis in axes):
        return None
    if not any(
        CLASS_ROOT_RE.match(root) or "供方" in root or "需方" in root
        for root in roots
    ):
        return None
    return TableFrame(
        item_columns=list(range(min(item_headers), first_value)),
        axes=axes,
        header_rows=table.header_rows,
    )


def frame_rows(table: TableGrid, frame: TableFrame) -> list[FrameRow]:
    rows: list[FrameRow] = []
    for row_index in range(frame.header_rows, len(table.rows)):
        row = table.rows[row_index]
        if _footnote(row):
            continue
        item, item_column = _row_item(row, frame.item_columns)
        if not item:
            continue
        delta = _value_delta(row, frame, item)
        if delta < 0:
            item, item_column = _row_item(row, frame.item_columns[:-1])
            if not item:
                continue
        quantities = _row_quantities(row, frame.axes, delta)
        if not quantities:
            continue
        rows.append(
            FrameRow(
                row_index=row_index,
                item=item,
                item_column=item_column,
                quantities=quantities,
            )
        )
    return rows


def _header_paths(table: TableGrid) -> list[list[str]]:
    return [
        [clean_text(part) for part in path if clean_text(part)]
        for path in table.header_paths
    ]


def _is_item_header(path: list[str]) -> bool:
    if not path:
        return False
    text = " ".join(path)
    if not any(marker in text for marker in ITEM_MARKERS):
        return False
    if "数量" in text or "供方" in text or "需方" in text:
        return False
    return not CLASS_ROOT_RE.match(path[0])


def _is_axis_header(path: list[str]) -> bool:
    return any(CLASS_ROOT_RE.match(part) for part in path) or any(
        "供方" in part or "需方" in part for part in path
    )


def _is_aux_header(path: list[str]) -> bool:
    text = " ".join(path)
    return any(marker in text for marker in AUX_MARKERS)


def _axis_parts(path: list[str]) -> list[str]:
    if _is_item_header(path):
        return []
    parts: list[str] = []
    for raw in path:
        text = clean_text(raw)
        if not text:
            continue
        if any(marker in text for marker in NOISE_MARKERS):
            continue
        if text not in parts:
            parts.append(text)
    return parts


def _first_value_column(
    table: TableGrid, start: int, n_cols: int
) -> int | None:
    """Find the leftmost data column that holds sampling rules.

    The header is not always trustworthy: some tables give the item header a
    single column but lay the data out over two (class + sub-item). Locating
    the first rule column from the data keeps those tables aligned.
    """

    for column in range(start, n_cols):
        values = [
            clean_text(row[column])
            for row in table.rows[table.header_rows :]
            if column < len(row) and clean_text(row[column])
        ]
        if not values:
            continue
        hits = sum(1 for value in values if _quantity_like(value))
        if hits and hits / len(values) >= 0.5:
            return column
    return None


def _quantity_like(text: str) -> bool:
    value = clean_text(text)
    if not value or value in BLANK_VALUES:
        return False
    if re.search(r"\d\s*[%％]", value):
        return True
    if re.search(r"[~～]", value) and re.search(r"\d", value):
        return True
    if QUANTITY_UNIT_RE.search(value):
        return True
    return any(hint in value for hint in QUANTITY_HINTS)


def _footnote(row: list[str]) -> bool:
    first = clean_text(row[0]) if row else ""
    return first.startswith("*") or is_footnote_row(row)


def _clean_cell(text: str | None) -> str:
    value = clean_text(text)
    return FOOTNOTE_SUFFIX_RE.sub("", value).strip()


def _row_item(row: list[str], columns: list[int]) -> tuple[str, int]:
    """Use the most specific item cell (sub-item wins over its category)."""

    for column in reversed(columns):
        if column >= len(row):
            continue
        text = _clean_cell(row[column])
        if not text or text.isdigit():
            continue
        if any(marker in text for marker in ITEM_MARKERS):
            continue
        return text, column
    return "", columns[0] if columns else 0


def _value_delta(row: list[str], frame: TableFrame, item: str) -> int:
    """Detect rows whose value cells are shifted by one column.

    OCR/markup sometimes gives a top-level item one cell instead of the two
    columns reserved by the header (values move left), or lets a colspan item
    cell spill into the first value column (values move right).
    """

    if len(frame.item_columns) >= 2:
        second = frame.item_columns[-1]
        text = _clean_cell(row[second]) if second < len(row) else ""
        if text and _quantity_like(text):
            return -1
    first = frame.axes[0].column
    text = _clean_cell(row[first]) if first < len(row) else ""
    if text and text == item and not _quantity_like(text):
        return 1
    return 0


def _row_quantities(
    row: list[str], axes: list[TableAxis], delta: int = 0
) -> dict[str, str]:
    groups: list[tuple[str, list[tuple[str, str]]]] = []
    by_root: dict[str, list[tuple[str, str]]] = {}
    for axis in axes:
        column = axis.column + delta
        if column < 0 or column >= len(row):
            continue
        raw = _clean_cell(row[column])
        if not raw or raw in BLANK_VALUES:
            continue
        cells = by_root.get(axis.root)
        if cells is None:
            cells = []
            by_root[axis.root] = cells
            groups.append((axis.root, cells))
        cells.append((axis.sublabel, raw))

    quantities: dict[str, str] = {}
    for root, cells in groups:
        unique: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for cell in cells:
            if cell in seen:
                continue
            seen.add(cell)
            unique.append(cell)
        values = {raw for _, raw in unique}
        if len(values) == 1:
            quantities[root] = unique[0][1]
            continue
        quantities[root] = "；".join(
            f"{sub}：{raw}" if sub else raw for sub, raw in unique
        )
    return quantities
