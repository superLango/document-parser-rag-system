"""Document export helpers: hansonDoc schema, JSON, CSV and XLSX."""

from __future__ import annotations

import csv
import io
import json
import sys
from pathlib import Path
from typing import Any


def _hanson_builder(engine_root: Path):
    root = Path(engine_root)
    if not (root / "tools" / "export_hanson_schema.py").exists():
        from .config import ENGINE_ROOT

        root = ENGINE_ROOT
    root_text = str(root)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)
    from tools.export_hanson_schema import build_payload

    return build_payload


def hanson_payload(
    result: dict[str, Any],
    *,
    engine_root: Path,
    timing_seconds: float = 0.0,
    template_id: str | None = None,
    template_name: str | None = None,
    job_dir: Path | None = None,
    dictionary_path: str | Path | None = None,
) -> dict[str, Any]:
    builder = _hanson_builder(engine_root)
    return builder(
        result,
        timing_seconds,
        template_id=template_id or "6e2ad0d7-f92a-4663-b5cf-ae01c2378fa7",
        template_name=template_name or "产品标准抽取模板",
        job_dir=job_dir,
        dictionary_path=dictionary_path,
    )


def _record_row(record: dict[str, Any]) -> list[list[Any]]:
    rows: list[list[Any]] = []
    properties = record.get("properties") or {}
    for prop, value in properties.items():
        if not isinstance(value, dict):
            continue
        rows.append(
            [
                record.get("record_id"),
                record.get("grade") or "",
                record.get("condition") or "",
                prop,
                value.get("raw") or value.get("text") or "",
                value.get("value"),
                value.get("unit") or "",
                value.get("comparator") or "",
                value.get("evidence_id") or "",
            ]
        )
    return rows


def records_csv(records: list[dict[str, Any]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "record_id",
            "grade",
            "condition",
            "property",
            "raw",
            "value",
            "unit",
            "comparator",
            "evidence_id",
        ]
    )
    for record in records:
        for row in _record_row(record):
            writer.writerow(row)
    return buffer.getvalue().encode("utf-8-sig")


def _records_sheet(workbook: Any, records: list[dict[str, Any]]) -> None:
    sheet = workbook.active
    sheet.title = "记录"
    sheet.append(
        [
            "record_id",
            "grade",
            "condition",
            "property",
            "raw",
            "value",
            "unit",
            "comparator",
            "evidence_id",
        ]
    )
    for record in records:
        for row in _record_row(record):
            sheet.append(row)


def _items_sheet(workbook: Any, items: list[dict[str, Any]]) -> None:
    sheet = workbook.create_sheet("项目清单")
    sheet.append(
        [
            "item_raw",
            "item_canonical",
            "item_family",
            "status",
            "method_standard",
            "method_code",
            "method_name",
        ]
    )
    for item in items:
        sheet.append(
            [
                item.get("item_raw") or "",
                item.get("item_canonical") or "",
                item.get("item_family") or "",
                item.get("status") or "",
                item.get("method_standard") or "",
                item.get("method_code") or "",
                item.get("method_name") or "",
            ]
        )


def _clauses_sheet(workbook: Any, clauses: list[dict[str, Any]]) -> None:
    sheet = workbook.create_sheet("条款")
    sheet.append(["clause_id", "title", "page_no", "kind", "status", "fields"])
    for clause in clauses:
        sheet.append(
            [
                clause.get("clause_id") or "",
                clause.get("title") or "",
                clause.get("page_no"),
                clause.get("kind") or "",
                clause.get("status") or "",
                json.dumps(clause.get("fields") or {}, ensure_ascii=False),
            ]
        )


def xlsx_bytes(
    result: dict[str, Any],
    records: list[dict[str, Any]],
    items: list[dict[str, Any]],
    clauses: list[dict[str, Any]],
) -> bytes:
    from openpyxl import Workbook

    workbook = Workbook()
    _records_sheet(workbook, records)
    _items_sheet(workbook, items)
    _clauses_sheet(workbook, clauses)
    document = result.get("document") or {}
    info = workbook.create_sheet("标准信息")
    info.append(["标准名称", document.get("title") or ""])
    info.append(["标准编号", document.get("standard_no") or ""])
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def export_bytes(
    export_format: str,
    *,
    result: dict[str, Any],
    records: list[dict[str, Any]],
    items: list[dict[str, Any]],
    clauses: list[dict[str, Any]],
    engine_root: Path,
    timing_seconds: float = 0.0,
    job_dir: Path | None = None,
    dictionary_path: str | Path | None = None,
) -> tuple[bytes, str, str]:
    payload = dict(result)
    payload["records"] = records
    if export_format == "hanson":
        return (
            json.dumps(
                hanson_payload(
                    payload,
                    engine_root=engine_root,
                    timing_seconds=timing_seconds,
                    job_dir=job_dir,
                    dictionary_path=dictionary_path,
                ),
                ensure_ascii=False,
                indent=2,
            ).encode("utf-8"),
            "application/json",
            "json",
        )
    if export_format == "json":
        return (
            json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
            "application/json",
            "json",
        )
    if export_format == "csv":
        return records_csv(records), "text/csv; charset=utf-8", "csv"
    if export_format == "xlsx":
        return (
            xlsx_bytes(payload, records, items, clauses),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "xlsx",
        )
    raise ValueError(f"unsupported export format: {export_format}")
