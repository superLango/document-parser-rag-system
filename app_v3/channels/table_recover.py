"""表格补充通道（S8/S9）：从 OCR 表补充 v2 绑定遗漏的列/表。

原则：
- 只补充"缺失的度量列"（按 record_id 的列号判断），不替换 v2 已有列；
- 仅处理表头可识别为规范量的列（高倍/弯曲/冲击/硬度/拉伸）；
- 度量名从列头路径中取"最后一段有意义的标签"，跳过级别/不大于/数字/单位等条件段；
- 生成记录标记来源 `channel: recovered`，供验证器/评测使用。
"""
from __future__ import annotations

import re
from typing import Any

from app_v3.analyze.grade_columns import analyze_table_grades
from app_v3.normalize.grade import parse_grade_cell
from app_v3.normalize.items import normalize_item
from app_v3.table_program.ir import TableIR, load_tables

HIGH_MAG_KEYWORDS = ("偏析", "疏松", "低倍", "夹杂", "发纹", "脱碳", "晶粒", "显微组织", "铁素体", "斑点", "断口")
ROW_COL_RE = re.compile(r"-R(\d+)-C(\d+)")
CONDITION_SEGMENT_RE = re.compile(r"^(?:级别|不大于|不小于|[≥≤<>]|单位|注|产品|类别|牌号|序号)|^\d+(?:\.\d+)?$")


def measure_label(ir: TableIR, column: int) -> str:
    path = [str(part).strip() for part in ir.column_path(column) if str(part).strip()]
    if not path:
        return ""
    meaningful = [part for part in path if not CONDITION_SEGMENT_RE.search(part)]
    label = (meaningful or path)[-1]
    label = re.sub(r"[a-z]$", "", label) if len(label) > 2 else label
    return label


def classify_header(header: str) -> tuple[str, str, str] | None:
    text = str(header or "")
    if any(keyword in text for keyword in HIGH_MAG_KEYWORDS):
        return ("高倍", re.sub(r"[a-z]$", "", text).strip(), "级")
    if "弯曲" in text:
        return ("弯曲试验", "弯曲试验", "")
    if "冲击" in text or "KV" in text.upper():
        return ("冲击试验", "冲击吸收功(KV2)", "J")
    if any(code in text for code in ("硬度", "HV", "HBW", "HRB", "HRC")):
        return ("硬度试验", text, "")
    if "抗拉强度" in text or "Rm" in text:
        return ("室温拉伸", "抗拉强度(Rm)", "MPa")
    if "塑性延伸" in text or "Rp" in text:
        return ("室温拉伸", "规定塑性延伸强度(Rp0.2)", "MPa")
    if "断后伸长" in text or "伸长率" in text:
        return ("室温拉伸", "断后伸长率(A)", "%")
    return None


def _existing_columns(records: list[dict[str, Any]]) -> dict[str, set[int]]:
    columns: dict[str, set[int]] = {}
    for record in records:
        source = str(record.get("source_table") or "")
        match = ROW_COL_RE.search(str(record.get("record_id") or ""))
        if source and match:
            columns.setdefault(source, set()).add(int(match.group(2)))
    return columns


def recover_missing_columns(records: list[dict[str, Any]], ocr: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    tables = load_tables(ocr)
    existing = _existing_columns(records)
    recovered: list[dict[str, Any]] = []
    stats: dict[str, Any] = {"tables": 0, "records": 0, "categories": {}, "examples": []}
    for table_id, ir in tables.items():
        grade_info = analyze_table_grades({
            "table_id": table_id,
            "header_rows": ir.header_rows,
            "header_paths": ir.header_paths,
            "rows": ir.rows,
        })
        grade_columns = [column["index"] for column in grade_info.get("grade_columns") or []]
        measure_columns = []
        for index in range(ir.width):
            label = measure_label(ir, index)
            classified = classify_header(label) if label else None
            if classified and index not in grade_columns:
                measure_columns.append((index, classified))
        if not measure_columns:
            continue
        skip_columns = existing.get(table_id, set())
        generated = 0
        for row_index, row in ir.data_rows:
            if not any(str(cell).strip() for cell in row):
                continue
            grades: list[str] = []
            for grade_column in grade_columns:
                if grade_column < len(row):
                    parsed = parse_grade_cell(row[grade_column], header="牌号")
                    grades = [item["grade"] for item in parsed.get("grades") or []]
                    if grades:
                        break
            if not grades:
                grades = [""]
            for column, classified in measure_columns:
                if column in skip_columns:
                    continue
                raw = str(row[column]).strip() if column < len(row) else ""
                if not raw or raw in {"-", "—", "–"}:
                    continue
                if not re.search(r"\d", raw) and "不允许" not in raw:
                    continue
                category, item, unit = classified
                item = normalize_item(item)[0]
                requirement = raw
                if category == "高倍" and re.fullmatch(r"\d+(?:\.\d+)?", raw):
                    requirement = f"≤{raw}"
                if "不允许" in raw:
                    requirement = "不允许有"
                for grade in grades:
                    recovered.append({
                        "record_id": f"{table_id}-R{row_index}-C{column}-R",
                        "channel": "recovered",
                        "category": category,
                        "item": item,
                        "grade": grade,
                        "requirement": requirement,
                        "unit": unit,
                        "conditions": {},
                        "source_table": table_id,
                        "page_no": ir.page_no,
                    })
                    generated += 1
        if generated:
            stats["tables"] += 1
            stats["records"] += generated
            stats["categories"][category] = stats["categories"].get(category, 0) + generated
            if len(stats["examples"]) < 8:
                stats["examples"].append({"table_id": table_id, "records": generated})
    return recovered, stats
