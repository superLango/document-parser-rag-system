"""记录归一化流水线（S1）。

输入：v2 记录或金标同构记录（字段兼容：category/类别、item/项目名称、grade/材料牌号…）
输出：canonical record（见 schema/record.v1.schema.json）+ diagnostics + status。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from .aliases import extract_document_aliases
from .conditions import normalize_conditions, normalize_unit
from .grade import parse_grade_cell
from .items import normalize_item

CONDITION_KEY_MAP = {
    "temperature": "试验温度",
    "direction": "方向",
    "state": "试样状态",
    "size": "尺寸厚度",
    "method": "试验方法",
    "sampling": "取样数量",
    "position": "位置",
    "surface": "其他",
}
ENRICH_KEY_MAP = {
    "method": "试验方法",
    "state": "试样状态",
    "size": "尺寸厚度",
    "position": "位置",
    "sampling": "取样数量",
    "sampling_note": "取样说明",
}
REQUIREMENT_OPERATORS = ("≥", "≤", "<", ">", "=")


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _infer_operator(requirement: str) -> str:
    text = _clean(requirement)
    for operator in REQUIREMENT_OPERATORS:
        if text.startswith(operator):
            return operator
    if "~" in text or "至" in text:
        return "~"
    return ""


def _extract_conditions(record: dict[str, Any], aliases: dict[str, str]) -> dict[str, str]:
    raw: dict[str, Any] = {}
    conditions = record.get("conditions") or {}
    if isinstance(conditions, dict):
        for key, value in conditions.items():
            raw[CONDITION_KEY_MAP.get(str(key), str(key))] = value
    enrichment = record.get("enrichment") or {}
    if isinstance(enrichment, dict):
        for key, value in enrichment.items():
            mapped = ENRICH_KEY_MAP.get(str(key))
            if mapped and mapped not in raw and _clean(value):
                raw[mapped] = value
    return normalize_conditions(raw, aliases)


def _evidence(record: dict[str, Any]) -> dict[str, Any]:
    evidence = record.get("evidence")
    if isinstance(evidence, dict):
        result = dict(evidence)
    else:
        result = {}
    source_table = record.get("source_table") or record.get("table_id")
    if source_table and "table_id" not in result:
        result["table_id"] = str(source_table)
    if "page_no" not in result and record.get("page_no") is not None:
        result["page_no"] = record.get("page_no")
    if "source" not in result:
        if str(record.get("channel") or "") == "table" or source_table:
            result["source"] = "table"
        elif str(record.get("channel") or "") == "metadata":
            result["source"] = "metadata"
        else:
            result["source"] = "unknown"
    return result


def normalize_record(record: dict[str, Any], aliases: dict[str, str] | None = None) -> dict[str, Any]:
    aliases = aliases or {}
    diagnostics: list[dict[str, Any]] = []
    category = _clean(record.get("category") or record.get("类别") or record.get("feature"))
    item_raw = record.get("item") or record.get("项目名称") or record.get("measure")
    item, item_aliases = normalize_item(item_raw)
    grade_raw = _clean(record.get("grade") or record.get("材料牌号"))
    grade_info = parse_grade_cell(grade_raw, header="牌号") if grade_raw else {"grades": [], "rejected": []}
    grades = [item["grade"] for item in grade_info.get("grades") or []]
    grade_aliases: list[str] = []
    for item_grade in grade_info.get("grades") or []:
        grade_aliases.extend(item_grade.get("aliases") or [])
    requirement = _clean(record.get("requirement") or record.get("标准要求"))
    unit = normalize_unit(record.get("unit") or record.get("单位"))
    conditions = _extract_conditions(record, aliases)
    operator = _infer_operator(requirement)
    source = record.get("source") if isinstance(record.get("source"), dict) else {}
    if not source:
        source = {
            "channel": record.get("channel") or "",
            "table_id": record.get("source_table") or record.get("table_id") or "",
            "raw": record.get("raw") or "",
        }

    status = "ok"
    if not category:
        diagnostics.append({"code": "missing_category", "field": "category", "message": "缺少类别", "severity": "error"})
        status = "unresolved"
    if not item and category != "标准信息":
        diagnostics.append({"code": "missing_item", "field": "item", "message": "缺少项目名", "severity": "error"})
        status = "unresolved"
    if category != "标准信息" and not requirement:
        diagnostics.append({"code": "missing_requirement", "field": "requirement", "message": "缺少要求值", "severity": "error"})
        status = "unresolved"
    if grade_raw and not grades:
        diagnostics.append({
            "code": "grade_rejected", "field": "grade",
            "message": f"牌号无法解析: {grade_raw[:60]}", "severity": "warn",
            "raw": grade_raw,
        })
        if status == "ok":
            status = "warn"
    if category not in {"标准信息", ""} and not grades and status == "ok":
        diagnostics.append({"code": "missing_grade", "field": "grade", "message": "缺少牌号", "severity": "warn"})
        status = "warn"
    if not source.get("table_id") and not source.get("page_no") and source.get("source") == "unknown":
        diagnostics.append({"code": "missing_evidence", "field": "evidence", "message": "缺少来源信息", "severity": "info"})

    return {
        "record_id": str(record.get("record_id") or ""),
        "schema_version": "record.v1",
        "category": category,
        "item": item,
        "item_aliases": item_aliases,
        "grade": grades[0] if grades else "",
        "grade_aliases": list(dict.fromkeys(grade_aliases + grades[1:])),
        "requirement": requirement,
        "operator": operator,
        "unit": unit,
        "conditions": conditions,
        "enrichment": record.get("enrichment") or {},
        "evidence": _evidence(record),
        "status": status,
        "diagnostics": diagnostics,
        "source": source,
    }


def normalize_records(records: Iterable[dict[str, Any]], aliases: dict[str, str] | None = None) -> list[dict[str, Any]]:
    return [normalize_record(record, aliases) for record in records]


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    status = Counter(record.get("status") for record in records)
    categories = Counter(record.get("category") for record in records)
    codes = Counter()
    for record in records:
        for diagnostic in record.get("diagnostics") or []:
            codes[diagnostic.get("code") or ""] += 1
    resolved = sum(1 for record in records if record.get("grade") or record.get("category") == "标准信息")
    return {
        "total": len(records),
        "status": dict(status),
        "categories": dict(categories),
        "diagnostics": dict(codes),
        "grade_resolved": resolved,
        "grade_resolved_rate": round(resolved / len(records), 4) if records else 0.0,
    }


def _load_payload(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    return data.get("records") or data.get("items") or []


def _document_aliases(ocr_path: Path | None) -> dict[str, str]:
    if not ocr_path or not ocr_path.exists():
        return {}
    data = json.loads(ocr_path.read_text(encoding="utf-8"))
    pages = [str(page.get("markdown") or "") for page in data.get("pages") or []]
    return extract_document_aliases(pages)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="app_v3 S1 记录归一化流水线")
    parser.add_argument("--input", required=True, help="assembly-report.json 或 {records:[...]}")
    parser.add_argument("--output", required=True, help="归一化输出 JSON")
    parser.add_argument("--ocr", default="", help="可选：ocr.json，用于文档内状态别名挖掘")
    args = parser.parse_args(argv)

    records = _load_payload(Path(args.input))
    aliases = _document_aliases(Path(args.ocr) if args.ocr else None)
    normalized = normalize_records(records, aliases)
    payload = {
        "schema_version": "normalized.v1",
        "source": str(args.input),
        "aliases": aliases,
        "summary": summarize(normalized),
        "records": normalized,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    summary = payload["summary"]
    print(f"[normalize] total={summary['total']} status={summary['status']} "
          f"grade_resolved={summary['grade_resolved']} ({summary['grade_resolved_rate']}) "
          f"-> {output}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
