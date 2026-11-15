"""Run-to-run diff used by L1 reparse verification."""

from __future__ import annotations

from typing import Any


def _field_value(record: dict[str, Any], measure: str) -> dict[str, Any] | None:
    properties = record.get("properties") or {}
    value = properties.get(measure)
    if not isinstance(value, dict):
        return None
    return {
        "value": value.get("value"),
        "unit": value.get("unit"),
        "operator": value.get("operator"),
    }


def _diagnostic_key(item: dict[str, Any]) -> tuple[str, str, str, str]:
    detail = item.get("detail") or {}
    return (
        str(item.get("code") or ""),
        str(detail.get("table_id") or ""),
        str(detail.get("block_id") or ""),
        str(detail.get("page_no") or ""),
    )


def diff_runs(
    before_records: list[dict[str, Any]],
    after_records: list[dict[str, Any]],
    before_diagnostics: list[dict[str, Any]] | None = None,
    after_diagnostics: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    before_map = {
        str(item.get("record_id")): item
        for item in before_records
        if isinstance(item, dict) and item.get("record_id")
    }
    after_map = {
        str(item.get("record_id")): item
        for item in after_records
        if isinstance(item, dict) and item.get("record_id")
    }
    added_ids = sorted(set(after_map) - set(before_map))
    removed_ids = sorted(set(before_map) - set(after_map))
    fields_changed: list[dict[str, Any]] = []
    changed_records: set[str] = set()
    for record_id in sorted(set(before_map) & set(after_map)):
        before = before_map[record_id]
        after = after_map[record_id]
        before_props = before.get("properties") or {}
        after_props = after.get("properties") or {}
        for measure in sorted(set(before_props) | set(after_props)):
            before_value = _field_value(before, measure)
            after_value = _field_value(after, measure)
            if before_value == after_value:
                continue
            changed_records.add(record_id)
            fields_changed.append(
                {
                    "record_id": record_id,
                    "grade": after.get("grade"),
                    "table_id": after.get("table_id"),
                    "measure": measure,
                    "before": before_value,
                    "after": after_value,
                }
            )

    before_diags = before_diagnostics or []
    after_diags = after_diagnostics or []
    before_keys = {_diagnostic_key(item) for item in before_diags}
    after_keys = {_diagnostic_key(item) for item in after_diags}
    tables_before = sorted(
        {str(item.get("table_id")) for item in before_records if item.get("table_id")}
    )
    tables_after = sorted(
        {str(item.get("table_id")) for item in after_records if item.get("table_id")}
    )
    return {
        "summary": {
            "records_before": len(before_map),
            "records_after": len(after_map),
            "records_added": len(added_ids),
            "records_removed": len(removed_ids),
            "records_changed": len(changed_records),
            "fields_changed": len(fields_changed),
            "diagnostics_before": len(before_diags),
            "diagnostics_after": len(after_diags),
            "diagnostics_added": len(after_keys - before_keys),
            "diagnostics_removed": len(before_keys - after_keys),
            "tables_before": len(tables_before),
            "tables_after": len(tables_after),
            "tables_added": len(set(tables_after) - set(tables_before)),
            "tables_removed": len(set(tables_before) - set(tables_after)),
        },
        "records_added": added_ids[:50],
        "records_removed": removed_ids[:50],
        "fields": fields_changed[:200],
        "diagnostics_added": sorted(after_keys - before_keys)[:50],
        "diagnostics_removed": sorted(before_keys - after_keys)[:50],
        "tables": {
            "before": tables_before,
            "after": tables_after,
        },
    }


async def load_run_records(run_id: str) -> list[dict[str, Any]]:
    from .artifacts import artifact_json

    payload = await artifact_json(run_id, "records") or {}
    return [
        item for item in (payload.get("records") or []) if isinstance(item, dict)
    ]


async def load_run_diagnostics(run_id: str) -> list[dict[str, Any]]:
    from .artifacts import artifact_json

    payload = await artifact_json(run_id, "diagnostics") or {}
    return [
        item for item in (payload.get("diagnostics") or []) if isinstance(item, dict)
    ]


async def diff_run_ids(
    before_run_id: str, after_run_id: str
) -> dict[str, Any]:
    before_records = await load_run_records(before_run_id)
    after_records = await load_run_records(after_run_id)
    before_diagnostics = await load_run_diagnostics(before_run_id)
    after_diagnostics = await load_run_diagnostics(after_run_id)
    return diff_runs(
        before_records,
        after_records,
        before_diagnostics,
        after_diagnostics,
    )
