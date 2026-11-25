"""牌号修复：对 grade 缺失/被污染的记录，从表格牌号列或文档级牌号修复。"""
from __future__ import annotations

import re
from typing import Any

from app_v3.analyze.document_grade import infer_document_grades
from app_v3.analyze.grade_columns import analyze_table_grades
from app_v3.normalize.grade import parse_grade_cell

ROW_INDEX_RE = re.compile(r"-R(\d+)-C\d+")


def _tables_by_id(ocr: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not ocr:
        return {}
    return {str(table.get("table_id")): table for table in ocr.get("tables") or []}


def _record_table_id(record: dict[str, Any]) -> str:
    table_id = record.get("source_table") or record.get("table_id")
    if table_id:
        return str(table_id)
    evidence = record.get("evidence") or {}
    ref = (evidence.get("requirement") or {}).get("ref") if isinstance(evidence, dict) else {}
    if isinstance(ref, dict) and ref.get("table_id"):
        return str(ref["table_id"])
    return ""


def _record_row_index(record: dict[str, Any]) -> int | None:
    if isinstance(record.get("row_index"), int):
        return int(record["row_index"])
    match = ROW_INDEX_RE.search(str(record.get("record_id") or ""))
    if match:
        return int(match.group(1))
    audit = record.get("audit") or {}
    if isinstance(audit, dict) and isinstance(audit.get("row_index"), int):
        return int(audit["row_index"])
    return None


def _is_probably_english(pages_markdown: list[str]) -> bool:
    text = " ".join(str(page or "") for page in pages_markdown[:4])
    if not text.strip():
        return False
    ascii_letters = sum(1 for char in text if ("a" <= char.lower() <= "z"))
    chinese = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
    return ascii_letters > 50 and ascii_letters > chinese * 2


def repair_records(records: list[dict[str, Any]], ocr: dict[str, Any] | None = None,
                   pages_markdown: list[str] | None = None, *,
                   table_repair: bool = False, document_repair: bool = True,
                   english_only: bool = True) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """返回修复后的记录与统计。不修改输入列表中的对象（浅拷贝）。

    默认保守模式：
    - table_repair=False：不直接用表内牌号覆盖被污染 grade（容易引入错误）；
    - document_repair=True：仅在文档唯一且为英文标准的单一合金牌号时修复；
    - english_only=True：中文文档不做文档级牌号强修。
    """
    tables = _tables_by_id(ocr)
    table_grade_cache: dict[str, dict[str, Any]] = {}
    doc_grades = infer_document_grades(pages_markdown or []) if pages_markdown else []
    likely_english = _is_probably_english(pages_markdown or [])
    unique_doc_grade = None
    if document_repair and len(doc_grades) == 1:
        candidate = doc_grades[0]
        name = str(candidate.get("grade") or "")
        if (not english_only or likely_english) and int(candidate.get("count") or 0) >= 2 and not name.lower().startswith("grade"):
            unique_doc_grade = candidate
    stats: dict[str, Any] = {
        "total": len(records),
        "already_ok": 0,
        "repaired_from_table": 0,
        "repaired_from_document": 0,
        "unresolved": 0,
        "document_grades": doc_grades,
        "examples": [],
    }
    repaired: list[dict[str, Any]] = []
    for record in records:
        output = dict(record)
        grade_text = str(record.get("grade") or record.get("材料牌号") or "").strip()
        parsed = parse_grade_cell(grade_text, header="牌号") if grade_text else {"grades": [], "rejected": []}
        if parsed.get("grades"):
            stats["already_ok"] += 1
            repaired.append(output)
            continue
        fixed = None
        source = ""
        table_id = _record_table_id(record)
        table = tables.get(table_id)
        row_index = _record_row_index(record)
        if table_repair and table is not None and row_index is not None:
            if table_id not in table_grade_cache:
                table_grade_cache[table_id] = analyze_table_grades(table)
            analysis = table_grade_cache[table_id]
            row_grades = (analysis.get("row_grades") or {}).get(row_index) or []
            if row_grades:
                fixed = row_grades[0]
                source = f"table:{table_id}:row{row_index}"
        if fixed is None and unique_doc_grade is not None:
            fixed = {"grade": unique_doc_grade["grade"], "aliases": unique_doc_grade.get("aliases") or []}
            source = "document_grade"
        if fixed:
            output["grade"] = fixed["grade"]
            aliases = list(fixed.get("aliases") or [])
            if unique_doc_grade and fixed["grade"] != unique_doc_grade["grade"]:
                aliases.append(unique_doc_grade["grade"])
            output["grade_aliases"] = list(dict.fromkeys(aliases))
            output["audit"] = dict(record.get("audit") or {})
            output["audit"]["grade_repaired"] = {"from": grade_text, "to": fixed["grade"], "source": source}
            if source == "document_grade":
                stats["repaired_from_document"] += 1
            else:
                stats["repaired_from_table"] += 1
            if len(stats["examples"]) < 10:
                stats["examples"].append({"record_id": record.get("record_id"), "from": grade_text, "to": fixed["grade"], "source": source})
        else:
            stats["unresolved"] += 1
            if grade_text and len(stats["examples"]) < 10:
                stats["examples"].append({"record_id": record.get("record_id"), "from": grade_text, "to": "", "source": "unresolved"})
        repaired.append(output)
    return repaired, stats
