"""数据导出服务（阶段 2.2）。

提供通用的 Excel / CSV / JSON 导出能力，基于 openpyxl + StreamingResponse：
- export_excel：生成 .xlsx，首行表头，流式响应
- export_csv：生成 .csv（UTF-8 BOM，Excel 友好），流式响应
- export_json：生成 .json，流式响应

调用方提供 rows（dict 列表）+ columns（[{key, label}]），
无需关心格式细节。大数组通过 io.BytesIO/StringIO 一次性生成后流式返回。
"""

import csv
import io
import json
from datetime import datetime, timezone
from typing import Any

from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter


def _stamp(prefix: str, ext: str) -> str:
    """生成带时间戳的文件名。"""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"{prefix}_{ts}.{ext}"


def _cell_value(v: Any) -> Any:
    """将任意值转为可写入单元格的标量。"""
    if v is None:
        return ""
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, datetime):
        return v.isoformat()
    return v


def export_excel(
    rows: list[dict],
    columns: list[dict[str, str]],
    *,
    sheet_name: str = "Sheet1",
    filename_prefix: str = "export",
) -> StreamingResponse:
    """导出为 Excel(.xlsx)。

    Args:
        rows: dict 列表，每个 dict 的 key 对应 columns[].key。
        columns: [{"key": "name", "label": "名称"}]。
        sheet_name: 工作表名。
        filename_prefix: 下载文件名前缀。
    """
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name

    # 表头
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="4AA3FF")
    for col_idx, col in enumerate(columns, 1):
        cell = ws.cell(row=1, column=col_idx, value=col["label"])
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.freeze_panes = "A2"

    # 数据
    for row_idx, row in enumerate(rows, 2):
        for col_idx, col in enumerate(columns, 1):
            ws.cell(row=row_idx, column=col_idx, value=_cell_value(row.get(col["key"])))

    # 自适应列宽（粗略）
    for col_idx, col in enumerate(columns, 1):
        max_len = max(
            [len(str(col["label"]))] + [len(str(_cell_value(r.get(col["key"])))) for r in rows[:200]]
        )
        ws.column_dimensions[get_column_letter(col_idx)].width = min(max(max_len + 2, 10), 60)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{_stamp(filename_prefix, "xlsx")}"'},
    )


def export_csv(
    rows: list[dict],
    columns: list[dict[str, str]],
    *,
    filename_prefix: str = "export",
) -> StreamingResponse:
    """导出为 CSV（UTF-8 BOM，Excel 友好）。"""
    buf = io.StringIO()
    buf.write("\ufeff")  # BOM
    writer = csv.writer(buf)
    writer.writerow([col["label"] for col in columns])
    for row in rows:
        writer.writerow([_cell_value(row.get(col["key"])) for col in columns])
    buf.seek(0)

    return StreamingResponse(
        iter([buf.getvalue().encode("utf-8")]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{_stamp(filename_prefix, "csv")}"'},
    )


def export_json(
    rows: list[dict],
    *,
    filename_prefix: str = "export",
) -> StreamingResponse:
    """导出为 JSON。"""
    content = json.dumps(rows, ensure_ascii=False, default=str, indent=2)
    return StreamingResponse(
        iter([content.encode("utf-8")]),
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{_stamp(filename_prefix, "json")}"'},
    )


def export_data(
    rows: list[dict],
    columns: list[dict[str, str]],
    *,
    format: str = "excel",
    sheet_name: str = "Sheet1",
    filename_prefix: str = "export",
) -> StreamingResponse:
    """按格式分发导出。format ∈ {excel/xlsx, csv, json}。"""
    fmt = format.lower()
    if fmt in ("excel", "xlsx"):
        return export_excel(rows, columns, sheet_name=sheet_name, filename_prefix=filename_prefix)
    if fmt == "csv":
        return export_csv(rows, columns, filename_prefix=filename_prefix)
    if fmt == "json":
        return export_json(rows, filename_prefix=filename_prefix)
    raise ValueError(f"不支持的导出格式: {format}")
