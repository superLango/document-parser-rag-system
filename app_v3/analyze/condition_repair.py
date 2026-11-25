"""S3 条件修复：从表标题/表头路径/行键补全温度、状态、尺寸、方向。"""
from __future__ import annotations

import re
from typing import Any

from app_v3.normalize.conditions import (
    DIRECTION_MAP,
    normalize_direction,
    normalize_size,
    normalize_state,
    normalize_temperature,
)

ROW_COL_RE = re.compile(r"-R(\d+)-C(\d+)")
TEMP_VALUE_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*(?:℃|°C|度)")
ROOM_RE = re.compile(r"室温|常温|room\s*temperature|\bRT\b", re.IGNORECASE)
STATE_WORDS = ("固溶退火态", "固溶处理", "固溶", "退火", "正火", "回火", "淬火", "时效", "冷加工", "热加工", "半硬", "软态")


def _table_text(table: dict[str, Any]) -> str:
    parts = [str(table.get("caption") or "")]
    for path in table.get("header_paths") or []:
        if isinstance(path, (list, tuple)):
            parts.append(" ".join(str(part) for part in path if part))
        else:
            parts.append(str(path or ""))
    return " ".join(parts)


def _row_col(record: dict[str, Any]) -> tuple[int | None, int | None]:
    match = ROW_COL_RE.search(str(record.get("record_id") or ""))
    if not match:
        return None, None
    return int(match.group(1)), int(match.group(2))


def _column_text(table: dict[str, Any], column: int | None) -> str:
    paths = table.get("header_paths") or []
    if column is not None and column < len(paths) and isinstance(paths[column], (list, tuple)):
        return " ".join(str(part) for part in paths[column] if part)
    return ""


def _find_temperature(text: str) -> str:
    match = TEMP_VALUE_RE.search(text or "")
    if match:
        return normalize_temperature(match.group(0))
    if ROOM_RE.search(text or ""):
        return "室温"
    return ""


def _find_state_column(table: dict[str, Any], row: list[str]) -> str:
    headers = [str((path[-1] if isinstance(path, (list, tuple)) and path else path) or "")
               for path in (table.get("header_paths") or [])]
    for column, header in enumerate(headers):
        if any(word in header for word in ("状态", "交货状态", "热处理状态")) and column < len(row):
            value = str(row[column] or "").strip()
            if value:
                return normalize_state(value)
    return ""


def _find_size_column(table: dict[str, Any], row: list[str]) -> str:
    headers = [str((path[-1] if isinstance(path, (list, tuple)) and path else path) or "")
               for path in (table.get("header_paths") or [])]
    for column, header in enumerate(headers):
        if any(word in header for word in ("厚度", "尺寸", "规格", "直径", "宽度")) and "偏差" not in header and column < len(row):
            value = str(row[column] or "").strip()
            if value and value not in {"-", "—", "–"}:
                return normalize_size(value)
    return ""


def _find_direction(text: str) -> str:
    lowered = (text or "").lower()
    for key, value in DIRECTION_MAP.items():
        if len(key) > 1 and key in lowered:
            return value
    return ""


def repair_conditions(records: list[dict[str, Any]], ocr: dict[str, Any] | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    tables = {str(table.get("table_id")): table for table in (ocr or {}).get("tables") or []}
    stats = {"total": len(records), "temperature": 0, "state": 0, "size": 0, "direction": 0, "normalized": 0}
    repaired: list[dict[str, Any]] = []
    for record in records:
        output = dict(record)
        conditions = dict(record.get("conditions") or {})
        table_id = str(record.get("source_table") or "")
        table = tables.get(table_id)
        changes: list[dict[str, Any]] = []
        if table is not None:
            row_index, column_index = _row_col(record)
            rows = table.get("rows") or []
            row = rows[row_index] if row_index is not None and row_index < len(rows) else []
            table_text = _table_text(table)
            column_text = _column_text(table, column_index)
            if not conditions.get("试验温度"):
                temperature = _find_temperature(column_text) or _find_temperature(table_text)
                if temperature:
                    conditions["试验温度"] = temperature
                    changes.append({"field": "试验温度", "value": temperature, "source": "header/caption"})
            else:
                normalized = normalize_temperature(conditions["试验温度"])
                if normalized != conditions["试验温度"]:
                    changes.append({"field": "试验温度", "value": normalized, "source": "normalize"})
                    conditions["试验温度"] = normalized
            if not conditions.get("试样状态"):
                state = _find_state_column(table, row)
                if not state:
                    for word in STATE_WORDS:
                        if word in table_text:
                            state = normalize_state(word)
                            break
                if state:
                    conditions["试样状态"] = state
                    changes.append({"field": "试样状态", "value": state, "source": "header/row"})
            if not conditions.get("尺寸厚度"):
                size = _find_size_column(table, row)
                if size:
                    conditions["尺寸厚度"] = size
                    changes.append({"field": "尺寸厚度", "value": size, "source": "header/row"})
            else:
                normalized = normalize_size(conditions["尺寸厚度"])
                if normalized != conditions["尺寸厚度"]:
                    changes.append({"field": "尺寸厚度", "value": normalized, "source": "normalize"})
                    conditions["尺寸厚度"] = normalized
            if not conditions.get("方向"):
                direction = _find_direction(column_text) or _find_direction(table_text)
                if direction:
                    conditions["方向"] = direction
                    changes.append({"field": "方向", "value": direction, "source": "header"})
        if changes:
            output["conditions"] = conditions
            output["audit"] = dict(record.get("audit") or {})
            output["audit"]["condition_repair"] = changes
            enrichment = dict(record.get("enrichment") or {})
            if conditions.get("试样状态") and not str(enrichment.get("state") or "").strip():
                enrichment["state"] = conditions["试样状态"]
            if conditions.get("尺寸厚度") and not str(enrichment.get("size") or "").strip():
                enrichment["size"] = conditions["尺寸厚度"]
            if enrichment:
                output["enrichment"] = enrichment
            stats["normalized"] += 1
            for change in changes:
                field = change["field"]
                if field == "试验温度":
                    stats["temperature"] += 1
                elif field == "试样状态":
                    stats["state"] += 1
                elif field == "尺寸厚度":
                    stats["size"] += 1
                elif field == "方向":
                    stats["direction"] += 1
        repaired.append(output)
    return repaired, stats
