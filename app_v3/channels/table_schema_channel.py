"""app_v3 原生表格 schema 通道（S16）：模型给列描述，代码展开记录。"""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from app_v3.channels.llm_client import chat
from app_v3.channels.table_recover import classify_header, measure_label
from app_v3.normalize.conditions import normalize_conditions, normalize_unit
from app_v3.normalize.grade import parse_grade_cell
from app_v3.normalize.items import normalize_item
from app_v3.table_program.ir import TableIR, load_tables

INSTRUCTION = Path(__file__).with_name("instruction_table_schema.txt").read_text(encoding="utf-8")
CONDITION_CN = {"temperature": "试验温度", "direction": "方向", "state": "试样状态",
                "size": "尺寸厚度", "method": "试验方法", "sampling": "取样数量",
                "position": "位置", "other": "其他"}
CATEGORY_KEYWORDS = (
    ("化学成分", ("化学", "成分", "元素", "Element", "Composition")),
    ("硬度试验", ("硬度", "HV", "HBW", "HRB", "HRC")),
    ("冲击试验", ("冲击", "KV2", "Impact")),
    ("弯曲试验", ("弯曲", "Bend")),
    ("高倍", ("晶粒", "高倍", "低倍", "夹杂", "偏析", "疏松", "脱碳", "发纹", "显微组织", "铁素体")),
    ("热处理制度", ("热处理", "淬火", "回火", "退火", "固溶", "时效")),
    ("高温拉伸", ("高温拉伸", "高温", "持久", "蠕变")),
    ("室温拉伸", ("抗拉", "屈服", "延伸", "伸长", "断面收缩", "Rm", "Rp")),
)


def fallback_category(table: TableIR, header: str) -> str:
    text = f"{table.caption} {header}"
    for category, keywords in CATEGORY_KEYWORDS:
        if any(keyword in text for keyword in keywords):
            return category
    return ""


def table_payload(table: TableIR) -> dict[str, Any]:
    sample = []
    for _, row in table.data_rows[:2]:
        sample.append([row[index] for index in range(min(table.width, len(row)))])
    return {
        "id": table.table_id,
        "caption": table.caption,
        "header_rows": table.header_rows,
        "rows": len(table.data_rows),
        "cols": table.width,
        "headers": [table.column_header(index) for index in range(table.width)],
        "sample": sample,
    }


def _extract_json(text: str) -> dict[str, Any] | None:
    text = str(text or "").strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        return None
    try:
        return json.loads(text[start:end + 1])
    except Exception:
        return None


def describe_table(table: TableIR, retries: int = 1) -> dict[str, Any] | None:
    prompt = INSTRUCTION + json.dumps(table_payload(table), ensure_ascii=False, separators=(",", ":"))
    for _ in range(retries + 1):
        try:
            parsed = _extract_json(chat(prompt, max_tokens=4096))
        except Exception:
            parsed = None
        if parsed and str(parsed.get("id")) == table.table_id and parsed.get("cols"):
            return parsed
    return None


def expand_table(table: TableIR, descriptor: dict[str, Any]) -> list[dict[str, Any]]:
    keys = [int(index) for index in descriptor.get("keys") or []]
    cols = {int(col["i"]): col for col in descriptor.get("cols") or [] if isinstance(col, dict) and col.get("i") is not None}
    records: list[dict[str, Any]] = []
    for row_index, row in table.data_rows:
        if not any(str(cell).strip() for cell in row):
            continue
        key_values = {str(index): row[index] if index < len(row) else "" for index in keys}
        # 行键中的牌号列：优先表头含牌号/钢号/Grade/UNS
        grades: list[str] = []
        for index in keys:
            header = table.column_header(index)
            if any(token in header for token in ("牌号", "钢号", "钢种", "Grade", "UNS", "材料")):
                parsed = parse_grade_cell(row[index] if index < len(row) else "", header="牌号")
                grades = [item["grade"] for item in parsed.get("grades") or []]
                if grades:
                    break
        if not grades:
            for index in keys:
                parsed = parse_grade_cell(row[index] if index < len(row) else "", header="牌号")
                grades = [item["grade"] for item in parsed.get("grades") or []]
                if grades:
                    break
        if not grades:
            grades = [""]
        row_conditions: dict[str, str] = {}
        for index, column in cols.items():
            if column.get("k") == "c" and index < len(row) and row[index]:
                condition_type = str(column.get("t") or "other")
                row_conditions[CONDITION_CN.get(condition_type, condition_type)] = row[index]
        for index, column in cols.items():
            if column.get("k") != "m":
                continue
            raw = str(row[index]).strip() if index < len(row) else ""
            if not raw or raw in {"-", "—", "–"}:
                continue
            if not re.search(r"\d", raw) and "不允许" not in raw:
                continue
            conditions: dict[str, str] = {}
            for condition in column.get("conds") or []:
                condition_type = str(condition.get("t") or "other")
                value = str(condition.get("v") or "")
                if value:
                    conditions[CONDITION_CN.get(condition_type, condition_type)] = value
            conditions.update(row_conditions)
            item_raw = str(column.get("m") or measure_label(table, index))
            item, _ = normalize_item(item_raw)
            category = str(column.get("cat") or descriptor.get("cat") or fallback_category(table, table.column_header(index)))
            unit = normalize_unit(str(column.get("u") or table.unit(index)))
            operator = str(column.get("op") or "")
            requirement = raw
            if "不允许" in raw:
                requirement = "不允许有"
            elif operator and raw[:1] not in "≥≤<>" and "~" not in raw and "至" not in raw:
                requirement = f"{operator}{raw}"
            for grade in grades:
                records.append({
                    "record_id": f"{table.table_id}-R{row_index}-C{index}-N",
                    "channel": "native_table",
                    "category": category,
                    "item": item,
                    "grade": grade,
                    "requirement": requirement,
                    "unit": unit,
                    "conditions": conditions,
                    "source_table": table.table_id,
                    "page_no": table.page_no,
                })
    return records


def describe_tables(tables: list[TableIR], concurrency: int = 6) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = {executor.submit(describe_table, table): table for table in tables}
        for future in as_completed(futures):
            table = futures[future]
            try:
                descriptor = future.result()
            except Exception:
                descriptor = None
            if descriptor:
                results[table.table_id] = descriptor
    return results


def extract_tables(tables: list[TableIR], descriptors: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for table in tables:
        descriptor = descriptors.get(table.table_id)
        if not descriptor:
            continue
        records.extend(expand_table(table, descriptor))
    return records


def select_candidate_tables(ocr: dict[str, Any], max_tables: int = 12) -> list[TableIR]:
    candidates = []
    for table in load_tables(ocr).values():
        if table.profile in {"title", "cover", "signature"}:
            continue
        rows = table.data_rows
        if len(rows) < 2 or table.width < 2:
            continue
        cells = [cell for _, row in rows for cell in row if str(cell).strip()]
        if not cells:
            continue
        numeric = sum(1 for cell in cells if re.fullmatch(r"[≤≥<>]?\d+(?:\.\d+)?(?:[~至]\d+(?:\.\d+)?)?\s*%?", str(cell).strip()))
        if numeric / len(cells) < 0.15:
            continue
        candidates.append((numeric, table))
    candidates.sort(key=lambda item: item[0], reverse=True)
    return [table for _, table in candidates[:max_tables]]
