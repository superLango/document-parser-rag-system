"""Document outline index: searchable view of tables, records and diagnostics."""

from __future__ import annotations

import re
from typing import Any

from .measures import canonical_measure, normalize

SECTION_BY_PROFILE = {
    "chemical_composition": "chemical",
    "mechanical_properties": "mechanical",
    "hardness": "mechanical",
    "dimension": "dimension",
    "inspection_rules": "clause",
    "inspection_rule": "clause",
}
TEMPERATURE_RE = re.compile(r"(室温|常温|高温|低温|-?\d{1,4}\s*[℃°C])")


def table_headers(
    table: dict[str, Any], diagnostics: list[dict[str, Any]] | None = None
) -> list[str]:
    headers: list[str] = []
    paths = table.get("header_paths") or []
    if paths and isinstance(paths[0], list):
        for row in paths:
            headers.extend(str(cell) for cell in row if str(cell).strip())
    elif isinstance(paths, list):
        headers.extend(str(cell) for cell in paths if str(cell).strip())
    headers.extend(str(cell) for cell in (table.get("headers") or []))
    if not headers and diagnostics:
        table_id = str(table.get("table_id") or "")
        for item in diagnostics:
            detail = item.get("detail") or {}
            if item.get("code") == "MEASURE_COLUMN_MISSING" and str(
                detail.get("table_id") or ""
            ) == table_id:
                headers = [str(cell) for cell in detail.get("headers") or []]
                break
    return list(dict.fromkeys(header for header in headers if header))


def _record_count(
    table: dict[str, Any], records: list[dict[str, Any]]
) -> int:
    if isinstance(table.get("records"), int):
        return int(table["records"])
    table_id = str(table.get("table_id") or "")
    return sum(1 for record in records if str(record.get("table_id") or "") == table_id)


def build_outline(
    tables: list[dict[str, Any]],
    records: list[dict[str, Any]] | None = None,
    diagnostics: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Index every table with the signals intent matching needs."""
    records = records or []
    diagnostics = diagnostics or []
    outline: list[dict[str, Any]] = []
    for table in tables:
        table_id = str(table.get("table_id") or "")
        headers = table_headers(table, diagnostics)
        measures = sorted(
            {measure for header in headers if (measure := canonical_measure(header))}
        )
        caption = str(table.get("caption") or "")
        profile = str(table.get("profile") or "")
        section_kind = str(
            table.get("section_kind") or SECTION_BY_PROFILE.get(profile, "")
        )
        haystack = normalize(" ".join([caption, *headers]))
        conditions = sorted(set(TEMPERATURE_RE.findall(haystack)))
        codes = sorted(
            {
                str(item.get("code") or "")
                for item in diagnostics
                if str((item.get("detail") or {}).get("table_id") or "") == table_id
            }
        )
        outline.append(
            {
                "table_id": table_id,
                "page_no": int(table.get("page_no") or 0),
                "caption": caption or None,
                "profile": profile,
                "orientation": table.get("orientation"),
                "section_kind": section_kind,
                "headers": headers,
                "header_paths": table.get("header_paths") or [],
                "measures": measures,
                "conditions": conditions,
                "records": _record_count(table, records),
                "diagnostics": codes,
            }
        )
    return outline
