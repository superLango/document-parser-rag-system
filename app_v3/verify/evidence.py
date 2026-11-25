"""证据验证：记录必须能回溯到来源（表/页/单元格/条款引文）。"""
from __future__ import annotations

import re
from typing import Any

ROW_RE = re.compile(r"-R(\d+)-C\d+")


def _table_id(record: dict[str, Any]) -> str:
    source = record.get("source") or {}
    evidence = record.get("evidence") or {}
    if source.get("table_id"):
        return str(source["table_id"])
    if record.get("source_table"):
        return str(record["source_table"])
    if evidence.get("table_id"):
        return str(evidence["table_id"])
    ref = (evidence.get("requirement") or {}).get("ref") if isinstance(evidence, dict) else {}
    if isinstance(ref, dict) and ref.get("table_id"):
        return str(ref["table_id"])
    return ""


def _page_no(record: dict[str, Any]) -> int | None:
    if isinstance(record.get("page_no"), int):
        return int(record["page_no"])
    source = record.get("source") or {}
    if isinstance(source.get("page_no"), int):
        return int(source["page_no"])
    evidence = record.get("evidence") or {}
    if isinstance(evidence.get("page_no"), int):
        return int(evidence["page_no"])
    return None


def validate_evidence(record: dict[str, Any], tables: dict[str, Any], page_count: int | None = None) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    category = str(record.get("category") or "")
    channel = str(record.get("channel") or (record.get("source") or {}).get("channel") or "")
    evidence = record.get("evidence") or {}
    table_id = _table_id(record)
    page_no = _page_no(record)
    if category == "标准信息":
        if channel == "metadata" or (isinstance(evidence, dict) and evidence.get("source") == "metadata"):
            return diagnostics
        diagnostics.append({"code": "metadata_evidence_missing", "field": "evidence", "severity": "warn",
                            "message": "标准信息缺少元数据来源"})
        return diagnostics
    if table_id:
        if tables and table_id not in tables:
            diagnostics.append({"code": "stale_table_reference", "field": "evidence.table_id", "severity": "error",
                                "message": f"引用表不存在: {table_id}"})
        if page_no is None:
            diagnostics.append({"code": "missing_page", "field": "evidence.page_no", "severity": "warn",
                                "message": "表格记录缺少页码"})
    else:
        diagnostics.append({"code": "missing_table_reference", "field": "evidence.table_id", "severity": "warn",
                            "message": "缺少来源表"})
    if page_no is not None and page_count and (page_no < 1 or page_no > page_count):
        diagnostics.append({"code": "page_out_of_range", "field": "evidence.page_no", "severity": "error",
                            "message": f"页码越界: {page_no} / {page_count}"})
    if channel == "clause":
        quote = ""
        if isinstance(evidence, dict):
            quote = str(evidence.get("quote") or "")
        if not quote:
            diagnostics.append({"code": "missing_clause_quote", "field": "evidence.quote", "severity": "error",
                                "message": "条款记录缺少引文"})
    return diagnostics
