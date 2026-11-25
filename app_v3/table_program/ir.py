"""表格 IR v1：OCR/表格结构 → 统一表格中间表示（P1 WP1.1）。

目标：让程序 DSL 与通道共享同一套表格表示，不依赖具体 OCR 结构。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TableIR:
    table_id: str
    page_no: int | None = None
    caption: str = ""
    header_rows: int = 1
    rows: list[list[str]] = field(default_factory=list)
    header_paths: list[list[str]] = field(default_factory=list)
    units: list[str] = field(default_factory=list)
    conditions: list[str] = field(default_factory=list)
    profile: str = ""

    @classmethod
    def from_ocr(cls, table: dict[str, Any]) -> "TableIR":
        rows = [[str(cell or "").strip() for cell in (row or [])] for row in table.get("rows") or []]
        width = max((len(row) for row in rows), default=0)
        rows = [row + [""] * (width - len(row)) for row in rows]
        return cls(
            table_id=str(table.get("table_id") or ""),
            page_no=table.get("page_no"),
            caption=str(table.get("caption") or ""),
            header_rows=int(table.get("header_rows") or 1),
            rows=rows,
            header_paths=[[str(part) for part in (path or [])] for path in table.get("header_paths") or []],
            units=[str(unit or "") for unit in table.get("column_units") or []],
            conditions=[str(condition or "") for condition in table.get("column_conditions") or []],
            profile=str(table.get("profile") or ""),
        )

    @property
    def width(self) -> int:
        return max((len(row) for row in self.rows), default=0)

    @property
    def data_rows(self) -> list[tuple[int, list[str]]]:
        return [(index, row) for index, row in enumerate(self.rows[self.header_rows:], start=self.header_rows)]

    def column_path(self, column: int) -> list[str]:
        if column < len(self.header_paths):
            return self.header_paths[column]
        return [row[column] for row in self.rows[: self.header_rows] if column < len(row)]

    def column_header(self, column: int) -> str:
        return " ".join(part for part in self.column_path(column) if part)

    def column_headers(self) -> list[str]:
        return [self.column_header(column) for column in range(self.width)]

    def unit(self, column: int) -> str:
        return self.units[column] if column < len(self.units) else ""

    def condition_hint(self, column: int) -> str:
        return self.conditions[column] if column < len(self.conditions) else ""

    def cell(self, row: int, column: int) -> str:
        return self.rows[row][column] if row < len(self.rows) and column < len(self.rows[row]) else ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "table_id": self.table_id,
            "page_no": self.page_no,
            "caption": self.caption,
            "header_rows": self.header_rows,
            "width": self.width,
            "headers": self.column_headers(),
            "units": self.units,
        }


def load_tables(ocr: dict[str, Any]) -> dict[str, TableIR]:
    return {str(table.get("table_id")): TableIR.from_ocr(table) for table in ocr.get("tables") or []}
