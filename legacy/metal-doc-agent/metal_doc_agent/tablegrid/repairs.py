"""Explicit hard-table repairs (M1.5.5).

Repairs are kept in ``configs/table_repairs.json`` so each document-specific
fix is reviewable. Values are taken from the source PDF; ``<prev>`` copies the
same column from the previous row. Generic parsing rules stay in the parser.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from ..contracts import DocumentMeta, TableGrid
from .normalize import clean_text, is_footnote_row
from .parser import merge_continuations, rebuild_table

NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")

STANDARD_KEY_RE = re.compile(
    r"(?:GB\s*[-/]?\s*T|GJB|JB\s*[-/]?\s*T|ISO|ASTM|JIS|EN|HB|Q|JX|YS|YY)"
    r"\s*[-_—]?\s*\d+(?:\.\d+)?(?:\s*[-_—]\s*\d{2,4})?",
    re.IGNORECASE,
)


def apply_table_repairs(
    tables: list[TableGrid],
    document: DocumentMeta,
    config_path: str | Path | None = None,
    learned_path: str | Path | None = None,
) -> list[TableGrid]:
    """Apply reviewed configs plus learned document/template rules.

    ``config_path`` stays the human-reviewed production file. ``learned_path``
    is the self-heal rule store: document rules replay on re-parse, approved
    templates replay on documents with the same table signature.
    """

    specs = _load_document_specs(config_path, document)
    learned = _load_json(learned_path)
    specs = {
        **(specs or {}),
        **(_matching_document_specs(learned.get("documents") or {}, document) or {}),
    }
    if not specs and not learned:
        return tables

    by_id = {table.table_id: table for table in tables}
    applied = False
    for table_id, spec in specs.items():
        table = by_id.get(table_id)
        if table is None:
            continue
        _apply(table, spec, by_id)
        applied = True

    templates = learned.get("templates") or {}
    if templates:
        for table in tables:
            if table.table_id in specs:
                continue
            template = templates.get(table_signature(table)) or {}
            if template.get("status") != "approved":
                continue
            if template.get("table_id") != table.table_id:
                continue
            spec = _template_spec(template.get("spec") or {}, table)
            if spec:
                _apply(table, spec, by_id)
                applied = True
    if not applied:
        return tables
    return merge_continuations(tables)


def table_signature(table: TableGrid) -> str:
    """Stable identity of a table layout, used to reuse approved repairs."""

    payload = {
        "profile": table.profile,
        "caption": clean_text(table.caption),
        "header_rows": table.header_rows,
        "header_paths": [
            [clean_text(part) for part in path] for path in table.header_paths
        ],
        "n_cols": table.n_cols,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _load_json(path: str | Path | None) -> dict:
    if path is None:
        return {}
    file_path = Path(path)
    if not file_path.exists():
        return {}
    try:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _load_document_specs(
    config_path: str | Path | None, document: DocumentMeta
) -> dict:
    data = _load_json(config_path)
    return _matching_document_specs(data.get("documents") or {}, document)


def _matching_document_specs(documents: dict, document: DocumentMeta) -> dict:
    specs = next(
        (documents[key] for key in _document_keys(document) if key in documents),
        None,
    )
    if specs:
        return specs
    haystack = " ".join(
        part for part in (document.file_name, document.title) if part
    ).upper()
    for key, value in documents.items():
        if key.upper() in haystack:
            return value
    return {}


def _template_spec(spec: dict, table: TableGrid) -> dict:
    """Keep only template parts that are safe for this table instance."""

    if not isinstance(spec, dict):
        return {}
    source_numbers = set(
        NUMBER_RE.findall(
            " ".join(clean_text(cell) for row in table.rows for cell in row)
        )
    )
    result: dict = {}
    header_rows = spec.get("header_rows")
    if header_rows is not None:
        try:
            value = int(header_rows)
        except (TypeError, ValueError):
            value = -1
        if 0 <= value <= len(table.rows):
            result["header_rows"] = value
    replace_rows: dict[str, list[str]] = {}
    for key, values in (spec.get("replace_rows") or {}).items():
        try:
            index = int(key)
        except (TypeError, ValueError):
            continue
        if not 0 <= index < len(table.rows) or not isinstance(values, list):
            continue
        cells = [str(cell) for cell in values]
        if all(_grounded(cell, source_numbers) for cell in cells):
            replace_rows[str(index)] = cells
    if replace_rows:
        result["replace_rows"] = replace_rows
    patch_cells: dict[str, dict[str, str]] = {}
    for key, cells in (spec.get("patch_cells") or {}).items():
        try:
            index = int(key)
        except (TypeError, ValueError):
            continue
        if not 0 <= index < len(table.rows) or not isinstance(cells, dict):
            continue
        row: dict[str, str] = {}
        for col_key, value in cells.items():
            try:
                column = int(col_key)
            except (TypeError, ValueError):
                continue
            text = str(value)
            if 0 <= column < table.n_cols and _grounded(text, source_numbers):
                row[str(column)] = text
        if row:
            patch_cells[str(index)] = row
    if patch_cells:
        result["patch_cells"] = patch_cells
    delete_rows = [
        int(value)
        for value in (spec.get("delete_rows") or [])
        if str(value).lstrip("-").isdigit() and 0 <= int(value) < len(table.rows)
    ]
    if delete_rows:
        result["delete_rows"] = sorted(set(delete_rows), reverse=True)
    return result


def _grounded(value: str, source_numbers: set[str]) -> bool:
    text = clean_text(value)
    if not text:
        return True
    numbers = NUMBER_RE.findall(text)
    if not numbers:
        return len(text) <= 12
    return all(number in source_numbers for number in numbers)


def _document_keys(document: DocumentMeta) -> list[str]:
    keys = [document.doc_id]
    for value in (
        document.standard_no,
        document.file_name,
        document.title,
    ):
        if not value:
            continue
        key = "".join(char for char in value.upper() if char.isalnum())
        if key and key not in keys:
            keys.append(key)
        for match in STANDARD_KEY_RE.finditer(value):
            standard_key = "".join(
                char for char in match.group(0).upper() if char.isalnum()
            )
            if standard_key and standard_key not in keys:
                keys.append(standard_key)
    return keys


def _apply(table: TableGrid, spec: dict, by_id: dict[str, TableGrid]) -> None:
    variants = spec.get("variants")
    if variants:
        chosen = next(
            (
                variant
                for variant in variants
                if _variant_matches(variant, table.n_cols)
            ),
            None,
        )
        if chosen is None:
            return
        spec = {
            **spec,
            **{
                key: value
                for key, value in chosen.items()
                if key != "when_n_cols"
            },
        }
    source_id = spec.get("copy_header_from")
    if source_id and source_id in by_id:
        source = by_id[source_id]
        header_rows = int(spec.get("header_rows", source.header_rows))
        table.rows[:header_rows] = [list(row) for row in source.rows[:header_rows]]
        table.header_rows = header_rows
    copy_rows = spec.get("copy_rows_from")
    if copy_rows:
        source = by_id.get(copy_rows.get("source", ""))
        if source is not None:
            start = int(copy_rows.get("from_row", 0))
            header_rows = int(spec.get("header_rows", table.header_rows))
            table.rows = [
                list(row) for row in table.rows[:header_rows]
            ] + [list(row) for row in source.rows[start:]]
    if "header_rows" in spec:
        table.header_rows = int(spec["header_rows"])
    if spec.get("keep_header_rows_only"):
        table.rows = [list(row) for row in table.rows[: table.header_rows]]
    if spec.get("caption"):
        table.caption = spec["caption"]

    for row_index in spec.get("swap_rows", []):
        if not 0 <= row_index < len(table.rows):
            continue
        row = table.rows[row_index]
        for left, right in spec.get("swap_column_pairs", []):
            if max(left, right) < len(row):
                row[left], row[right] = row[right], row[left]

    for row_index, values in spec.get("replace_rows", {}).items():
        index = int(row_index)
        if index >= len(table.rows):
            continue
        previous = table.rows[index - 1] if index > 0 else []
        table.rows[index] = _resolve(values, previous, table.n_cols)

    for row_index, cells in spec.get("patch_cells", {}).items():
        index = int(row_index)
        if index >= len(table.rows):
            continue
        row = table.rows[index]
        for col_index, value in cells.items():
            column = int(col_index)
            if column < len(row):
                row[column] = value

    for row_index in sorted(spec.get("delete_rows", []), reverse=True):
        if 0 <= row_index < len(table.rows):
            del table.rows[row_index]

    rebuild_table(table)
    if spec.get("trim_trailing"):
        _trim_trailing(table)
        rebuild_table(table)


def _variant_matches(variant: dict, n_cols: int) -> bool:
    if "when_n_cols" in variant:
        return int(variant["when_n_cols"]) == n_cols
    minimum = int(variant.get("when_min_n_cols", 0))
    maximum = int(variant.get("when_max_n_cols", 10**6))
    return minimum <= n_cols <= maximum


def _resolve(values: list[str], previous: list[str], n_cols: int) -> list[str]:
    resolved: list[str] = []
    for index, value in enumerate(values):
        if value == "<prev>":
            value = previous[index] if index < len(previous) else ""
        resolved.append(value)
    return (resolved + [""] * n_cols)[:n_cols]


def _trim_trailing(table: TableGrid) -> None:
    data_rows = [
        row
        for index, row in enumerate(table.rows)
        if index >= table.header_rows and not is_footnote_row(row)
    ]
    max_col = -1
    for row in data_rows:
        for index, cell in enumerate(row):
            if clean_text(cell):
                max_col = max(max_col, index)
    if max_col < 0 or max_col + 1 >= table.n_cols:
        return

    markers: list[str] = []
    for path in table.header_paths[max_col + 1 :]:
        for part in path:
            if part in {"不小于", "不大于"} and part not in markers:
                markers.append(part)

    table.rows = [row[: max_col + 1] for row in table.rows]
    table.n_cols = max_col + 1

    if markers and table.header_rows > 0:
        row_index = table.header_rows - 1
        existing = clean_text(table.rows[row_index][max_col])
        marker = markers[0]
        if marker not in existing:
            table.rows[row_index][max_col] = marker
