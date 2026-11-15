"""RepairContext builder: the bounded work order handed to the repair agent."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import Any

from .coverage import compute_coverage
from .measures import canonical_measure
from .schema_contract import schema_summary

CONSTRAINTS_BY_RULE: dict[str, list[str]] = {
    "DOC-UNBOUND-COLUMNS": ["recipe.binding_override", "column_alias.add", "table_repair.add"],
    "DOC-DUP-KEYS": ["recipe.binding_override", "table_repair.add"],
    "DOC-NO-RECORDS": ["table_repair.add", "recipe.binding_override"],
    "DOC-LOW-COVERAGE": ["table_repair.add", "recipe.binding_override"],
    "DOC-UNIT-MISSING": ["recipe.binding_override", "unit_normalize.add"],
    "DOC-NO-TABLES": [],
}
# 条件绑定类规则需要一次补齐多列（实测 17 ops），其余规则保持最小补丁。
MAX_OPS_BY_RULE: dict[str, int] = {"DOC-DUP-KEYS": 20}
DEFAULT_MAX_OPS = 5


def _table_headers(table: dict[str, Any], diagnostics: list[dict[str, Any]]) -> list[str]:
    headers: list[str] = []
    paths = table.get("header_paths") or []
    if paths and isinstance(paths[0], list):
        for row in paths:
            headers.extend(str(cell) for cell in row if str(cell).strip())
    elif isinstance(paths, list):
        headers.extend(str(cell) for cell in paths if str(cell).strip())
    headers.extend(str(cell) for cell in (table.get("headers") or []))
    if not headers:
        table_id = str(table.get("table_id") or "")
        for item in diagnostics:
            detail = item.get("detail") or {}
            if item.get("code") == "MEASURE_COLUMN_MISSING" and str(
                detail.get("table_id") or ""
            ) == table_id:
                headers = [str(cell) for cell in detail.get("headers") or []]
                break
    return list(dict.fromkeys(header for header in headers if header))


def _diagnosed_measures(
    diagnostics: list[dict[str, Any]], table_id: str
) -> list[str]:
    """Measures the parser reported missing on the target table."""
    measures = {
        str((item.get("detail") or {}).get("measure") or "")
        for item in diagnostics
        if item.get("code") == "MEASURE_COLUMN_MISSING"
        and (
            not table_id
            or str((item.get("detail") or {}).get("table_id") or "") == table_id
        )
    }
    return sorted(measure for measure in measures if measure)


def _header_merges(table: dict[str, Any], limit: int = 40) -> list[dict[str, Any]]:
    """Only header-area merges matter for structure repair and stay small."""
    merges = table.get("merges") if isinstance(table.get("merges"), list) else []
    header = [
        item
        for item in merges
        if isinstance(item, dict)
        and (item.get("is_header") or int(item.get("row") or 0) < 2)
    ]
    return header[:limit]


def _rule_id(feedback: dict[str, Any]) -> str:
    target = feedback.get("target") or {}
    return str(target.get("rule_id") or feedback.get("rule_id") or "")


def _row_count(table: dict[str, Any]) -> int:
    rows = table.get("rows")
    if isinstance(rows, list):
        return len(rows)
    try:
        return int(rows or 0)
    except (TypeError, ValueError):
        return 0


def _record_count(table: dict[str, Any], record_counts: Counter[str]) -> int:
    table_id = str(table.get("table_id") or "")
    value = table.get("records")
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return record_counts.get(table_id, 0)


def _choose_uncovered(
    tables: list[dict[str, Any]],
    record_counts: Counter[str],
    preferred: list[str] | None = None,
) -> str:
    """Pick the table that most clearly failed: has rows but produced no records."""
    by_id = {str(table.get("table_id") or ""): table for table in tables}
    pool = [by_id[table_id] for table_id in preferred or [] if table_id in by_id]
    if not pool:
        pool = tables
    uncovered = [
        table
        for table in pool
        if _row_count(table) > 0 and _record_count(table, record_counts) == 0
    ]
    if uncovered:
        uncovered.sort(key=lambda table: -_row_count(table))
        return str(uncovered[0].get("table_id") or "")
    return ""


def _choose_target(
    feedback: dict[str, Any],
    intent: dict[str, Any] | None,
    tables: list[dict[str, Any]],
    diagnostics: list[dict[str, Any]],
    records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    target = feedback.get("target") or {}
    record_counts: Counter[str] = Counter(
        str(record.get("table_id") or "") for record in records or []
    )
    table_id = str(target.get("table_id") or "")
    if not table_id and intent:
        candidates = intent.get("candidate_targets") or []
        if candidates:
            table_id = str(candidates[0].get("table_id") or "")
    if not table_id and str(target.get("rule_id") or "") in {
        "DOC-NO-RECORDS",
        "DOC-LOW-COVERAGE",
    }:
        table_id = _choose_uncovered(
            tables,
            record_counts,
            [str(item) for item in target.get("table_ids") or []],
        )
    if not table_id:
        scored: list[tuple[int, dict[str, Any]]] = []
        for table in tables:
            own = [
                item
                for item in diagnostics
                if str((item.get("detail") or {}).get("table_id") or "")
                == str(table.get("table_id") or "")
                and item.get("severity") in {"warning", "error"}
            ]
            scored.append((len(own), table))
        scored.sort(key=lambda item: -item[0])
        if scored and scored[0][0] > 0:
            table_id = str(scored[0][1].get("table_id") or "")
    for table in tables:
        if str(table.get("table_id") or "") == table_id:
            return table
    return {}


def choose_target_table(
    *,
    feedback: dict[str, Any],
    tables: list[dict[str, Any]],
    diagnostics: list[dict[str, Any]],
    records: list[dict[str, Any]] | None = None,
    intent: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Public helper so the orchestrator can resolve the same target table."""
    return _choose_target(feedback, intent, tables, diagnostics, records)


def _records_for(records: list[dict[str, Any]], table_id: str) -> list[dict[str, Any]]:
    if not table_id:
        return records
    return [
        record
        for record in records
        if str(record.get("table_id") or "") == table_id
    ]


def _diagnostic_count(
    diagnostics: list[dict[str, Any]], code: str, table_id: str
) -> int:
    count = 0
    for item in diagnostics:
        if item.get("code") != code:
            continue
        if table_id and str((item.get("detail") or {}).get("table_id") or "") != table_id:
            continue
        count += 1
    return count


def _duplicate_count(records: list[dict[str, Any]]) -> int:
    counts: Counter[tuple[str, str]] = Counter()
    for record in records:
        grade = str(record.get("grade") or "").strip()
        if not grade or grade == "~":
            continue
        for name in record.get("properties") or {}:
            counts[(grade, str(name))] += 1
    return sum(count - 1 for count in counts.values() if count > 1)


def _missing_unit_ratio(records: list[dict[str, Any]]) -> float:
    numeric = missing = 0
    for record in records:
        for value in (record.get("properties") or {}).values():
            if not isinstance(value, dict):
                continue
            number = value.get("value")
            if isinstance(number, bool) or not isinstance(number, (int, float)):
                continue
            numeric += 1
            if not value.get("unit"):
                missing += 1
    return round(missing / numeric, 4) if numeric else 0.0


def _acceptance(
    rule_id: str,
    table_id: str,
    records: list[dict[str, Any]],
    diagnostics: list[dict[str, Any]],
    coverage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    coverage = coverage or {}
    if rule_id == "DOC-UNBOUND-COLUMNS":
        current = int(coverage.get("required_present") or 0)
        return {
            "metric": "required_items",
            "current": current,
            "target": current + 1,
        }
    if rule_id in {"DOC-NO-RECORDS", "DOC-LOW-COVERAGE"}:
        current = int(coverage.get("complete_rows") or 0)
        return {
            "metric": "complete_items",
            "current": current,
            "target": current + 1,
        }
    if rule_id == "DOC-DUP-KEYS":
        current = _duplicate_count(records)
        return {"metric": "duplicate_keys", "current": current, "target": max(0, current - 1)}
    if rule_id == "DOC-UNIT-MISSING":
        current = _missing_unit_ratio(records)
        return {"metric": "missing_unit_ratio", "current": current, "target": 0.0}
    if rule_id == "DOC-NO-TABLES":
        return {"metric": "tables", "current": 0, "target": 1}
    return {"metric": "records", "current": len(records), "target": len(records) + 1}


def merge_tables(
    tables: list[dict[str, Any]], ocr_tables: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Merge sandbox table summaries with OCR table details (headers/caption)."""
    by_id = {str(item.get("table_id") or ""): item for item in ocr_tables}
    list_fields = {"rows", "header_paths", "headers", "merges", "footnotes", "blocks"}
    merged: list[dict[str, Any]] = []
    for table in tables:
        table_id = str(table.get("table_id") or "")
        detail = dict(by_id.get(table_id) or {})
        for key, value in table.items():
            if key in list_fields and not isinstance(value, list):
                # 沙箱摘要里的 rows 是数量（int），不能覆盖 OCR 的行数组。
                continue
            if value not in (None, "", [], {}):
                detail[key] = value
        merged.append(detail)
    seen = {str(item.get("table_id") or "") for item in tables}
    for table_id, detail in by_id.items():
        if table_id not in seen:
            merged.append(dict(detail))
    return merged


def build_repair_context(
    *,
    feedback: dict[str, Any],
    tables: list[dict[str, Any]],
    records: list[dict[str, Any]],
    diagnostics: list[dict[str, Any]],
    recipe: dict[str, Any],
    intent: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the bounded RepairContext handed to the repair agent."""
    rule_id = _rule_id(feedback)
    table = _choose_target(feedback, intent, tables, diagnostics, records)
    table_id = str(table.get("table_id") or "")
    scoped_records = _records_for(records, table_id)
    headers = _table_headers(table, diagnostics)

    bindings = (recipe or {}).get("bindings") or {}
    bound = {
        canonical
        for name in (bindings.get("measures") or {})
        if (canonical := canonical_measure(name))
    }
    unbound = sorted(
        {
            canonical
            for header in headers
            if (canonical := canonical_measure(header)) and canonical not in bound
        }
    )
    # 解析器报出的缺失 measure（如 Ag/As）同样是可绑定的候选列。
    unbound = sorted(
        set(unbound)
        | {
            measure
            for measure in _diagnosed_measures(diagnostics, table_id)
            if measure not in bound
        }
    )

    table_diagnostics = [
        item
        for item in diagnostics
        if not table_id
        or str((item.get("detail") or {}).get("table_id") or "") == table_id
    ][:20]

    coverage = compute_coverage(
        scoped_records,
        text=" ".join([str(table.get("caption") or ""), *headers]),
    )
    acceptance = _acceptance(
        rule_id, table_id, scoped_records, diagnostics, coverage
    )
    allowed_operators = CONSTRAINTS_BY_RULE.get(
        rule_id, ["table_repair.add", "recipe.binding_override"]
    )
    allowed_levels = ["engine"] if rule_id == "DOC-NO-TABLES" else ["L1", "L2"]

    context = {
        "task": {
            "feedback_id": str(feedback.get("feedback_id") or feedback.get("id") or ""),
            "source": str(feedback.get("reporter") or "operator"),
            "rule_id": rule_id,
            "verdict": str((intent or {}).get("verdict") or "ambiguous"),
            "priority": "P1" if rule_id else "P0",
            "goal": _goal(rule_id, table_id, acceptance),
            "acceptance": acceptance,
        },
        "problem": {
            "description": str(feedback.get("description") or ""),
            "target": {
                "run_id": str(feedback.get("run_id") or ""),
                "table_id": table_id,
                "record_id": str((feedback.get("target") or {}).get("record_id") or ""),
                "property": (intent or {}).get("properties") or [],
                "page_no": int(table.get("page_no") or 0),
            },
            "observed": {
                "records": len(scoped_records),
                "required_rate": coverage["required_rate"],
                "complete_rows": coverage["complete_rows"],
                "diagnostics": sorted({str(item.get("code") or "") for item in table_diagnostics}),
            },
            "expected": None,
        },
        "schema": schema_summary(),
        "coverage": coverage,
        "evidence": {
            "source_quote": str(feedback.get("source_quote") or ""),
            "page_text": "",
            "table": {
                "table_id": table_id,
                "page_no": int(table.get("page_no") or 0),
                "caption": table.get("caption"),
                "profile": table.get("profile"),
                "orientation": table.get("orientation"),
                "header_paths": table.get("header_paths") or [],
                "headers": headers,
                "sample_rows": (
                    table.get("rows") if isinstance(table.get("rows"), list) else []
                )[:3],
                "merges": _header_merges(table),
                "merge_count": len(table.get("merges") or []),
                "footnotes": (table.get("footnotes") or [])[:20],
            },
            "records": [
                {
                    "record_id": record.get("record_id"),
                    "grade": record.get("grade"),
                    "condition_key": record.get("condition_key"),
                    "properties": {
                        name: {
                            "raw": (value or {}).get("raw"),
                            "unit": (value or {}).get("unit"),
                        }
                        for name, value in (record.get("properties") or {}).items()
                    },
                }
                for record in scoped_records[:5]
            ],
            "diagnostics": table_diagnostics,
        },
        "recipe": {
            "recipe_id": str((recipe or {}).get("recipe_id") or ""),
            "version": str((recipe or {}).get("version") or ""),
            "profile": str((recipe or {}).get("profile") or ""),
            "bindings": bindings,
            "rules": (recipe or {}).get("rules") or {},
            "bound_columns": sorted(bound),
            "unbound_columns": unbound,
        },
        "constraints": {
            "allowed_levels": allowed_levels,
            "allowed_operators": allowed_operators,
            "admissible": {
                "columns": unbound,
                "measures": unbound,
                "table_repair": "table_repair.add" in allowed_operators,
            },
            "forbidden": [
                "修改目标表之外的其它表",
                "编造原文没有的数值",
                "修改生产配置",
                "修改代码",
            ],
            "output_schema": "RepairProposal/v2",
            "max_ops": MAX_OPS_BY_RULE.get(rule_id, DEFAULT_MAX_OPS),
        },
        "history": {
            "previous_attempts": [],
            "similar_cases": [],
        },
        "intent": intent or {},
    }
    payload = json.dumps(context, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    context["context_hash"] = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return context


def _goal(rule_id: str, table_id: str, acceptance: dict[str, Any]) -> str:
    scope = f"表 {table_id}" if table_id else "文档"
    metric = acceptance.get("metric")
    if metric == "MEASURE_COLUMN_MISSING":
        return f"让{scope}的未绑定测量列完成绑定，MEASURE_COLUMN_MISSING 计数下降"
    if metric == "records":
        current = acceptance.get("current")
        target = acceptance.get("target")
        return f"让{scope}的产出记录数从 {current} 增加到至少 {target}"
    if metric == "duplicate_keys":
        return f"让{scope}的重复主键数下降"
    if metric == "missing_unit_ratio":
        return f"让{scope}缺失单位的数值比例下降"
    return f"修复{scope}的抽取问题"
