"""表格牌号列分析：识别牌号列并解析行内牌号。"""
from __future__ import annotations

import re
from typing import Any

from app_v3.normalize.grade import header_is_grade_column, parse_grade_cell


def table_headers(table: dict[str, Any]) -> list[str]:
    paths = table.get("header_paths") or []
    headers: list[str] = []
    if paths:
        for path in paths:
            if isinstance(path, (list, tuple)):
                headers.append(" ".join(str(part) for part in path if str(part or "").strip()))
            else:
                headers.append(str(path or ""))
        return headers
    rows = table.get("rows") or []
    header_rows = int(table.get("header_rows") or 1)
    width = max((len(row) for row in rows), default=0)
    for column in range(width):
        parts = [str(rows[row][column]) for row in range(min(header_rows, len(rows))) if column < len(rows[row])]
        headers.append(" ".join(part for part in parts if part.strip()))
    return headers


def analyze_table_grades(table: dict[str, Any]) -> dict[str, Any]:
    headers = table_headers(table)
    grade_columns = [index for index, header in enumerate(headers) if header_is_grade_column(header)]
    if grade_columns and all("uns" in headers[index].lower() for index in grade_columns):
        grade_columns = []
    rows = table.get("rows") or []
    header_rows = int(table.get("header_rows") or 1)
    inferred_headers: dict[int, str] = {}
    if not grade_columns:
        uns_columns = [index for index, header in enumerate(headers) if "uns" in header.lower()]
        for uns in uns_columns:
            for column in range(uns - 1, -1, -1):
                values = [str(row[column]).strip() for row in rows[header_rows:]
                          if column < len(row) and str(row[column]).strip()]
                numeric = [value for value in values if re.fullmatch(r"\d{1,3}[A-Za-z]?", value)]
                if values and len(numeric) >= max(2, int(len(values) * 0.6)):
                    grade_columns.append(column)
                    inferred_headers[column] = "Grade (inferred)"
                    break
    header_rows = int(table.get("header_rows") or 1)
    row_grades: dict[int, list[dict[str, Any]]] = {}
    rejected: list[dict[str, Any]] = []
    for row_index in range(header_rows, len(rows)):
        row = rows[row_index]
        grades: list[dict[str, Any]] = []
        for column in grade_columns:
            if column >= len(row):
                continue
            header_text = inferred_headers.get(column) or (headers[column] if column < len(headers) else "牌号")
            parsed = parse_grade_cell(row[column], header=header_text)
            grades.extend(parsed.get("grades") or [])
            for value in parsed.get("rejected") or []:
                rejected.append({"row": row_index, "column": column, "value": value})
        if grades:
            unique: list[dict[str, Any]] = []
            seen: set[str] = set()
            for item in grades:
                key = item.get("grade", "").lower()
                if key in seen:
                    continue
                seen.add(key)
                unique.append(item)
            row_grades[row_index] = unique
    return {
        "table_id": table.get("table_id"),
        "header_rows": header_rows,
        "grade_columns": [
            {"index": index, "header": headers[index] if index < len(headers) else ""}
            for index in grade_columns
        ],
        "row_grades": row_grades,
        "rejected": rejected,
    }
