"""Let the model plan a table-level repair from the source table itself.

The audit pass can only judge records that were already extracted. For a
feedback like "室温拉伸大部分内容有问题", most fields may be missing, so the
model must instead read the source table and propose a ``table_repair`` spec
(header rows / replaced rows / patched cells). The spec is executed by the
existing L1 sandbox re-parse and must pass the normal gate; the model never
writes code or production files.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from ..contracts import Record, TableGrid
from ..tablegrid.normalize import clean_text
from .planner import _parse_json

NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")
MAX_ROWS = 80
MAX_RECORDS = 40
ALLOWED_KEYS = {
    "reason",
    "header_rows",
    "replace_rows",
    "patch_cells",
    "delete_rows",
}
PROMPT = """你是金属材料文档抽取修复规划器。下面是原文表格的结构化内容和当前抽取记录，以及用户反馈。
请生成一个 table_repair 方案，让重新抽取后能正确覆盖源表内容。只输出 JSON：
{"reason":"...","header_rows":2,"replace_rows":{"0":["性能","400℃","500℃"]},"patch_cells":{"2":{"1":"≥590"}},"delete_rows":[]}
规则：
- header_rows：表头行数
- replace_rows：键是行号（0-based），值是该行完整单元格数组
- patch_cells：键是行号，值是 {列号: 新值}
- delete_rows：要删除的行号
- 只能修改表格结构/单元格，不能编造源表没有的数据；可以补充 ≥/≤ 等比较符和“性能/牌号/温度”等表头词
- 源表表头里的 ≥/≤/＞/＜ 必须同时写进对应数据单元格（如 "≥590"、"≤150"），否则抽取器会丢失比较符
- 只针对表 {table_id}
源表：{table}
当前记录：{records}
反馈：{feedback}
"""


@dataclass
class TableFixPlan:
    table_id: str
    spec: dict[str, Any]
    reason: str = ""


def plan_table_fix(
    table: TableGrid,
    records: list[Record],
    feedback: str,
    *,
    model_url: str | None,
    model_name: str,
    timeout: float = 60.0,
) -> TableFixPlan | None:
    if not model_url:
        return None
    prompt = (
        PROMPT.replace("{table_id}", table.table_id)
        .replace("{table}", _table_payload(table))
        .replace("{records}", _records_payload(records))
        .replace("{feedback}", clean_text(feedback))
    )
    try:
        import httpx

        with httpx.Client(timeout=timeout, trust_env=False) as client:
            response = client.post(
                f"{model_url.rstrip('/')}/chat/completions",
                json={
                    "model": model_name,
                    "messages": [
                        {"role": "system", "content": "只输出 JSON，不要解释。"},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.0,
                    "max_tokens": 1024,
                    "response_format": {"type": "json_object"},
                    "stream": False,
                },
            )
            response.raise_for_status()
        payload = _parse_json(response.json()["choices"][0]["message"]["content"])
    except Exception:  # noqa: BLE001 - planning is best effort
        return None
    spec = _validated_spec(payload, table)
    if spec is None:
        return None
    return TableFixPlan(
        table_id=table.table_id,
        spec=spec,
        reason=str(payload.get("reason") or "").strip(),
    )


def _table_payload(table: TableGrid) -> str:
    return json.dumps(
        {
            "table_id": table.table_id,
            "caption": table.caption,
            "profile": table.profile,
            "header_rows": table.header_rows,
            "header_paths": table.header_paths,
            "rows": table.rows[:MAX_ROWS],
        },
        ensure_ascii=False,
    )


def _records_payload(records: list[Record]) -> str:
    rows = []
    for record in records[:MAX_RECORDS]:
        rows.append(
            {
                "record_id": record.record_id,
                "grade": record.grade or record.grade_level,
                "condition": record.condition,
                "properties": {
                    name: value.raw or value.text
                    for name, value in record.properties.items()
                },
            }
        )
    return json.dumps(rows, ensure_ascii=False)


def _validated_spec(payload: dict[str, Any], table: TableGrid) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    spec: dict[str, Any] = {}
    source_numbers = set(NUMBER_RE.findall(_source_text(table)))

    header_rows = payload.get("header_rows")
    if header_rows is not None:
        try:
            value = int(header_rows)
        except (TypeError, ValueError):
            return None
        if 0 <= value <= len(table.rows):
            spec["header_rows"] = value

    replace_rows = _valid_replace_rows(payload.get("replace_rows"), table, source_numbers)
    if replace_rows:
        spec["replace_rows"] = replace_rows
    patch_cells = _valid_patch_cells(payload.get("patch_cells"), table, source_numbers)
    if patch_cells:
        spec["patch_cells"] = patch_cells
    delete_rows = _valid_delete_rows(payload.get("delete_rows"), table)
    if delete_rows:
        spec["delete_rows"] = delete_rows
    if not any(key in spec for key in ("header_rows", "replace_rows", "patch_cells", "delete_rows")):
        return None
    return spec


def _valid_replace_rows(
    raw: Any, table: TableGrid, source_numbers: set[str]
) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    if not isinstance(raw, dict):
        return result
    for key, values in raw.items():
        try:
            index = int(key)
        except (TypeError, ValueError):
            continue
        if not 0 <= index < len(table.rows) or not isinstance(values, list):
            continue
        cells = [str(value) for value in values]
        if not cells or len(cells) > table.n_cols:
            continue
        cells = (cells + [""] * table.n_cols)[: table.n_cols]
        if all(_grounded(cell, source_numbers) for cell in cells):
            result[str(index)] = cells
    return result


def _valid_patch_cells(
    raw: Any, table: TableGrid, source_numbers: set[str]
) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    if not isinstance(raw, dict):
        return result
    for row_key, cells in raw.items():
        try:
            row_index = int(row_key)
        except (TypeError, ValueError):
            continue
        if not 0 <= row_index < len(table.rows) or not isinstance(cells, dict):
            continue
        row: dict[str, str] = {}
        for col_key, value in cells.items():
            try:
                col_index = int(col_key)
            except (TypeError, ValueError):
                continue
            if not 0 <= col_index < table.n_cols:
                continue
            text = str(value)
            if _grounded(text, source_numbers):
                row[str(col_index)] = text
        if row:
            result[str(row_index)] = row
    return result


def _valid_delete_rows(raw: Any, table: TableGrid) -> list[int]:
    if not isinstance(raw, list):
        return []
    rows: list[int] = []
    for value in raw:
        try:
            index = int(value)
        except (TypeError, ValueError):
            continue
        if 0 <= index < len(table.rows):
            rows.append(index)
    return sorted(set(rows), reverse=True)


def _source_text(table: TableGrid) -> str:
    return " ".join(clean_text(cell) for row in table.rows for cell in row)


def _grounded(value: str, source_numbers: set[str]) -> bool:
    """Reject fabricated numbers; allow header words and comparator prefixes."""

    text = clean_text(value)
    if not text:
        return True
    numbers = NUMBER_RE.findall(text)
    if not numbers:
        return len(text) <= 12
    return all(number in source_numbers for number in numbers)
