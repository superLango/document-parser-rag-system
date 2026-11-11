"""Export exactly what the result table shows: category, fields and rows."""

from __future__ import annotations

import csv
import io
from typing import Any

TABLE_FORMATS = {"csv", "xlsx"}


def _cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, dict):
        for key in ("raw", "text", "value"):
            if value.get(key) not in (None, ""):
                return value[key]
        return ""
    if isinstance(value, (list, tuple)):
        return "；".join(str(item) for item in value if item not in (None, ""))
    return value


def _categories(schema: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in schema.get("categories") or [] if isinstance(item, dict)]


def _fields(category: dict[str, Any]) -> list[str]:
    fields = [str(name) for name in category.get("fields") or []]
    if fields:
        return fields
    seen: list[str] = []
    for record in category.get("records") or []:
        if not isinstance(record, dict):
            continue
        for name in record:
            if name not in seen:
                seen.append(str(name))
    return seen


def table_csv(schema: dict[str, Any]) -> bytes:
    categories = _categories(schema)
    columns: list[str] = []
    for category in categories:
        for name in _fields(category):
            if name not in columns:
                columns.append(name)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["类别", *columns])
    for category in categories:
        feature = category.get("feature") or ""
        records = category.get("records") or []
        if not records:
            writer.writerow([feature, *["" for _ in columns]])
            continue
        for record in records:
            if not isinstance(record, dict):
                continue
            writer.writerow(
                [feature, *[_cell(record.get(name)) for name in columns]]
            )
    return buffer.getvalue().encode("utf-8-sig")


def table_xlsx(schema: dict[str, Any]) -> bytes:
    from openpyxl import Workbook

    workbook = Workbook()
    workbook.remove(workbook.active)
    used: set[str] = set()
    for index, category in enumerate(_categories(schema), start=1):
        fields = _fields(category)
        title = _sheet_name(str(category.get("feature") or f"表{index}"), used)
        sheet = workbook.create_sheet(title)
        sheet.append(fields)
        for record in category.get("records") or []:
            if not isinstance(record, dict):
                continue
            sheet.append([_cell(record.get(name)) for name in fields])
    if not workbook.sheetnames:
        workbook.create_sheet("结果")
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _sheet_name(name: str, used: set[str]) -> str:
    cleaned = "".join(
        char for char in name if char not in '[]:*?/\\'
    ).strip() or "结果"
    cleaned = cleaned[:31]
    candidate = cleaned
    suffix = 2
    while candidate in used:
        tail = f"-{suffix}"
        candidate = f"{cleaned[: 31 - len(tail)]}{tail}"
        suffix += 1
    used.add(candidate)
    return candidate


def table_export_bytes(
    export_format: str, schema: dict[str, Any]
) -> tuple[bytes, str, str]:
    if export_format == "csv":
        return table_csv(schema), "text/csv; charset=utf-8", "csv"
    if export_format == "xlsx":
        return (
            table_xlsx(schema),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "xlsx",
        )
    raise ValueError(f"unsupported export format: {export_format}")


def result_table_schema(result: dict[str, Any]) -> dict[str, Any]:
    """Build the same table view when schema projection is unavailable."""

    tables = {
        str(table.get("table_id")): table
        for table in result.get("tables") or []
        if isinstance(table, dict)
    }
    groups: dict[str, dict[str, Any]] = {}
    for record in result.get("records") or []:
        if not isinstance(record, dict):
            continue
        table_id = str(record.get("source_table_id") or "")
        table = tables.get(table_id) or {}
        feature = str(table.get("caption") or table_id or "结果")
        group = groups.setdefault(
            feature,
            {"feature": feature, "fields": [], "records": []},
        )
        row: dict[str, Any] = {}
        if record.get("grade") or record.get("grade_level"):
            row["牌号"] = record.get("grade") or record.get("grade_level")
        if record.get("condition"):
            row["条件"] = record.get("condition")
        for name, value in (record.get("properties") or {}).items():
            if isinstance(value, dict):
                row[str(name)] = (
                    value.get("raw") or value.get("text") or value.get("value") or ""
                )
            else:
                row[str(name)] = value
        for name in row:
            if name not in group["fields"]:
                group["fields"].append(name)
        group["records"].append(row)
    return {"categories": list(groups.values())}

