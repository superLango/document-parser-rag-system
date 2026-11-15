"""Rule-first diagnosis: root cause, action and expected value from evidence.

The diagnosis runs before any repair.  It maps deterministic signals (rule id,
diagnostics, unbound columns, table rows) to a root cause and tries to derive
the expected value from the source table, so the repair agent receives a
concrete target instead of a guess.
"""

from __future__ import annotations

import re
from typing import Any

from .measures import canonical_measure, normalize
from .outline import table_headers
from .resolve import resolve_expected

GRADE_HEADERS = {"牌号", "grade", "钢号", "材料牌号", "designation", "material"}
SKIP_VALUES = {"", "-", "--", "—", "–", "/", "…", "...", "remainder", "balance"}


def _rule_id(context: dict[str, Any]) -> str:
    return str((context.get("task") or {}).get("rule_id") or "")


def _target_table_id(context: dict[str, Any]) -> str:
    return str(((context.get("problem") or {}).get("target") or {}).get("table_id") or "")


def _table(tables: list[dict[str, Any]], table_id: str) -> dict[str, Any]:
    for table in tables:
        if str(table.get("table_id") or "") == table_id:
            return table
    return {}


def _has_diagnostic(diagnostics: list[dict[str, Any]], code: str, table_id: str) -> bool:
    for item in diagnostics:
        if item.get("code") != code:
            continue
        if table_id and str((item.get("detail") or {}).get("table_id") or "") != table_id:
            continue
        return True
    return False


def _base_diagnosis(
    root_cause: str,
    action: str,
    scope: str,
    confidence: float,
    *,
    mechanism: str,
    first_divergence: str = "",
    rule_change: dict[str, Any] | None = None,
    checks: list[str] | None = None,
    needs_model: bool = False,
) -> dict[str, Any]:
    return {
        "root_cause": root_cause,
        "action": action,
        "scope": scope,
        "expected": None,
        "mechanism": mechanism,
        "first_divergence": first_divergence,
        "rule_change": rule_change,
        "evidence": [],
        "checks": checks or [],
        "confidence": confidence,
        "source": "rule",
        "needs_model": needs_model,
    }


def _row_grade(row: list[str], grade_col: int | None) -> str:
    if grade_col is None:
        return str(row[0] if row else "")
    return str(row[grade_col] if grade_col is not None and grade_col < len(row) else "")


def _same_value(left: Any, right: Any) -> bool:
    text_left = normalize(left)
    text_right = normalize(right)
    if text_left == text_right:
        return True
    numbers = re.findall(r"-?\d+(?:\.\d+)?", text_left)
    expected = re.findall(r"-?\d+(?:\.\d+)?", text_right)
    if not numbers or not expected:
        return False
    try:
        return [float(value) for value in numbers] == [
            float(value) for value in expected
        ]
    except ValueError:
        return False


def _first_mismatch(
    records: list[dict[str, Any]],
    table: dict[str, Any],
) -> dict[str, Any] | None:
    """Find the first record property whose raw value differs from the source cell."""
    headers = table_headers(table)
    if not headers:
        return None
    grade_col = next(
        (index for index, header in enumerate(headers) if normalize(header) in GRADE_HEADERS),
        None,
    )
    measure_cols = {
        index: measure
        for index, header in enumerate(headers)
        if (measure := canonical_measure(header))
    }
    rows = table.get("rows") if isinstance(table.get("rows"), list) else []
    for record in records:
        grade = str(record.get("grade") or "")
        if not grade or grade == "~":
            continue
        for row_index, row in enumerate(rows):
            if grade_col is not None and not _same_value(
                _row_grade(row, grade_col), grade
            ):
                continue
            for col_index, measure in measure_cols.items():
                prop = (record.get("properties") or {}).get(measure)
                if not isinstance(prop, dict) or col_index >= len(row):
                    continue
                cell = str(row[col_index] or "").strip()
                if normalize(cell) in SKIP_VALUES:
                    continue
                raw = prop.get("raw")
                if raw is None or _same_value(raw, cell):
                    continue
                return {
                    "record_id": record.get("record_id"),
                    "property": measure,
                    "observed": raw,
                    "expected": cell,
                    "page_no": int(table.get("page_no") or 0),
                    "table_id": str(table.get("table_id") or ""),
                    "row_index": row_index,
                    "col_index": col_index,
                }
    return None


def diagnose(
    *,
    intent: dict[str, Any],
    repair_context: dict[str, Any],
    tables: list[dict[str, Any]],
    records: list[dict[str, Any]],
    diagnostics: list[dict[str, Any]],
    pages: list[dict[str, Any]] | None = None,
    description: str = "",
) -> dict[str, Any]:
    """Rule diagnosis, then attach a deterministic expected value when possible."""
    diagnosis = _rule_diagnosis(
        intent=intent,
        repair_context=repair_context,
        tables=tables,
        records=records,
        diagnostics=diagnostics,
    )
    if not diagnosis.get("expected"):
        problem = repair_context.get("problem") or {}
        resolved = resolve_expected(
            pages or [],
            description=description or str(problem.get("description") or ""),
            properties=list(intent.get("properties") or []),
        )
        if resolved:
            diagnosis["expected"] = resolved["expected"]
            diagnosis["expected_source"] = resolved["source"]
            diagnosis["expected_evidence"] = {
                key: resolved.get(key)
                for key in (
                    "page_no",
                    "quote",
                    "standard_no",
                    "standard_name",
                    "keyword",
                )
            }
            evidence = list(diagnosis.get("evidence") or [])
            evidence.append(
                {
                    "page_no": resolved.get("page_no"),
                    "quote": resolved.get("quote") or resolved.get("expected"),
                    "source": resolved.get("source"),
                }
            )
            diagnosis["evidence"] = evidence
    return diagnosis


def _rule_diagnosis(
    *,
    intent: dict[str, Any],
    repair_context: dict[str, Any],
    tables: list[dict[str, Any]],
    records: list[dict[str, Any]],
    diagnostics: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return a deterministic diagnosis for the current feedback task."""
    rule_id = _rule_id(repair_context)
    table_id = _target_table_id(repair_context)
    scope = str(intent.get("scope") or "document")
    table = _table(tables, table_id)
    rows = table.get("rows") if isinstance(table.get("rows"), list) else []
    unbound = list(((repair_context.get("recipe") or {}).get("unbound_columns")) or [])
    admissible = list(
        (((repair_context.get("constraints") or {}).get("admissible") or {}).get("columns"))
        or []
    )
    checks = [
        f"rule_id={rule_id or 'none'}",
        f"table_id={table_id or 'none'}",
        f"rows={len(rows)}",
        f"records={len(records)}",
        f"unbound_columns={unbound}",
        f"admissible={admissible}",
    ]

    if rule_id == "DOC-NO-TABLES" or not tables:
        return _base_diagnosis(
            "ocr_error",
            "report_only",
            "document",
            0.8,
            mechanism="整篇未检测到表格，属于版面/OCR 层问题，配方补丁无法修复",
            first_divergence="OCR 输出 tables=0",
            checks=checks,
        )

    if rule_id == "DOC-UNBOUND-COLUMNS":
        if admissible:
            return _base_diagnosis(
                "recipe_binding",
                "rule_fix",
                scope,
                0.85,
                mechanism="表头列存在但配方未绑定对应 measure",
                first_divergence="列 " + "/".join(unbound) + " 未进入 bindings.measures",
                rule_change={
                    "rule_id": "bindings.measures",
                    "before": "未绑定 " + "/".join(unbound),
                    "after": "按表头把 " + "/".join(admissible) + " 绑定到对应列",
                },
                checks=checks,
            )
        return _base_diagnosis(
            "table_structure",
            "table_repair",
            scope,
            0.8,
            mechanism="表头没有可承载这些测量值的列，属于表结构或 OCR 问题",
            first_divergence="unbound_columns 与可映射列无交集",
            rule_change={
                "rule_id": "table_repair",
                "before": "表头无法承载目标 measure",
                "after": "修复表头/合并单元格后重新解析",
            },
            checks=checks,
        )

    if rule_id in {"DOC-NO-RECORDS", "DOC-LOW-COVERAGE"}:
        if rows:
            return _base_diagnosis(
                "table_structure",
                "table_repair",
                scope,
                0.8,
                mechanism="表内有数据行但未产出记录，通常是表头或行键识别失败",
                first_divergence=f"表 {table_id} 有 {len(rows)} 行，产出 0 条记录",
                rule_change={
                    "rule_id": "table_repair",
                    "before": "表头/行键未识别",
                    "after": "按表头行与行键修复后重新解析",
                },
                checks=checks,
            )
        return _base_diagnosis(
            "ocr_error",
            "reparse",
            scope,
            0.6,
            mechanism="目标表没有可用数据行，需先确认 OCR 是否正常",
            first_divergence="目标表 rows=0",
            checks=checks,
            needs_model=True,
        )

    if rule_id == "DOC-DUP-KEYS":
        return _base_diagnosis(
            "extraction_rule",
            "rule_fix",
            scope,
            0.8,
            mechanism="同一牌号与条件下重复产出记录，通常是条件列未进入 condition_key",
            first_divergence="重复主键计数超过阈值",
            rule_change={
                "rule_id": "bindings.conditions",
                "before": "条件列未进入 condition_key",
                "after": "把温度/方向/状态等条件列加入 bindings.conditions",
            },
            checks=checks,
        )

    if rule_id == "DOC-UNIT-MISSING":
        return _base_diagnosis(
            "recipe_binding",
            "rule_fix",
            scope,
            0.75,
            mechanism="measure 已绑定但单位缺失",
            first_divergence="数值字段 unit 为空",
            rule_change={
                "rule_id": "bindings.measures.unit",
                "before": "measure 未配置 unit",
                "after": "按表头单位为 measure 配置 unit",
            },
            checks=checks,
        )

    category = str(intent.get("category") or "")
    field = str(intent.get("field") or "")
    if field == "项目名称" and category == "missing_value":
        scoped_records = [
            item
            for item in records
            if not table_id or str(item.get("table_id") or "") == table_id
        ]
        if table_id and rows and not scoped_records:
            return _base_diagnosis(
                "table_structure",
                "table_repair",
                scope,
                0.75,
                mechanism="表内有数据行，但该项目没有产出任何记录",
                first_divergence=f"表 {table_id} 有 {len(rows)} 行，记录数 0",
                rule_change={
                    "rule_id": "table_repair",
                    "before": "表头或行键未识别，整表未产出记录",
                    "after": "修复表头/行键后重新解析该表",
                },
                checks=checks,
            )
        if admissible:
            return _base_diagnosis(
                "recipe_binding",
                "rule_fix",
                scope,
                0.8,
                mechanism="项目缺失：表头存在可绑定列，但配方未绑定对应测量项",
                first_divergence="可绑定列 " + "/".join(admissible),
                rule_change={
                    "rule_id": "bindings.measures",
                    "before": "项目对应列未绑定",
                    "after": "按表头补齐 bindings.measures",
                },
                checks=checks,
            )
        if _has_diagnostic(diagnostics, "MEASURE_COLUMN_MISSING", table_id):
            return _base_diagnosis(
                "recipe_binding",
                "rule_fix",
                scope,
                0.7,
                mechanism="项目缺失：目标表存在未绑定的测量列",
                first_divergence="MEASURE_COLUMN_MISSING 命中目标表",
                rule_change={
                    "rule_id": "bindings.measures",
                    "before": "部分测量列未绑定",
                    "after": "按表头补齐 bindings.measures",
                },
                checks=checks,
            )

    mismatch = _first_mismatch(records, table)
    if mismatch is not None:
        diagnosis = _base_diagnosis(
            "value_parsing",
            "rule_fix",
            scope,
            0.85,
            mechanism="记录值与原文单元格不一致，属于取值或列对齐问题",
            first_divergence=(
                f"记录 {mismatch['record_id']}.{mismatch['property']} "
                f"raw={mismatch['observed']}，原文单元格={mismatch['expected']}"
            ),
            rule_change={
                "rule_id": "value_parsing",
                "before": f"{mismatch['property']} 取值与原文不一致",
                "after": "按表头列对齐与比较符规则重新取值",
            },
            checks=checks,
            needs_model=False,
        )
        diagnosis["expected"] = mismatch["expected"]
        diagnosis["evidence"] = [
            {
                "page_no": mismatch["page_no"],
                "table_id": mismatch["table_id"],
                "row_index": mismatch["row_index"],
                "col_index": mismatch["col_index"],
                "quote": mismatch["expected"],
            }
        ]
        return diagnosis

    if category in {"wrong_value", "wrong_requirement", "wrong_unit"}:
        return _base_diagnosis(
            "value_parsing",
            "rule_fix",
            scope,
            0.5,
            mechanism="用户指出值/要求问题，但未能在目标表定位到差异单元格",
            first_divergence="未找到记录与原文单元格的差异",
            checks=checks,
            needs_model=True,
        )

    if _has_diagnostic(diagnostics, "MEASURE_COLUMN_MISSING", table_id):
        return _base_diagnosis(
            "recipe_binding",
            "rule_fix",
            scope,
            0.7,
            mechanism="存在未绑定的测量列，需要补充配方绑定",
            first_divergence="MEASURE_COLUMN_MISSING 命中目标表",
            rule_change={
                "rule_id": "bindings.measures",
                "before": "部分测量列未绑定",
                "after": "按表头补齐 bindings.measures",
            },
            checks=checks,
        )

    return _base_diagnosis(
        "unknown",
        "report_only",
        scope,
        0.3,
        mechanism="规则无法归因，需要模型结合证据进一步判断",
        checks=checks,
        needs_model=True,
    )


def needs_model_attribution(diagnosis: dict[str, Any]) -> bool:
    """Only rule diagnoses flagged with needs_model go to the model."""
    return bool(diagnosis.get("needs_model")) and str(
        diagnosis.get("source") or "rule"
    ) == "rule"


def merge_model_diagnosis(
    rule: dict[str, Any],
    model: dict[str, Any],
    *,
    table_id: str = "",
) -> dict[str, Any]:
    """Keep the rule skeleton, override attribution fields with validated model output."""
    merged = dict(rule)
    if not model.get("model_used"):
        merged["model_attribution"] = {
            "applied": False,
            "reason": "模型归因不可用或字段不合法",
        }
        return merged
    rule_root_cause = rule.get("root_cause")
    for key in (
        "root_cause",
        "action",
        "scope",
        "mechanism",
        "first_divergence",
        "rule_change",
    ):
        value = model.get(key)
        if value:
            merged[key] = value
    if model.get("expected"):
        merged["expected"] = model["expected"]
    if model.get("confidence"):
        merged["confidence"] = model["confidence"]
    evidence = [
        item
        for item in model.get("evidence") or []
        if isinstance(item, dict)
        and (not table_id or str(item.get("table_id") or "") == table_id)
    ]
    if evidence:
        merged["evidence"] = evidence
    merged["source"] = "model"
    merged["model_attribution"] = {
        "applied": True,
        "rule_root_cause": rule_root_cause,
    }
    return merged
