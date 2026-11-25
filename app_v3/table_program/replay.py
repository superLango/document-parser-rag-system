"""表格程序回放校验：melt/pivot 记录必须覆盖来源值单元格。"""
from __future__ import annotations

from typing import Any

from .ir import TableIR


def _melt_specs(program: dict[str, Any]) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    for step in program.get("steps") or []:
        if str(step.get("op") or "") == "melt":
            specs.extend(step.get("value_columns") or [])
    return specs


def validate_program(program: dict[str, Any], ir: TableIR, records: list[dict[str, Any]]) -> dict[str, Any]:
    """校验记录是否覆盖所有非空值单元格（melt 场景）。

    返回 {"ok": bool, "missing": [...], "extra": [...], "coverage": float}。
    """
    specs = _melt_specs(program)
    if not specs:
        return {"ok": True, "missing": [], "extra": [], "coverage": 1.0}
    skip = set(program.get("skip_values") or {"", "-", "—", "–"})
    expected = set()
    for row_index, row in ir.data_rows:
        for spec in specs:
            column = int(spec.get("column") or 0)
            raw = str(row[column]).strip() if column < len(row) else ""
            if raw in skip:
                continue
            expected.add((row_index, column, raw))
    actual = set()
    for record in records:
        actual.add((record.get("source_row"), record.get("source_column"), str(record.get("raw") or "").strip()))
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    coverage = round(len(expected & actual) / len(expected), 4) if expected else 1.0
    return {"ok": not missing, "missing": missing[:20], "extra": extra[:20], "coverage": coverage}
