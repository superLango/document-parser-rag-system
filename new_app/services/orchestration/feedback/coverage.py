"""Coverage against the fixed output schema: what is missing and why."""

from __future__ import annotations

from typing import Any

from .measures import normalize
from .schema_contract import (
    CONDITIONAL_FIELDS,
    REQUIRED_FIELDS,
    field_hints,
    property_name,
)

SKIP_VALUES = {"", "-", "--", "—", "–", "/", "…", "...", "~", "无", "不要求"}


def _present(value: Any) -> bool:
    return normalize(value) not in {normalize(item) for item in SKIP_VALUES}


def _source_flags(text: str) -> dict[str, bool]:
    haystack = normalize(text)
    return {
        field: any(normalize(hint) in haystack for hint in field_hints(field))
        for fields in CONDITIONAL_FIELDS.values()
        for field in fields
    }


def _item_value(field: str, prop: dict[str, Any], record: dict[str, Any]) -> Any:
    conditions = record.get("conditions") or {}
    if field == "单位":
        return prop.get("unit")
    if field in {"试验方法", "试验温度"}:
        for key in (field, "温度" if field == "试验温度" else field):
            if key in conditions:
                return conditions[key]
        return record.get(field)
    if field in conditions:
        return conditions[field]
    return record.get(field)


def summarize_coverage(coverage: dict[str, Any]) -> dict[str, Any]:
    """Compact coverage view for retry feedback and verification artifacts."""
    return {
        "complete_rows": coverage.get("complete_rows", 0),
        "required_present": coverage.get("required_present", 0),
        "required_total": coverage.get("required_total", 0),
        "required_rate": coverage.get("required_rate", 0.0),
        "missing": (coverage.get("missing") or [])[:10],
        "conditional_missing": (coverage.get("conditional_missing") or [])[:5],
    }


def compute_coverage(
    records: list[dict[str, Any]],
    *,
    text: str = "",
    heat_treatments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Compute required / conditional field coverage for the fixed schema."""
    source = _source_flags(text)
    missing: list[dict[str, Any]] = []
    conditional_missing: list[dict[str, Any]] = []
    required_total = required_present = complete_rows = items_total = 0
    conditional_expected = conditional_present = 0

    for record in records:
        grade = str(record.get("grade") or "")
        grade_ok = _present(grade) and grade != "~"
        properties = record.get("properties") or {}
        rows = list(properties.items()) if properties else [(None, None)]
        for measure, prop in rows:
            items_total += 1
            required_total += 3
            prop = prop if isinstance(prop, dict) else {}
            name = property_name(str(measure)) if measure else ""
            name_ok = _present(name)
            requirement_ok = _present(prop.get("raw")) or prop.get("value") is not None
            required_present += sum([int(grade_ok), int(name_ok), int(requirement_ok)])
            if not grade_ok:
                missing.append(
                    {
                        "field": "材料牌号",
                        "cause": "row_skipped",
                        "table_id": record.get("table_id"),
                        "row_index": record.get("row_index"),
                        "measure": measure,
                    }
                )
            if not name_ok:
                missing.append(
                    {
                        "field": "项目名称",
                        "cause": "no_mapping",
                        "table_id": record.get("table_id"),
                        "row_index": record.get("row_index"),
                    }
                )
            if not requirement_ok:
                missing.append(
                    {
                        "field": "标准要求",
                        "cause": "value_unparsed",
                        "table_id": record.get("table_id"),
                        "row_index": record.get("row_index"),
                        "measure": measure,
                    }
                )
            if grade_ok and name_ok and requirement_ok:
                complete_rows += 1

            for field in CONDITIONAL_FIELDS["items"]:
                expected = (
                    isinstance(prop.get("value"), (int, float))
                    and not isinstance(prop.get("value"), bool)
                    if field == "单位"
                    else source.get(field, False)
                )
                if not expected:
                    continue
                conditional_expected += 1
                if _present(_item_value(field, prop, record)):
                    conditional_present += 1
                else:
                    conditional_missing.append(
                        {
                            "field": field,
                            "cause": "source_available_but_missing",
                            "table_id": record.get("table_id"),
                            "row_index": record.get("row_index"),
                            "measure": measure,
                        }
                    )

    heat_total = heat_present = 0
    for row in heat_treatments or []:
        for field in REQUIRED_FIELDS["heat_treatment"]:
            heat_total += 1
            if _present(row.get(field)):
                heat_present += 1
            else:
                missing.append({"field": field, "cause": "value_missing", "level": "heat"})

    required_rate = round(required_present / required_total, 4) if required_total else 0.0
    return {
        "schema_version": "1.0.0",
        "items_total": items_total,
        "complete_rows": complete_rows,
        "required_total": required_total,
        "required_present": required_present,
        "required_rate": required_rate,
        "missing": missing[:200],
        "conditional_expected": conditional_expected,
        "conditional_present": conditional_present,
        "conditional_missing": conditional_missing[:200],
        "heat_treatment_total": heat_total,
        "heat_treatment_present": heat_present,
    }
