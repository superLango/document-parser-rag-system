"""Data-driven hard-table repairs.

Each rule is reviewable JSON: a ``match`` block selects the table, and an
``action`` block applies one deterministic fix. Generic structure rules stay in
``table_grid.py``; this module only carries table-specific corrections that the
approved sample set confirms.
"""

import hashlib
import json
import re
from pathlib import Path

from ..contracts import DocumentMeta, TableGrid
from .normalize import clean_text
from .profile import annotate_table
from .table_grid import merge_continuations, rebuild_table

STANDARD_KEY_RE = re.compile(
    r"(?:GB\s*[-/]?\s*T|GJB|JB\s*[-/]?\s*T|ISO|ASTM|JIS|EN|HB|Q|JX|YS|YY)"
    r"\s*[-_—]?\s*\d+(?:\.\d+)?(?:\s*[-_—]\s*\d{2,4})?",
    re.IGNORECASE,
)

DEFAULT_RULES_PATH = Path(__file__).resolve().parent.parent / "data" / "table_repairs.json"


def table_signature(table: TableGrid) -> str:
    """Stable identity of a table layout, used to match reviewed repairs."""
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


def load_rules(path: str | Path | None = None) -> list[dict]:
    file_path = Path(path) if path else DEFAULT_RULES_PATH
    if not file_path.exists():
        return []
    try:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
    except ValueError:
        return []
    rules = payload.get("rules") if isinstance(payload, dict) else None
    return [rule for rule in rules or [] if isinstance(rule, dict)]


def apply_repairs(
    tables: list[TableGrid],
    *,
    document: DocumentMeta | None = None,
    rules: list[dict] | None = None,
    rules_path: str | Path | None = None,
) -> tuple[list[TableGrid], list[str]]:
    """Apply matching rules; returns repaired tables and applied rule ids."""

    active = rules if rules is not None else load_rules(rules_path)
    if not active:
        return tables, []

    applied: list[str] = []
    for rule in active:
        if not _matches(rule.get("match") or {}, tables, document):
            continue
        target = _select_table(rule.get("match") or {}, tables)
        if target is None:
            continue
        action = rule.get("action") or {}
        if not _apply_action(target, action):
            continue
        rebuild_table(target)
        annotate_table(target)
        applied.append(str(rule.get("rule_id") or "unnamed"))

    if not applied:
        return tables, []
    return merge_continuations(tables), applied


def _document_haystack(document: DocumentMeta | None) -> str:
    if document is None:
        return ""
    parts = [document.file_name, document.title]
    return " ".join(part for part in parts if part).upper()


def _document_standard_no(document: DocumentMeta | None) -> str:
    if document is None:
        return ""
    if document.standard_no:
        return clean_text(document.standard_no).upper()
    haystack = _document_haystack(document)
    match = STANDARD_KEY_RE.search(haystack)
    return clean_text(match.group(0)).upper() if match else ""


def _matches(match: dict, tables: list[TableGrid], document: DocumentMeta | None) -> bool:
    if not match:
        return False
    expected_standard = clean_text(match.get("standard_no")).upper()
    if expected_standard:
        actual = _document_standard_no(document)
        if not actual or expected_standard not in actual:
            return False
    expected_caption = clean_text(match.get("table_caption"))
    if expected_caption:
        if not any(expected_caption in clean_text(table.caption) for table in tables):
            return False
    expected_profile = str(match.get("profile") or "").strip()
    if expected_profile:
        if not any(table.profile == expected_profile for table in tables):
            return False
    expected_signature = str(match.get("signature") or "").strip()
    if expected_signature:
        if not any(table_signature(table) == expected_signature for table in tables):
            return False
    return True


def _select_table(match: dict, tables: list[TableGrid]) -> TableGrid | None:
    expected_profile = str(match.get("profile") or "").strip()
    expected_caption = clean_text(match.get("table_caption"))
    expected_signature = str(match.get("signature") or "").strip()
    for table in tables:
        if expected_signature and table_signature(table) != expected_signature:
            continue
        if expected_profile and table.profile != expected_profile:
            continue
        if expected_caption and expected_caption not in clean_text(table.caption):
            continue
        return table
    return None


def _apply_action(table: TableGrid, action: dict) -> bool:
    action_type = str(action.get("type") or "").strip().lower()
    if action_type == "rebuild_grid":
        return _rebuild_grid(table, action)
    if action_type == "header_rows":
        return _set_header_rows(table, action)
    if action_type == "patch_cells":
        return _patch_cells(table, action)
    if action_type == "replace_rows":
        return _replace_rows(table, action)
    if action_type == "delete_rows":
        return _delete_rows(table, action)
    if action_type == "trim_trailing":
        return _trim_trailing(table, action)
    return False


def _rebuild_grid(table: TableGrid, action: dict) -> bool:
    n_rows = int(action.get("rows") or 0)
    n_cols = int(action.get("columns") or 0)
    if n_rows <= 0 or n_cols <= 0:
        return False
    flat = [cell for row in table.rows for cell in row]
    flat = flat[: n_rows * n_cols]
    flat += [""] * (n_rows * n_cols - len(flat))
    table.rows = [flat[index * n_cols : (index + 1) * n_cols] for index in range(n_rows)]
    table.n_rows = n_rows
    table.n_cols = n_cols
    return True


def _set_header_rows(table: TableGrid, action: dict) -> bool:
    header_rows = int(action.get("value") or 0)
    if header_rows <= 0 or header_rows > len(table.rows):
        return False
    table.header_rows = header_rows
    return True


def _patch_cells(table: TableGrid, action: dict) -> bool:
    cells = action.get("cells") or []
    patched = False
    for cell in cells:
        row = int(cell.get("row", -1))
        col = int(cell.get("col", -1))
        if row < 0 or col < 0 or row >= len(table.rows) or col >= len(table.rows[row]):
            continue
        table.rows[row][col] = str(cell.get("value", ""))
        patched = True
    return patched


def _replace_rows(table: TableGrid, action: dict) -> bool:
    rows = action.get("rows") or []
    replaced = False
    for item in rows:
        row = int(item.get("row", -1))
        values = [str(value) for value in item.get("values") or []]
        if row < 0 or row >= len(table.rows) or not values:
            continue
        table.rows[row] = values[: table.n_cols] + [""] * max(
            0, table.n_cols - len(values)
        )
        replaced = True
    return replaced


def _delete_rows(table: TableGrid, action: dict) -> bool:
    indexes = {int(index) for index in action.get("rows") or []}
    if not indexes:
        return False
    kept = [row for index, row in enumerate(table.rows) if index not in indexes]
    if len(kept) == len(table.rows):
        return False
    table.rows = kept
    return True


def _trim_trailing(table: TableGrid, action: dict) -> bool:
    columns = int(action.get("columns") or 0)
    if columns <= 0:
        return False
    trimmed = False
    for index, row in enumerate(table.rows):
        if len(row) > columns:
            table.rows[index] = row[:columns]
            trimmed = True
    return trimmed
