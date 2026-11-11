"""Built-in read-only tools for Router/Review harness tasks."""

from __future__ import annotations

from typing import Any

from .registry import Tool, ToolRegistry


def _tables(context: dict[str, Any]) -> dict[str, dict[str, Any]]:
    tables = context.get("tables") or []
    return {str(item.get("table_id")): item for item in tables if isinstance(item, dict)}


def _records(context: dict[str, Any]) -> list[dict[str, Any]]:
    records = context.get("records") or []
    return [item for item in records if isinstance(item, dict)]


async def get_table_summary(arguments: dict[str, Any], context: dict[str, Any]) -> Any:
    table = _tables(context).get(str(arguments.get("table_id") or ""))
    if table is None:
        return {"error": "table_not_found"}
    return {
        "table_id": table.get("table_id"),
        "page_no": table.get("page_no"),
        "caption": table.get("caption"),
        "profile": table.get("profile"),
        "orientation": table.get("orientation"),
        "n_rows": table.get("n_rows"),
        "n_cols": table.get("n_cols"),
        "header_paths": table.get("header_paths") or [],
        "units": table.get("units") or [],
        "sample_rows": _sample_rows(table.get("rows")),
    }


def _sample_rows(rows: Any) -> list[Any]:
    return rows[:5] if isinstance(rows, list) else []


async def get_records(arguments: dict[str, Any], context: dict[str, Any]) -> Any:
    table_id = str(arguments.get("table_id") or "")
    limit = max(1, min(int(arguments.get("limit") or 20), 100))
    records = [
        item for item in _records(context) if not table_id or item.get("table_id") == table_id
    ]
    return {"count": len(records), "records": records[:limit]}


async def get_evidence(arguments: dict[str, Any], context: dict[str, Any]) -> Any:
    record_id = str(arguments.get("record_id") or "")
    evidence = [
        item
        for item in (context.get("evidence") or [])
        if not record_id or item.get("evidence_id") == record_id
    ]
    return {"count": len(evidence), "evidence": evidence[:20]}


async def get_recipe_catalog(_: dict[str, Any], context: dict[str, Any]) -> Any:
    return {"catalog": context.get("catalog") or []}


async def validate_record(arguments: dict[str, Any], context: dict[str, Any]) -> Any:
    record_id = str(arguments.get("record_id") or "")
    record = next(
        (item for item in _records(context) if item.get("record_id") == record_id),
        None,
    )
    if record is None:
        return {"error": "record_not_found"}
    evidence_ids = {item.get("evidence_id") for item in (context.get("evidence") or [])}
    refs = record.get("evidence_refs") or []
    properties = record.get("properties") or {}
    return {
        "record_id": record_id,
        "grade_present": bool(record.get("grade")),
        "properties": len(properties),
        "evidence_refs": refs,
        "evidence_found": [ref in evidence_ids for ref in refs],
        "missing_unit": [
            name for name, value in properties.items() if not (value or {}).get("unit")
        ],
    }


def build_default_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        Tool(
            name="get_table_summary",
            description="Return table metadata, header paths, units and five sample rows.",
            input_schema={
                "type": "object",
                "required": ["table_id"],
                "properties": {"table_id": {"type": "string"}},
            },
            handler=get_table_summary,
        )
    )
    registry.register(
        Tool(
            name="get_records",
            description="Return extracted records, optionally filtered by table_id.",
            input_schema={
                "type": "object",
                "properties": {
                    "table_id": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                },
            },
            handler=get_records,
        )
    )
    registry.register(
        Tool(
            name="get_evidence",
            description="Return evidence rows for a record id.",
            input_schema={
                "type": "object",
                "required": ["record_id"],
                "properties": {"record_id": {"type": "string"}},
            },
            handler=get_evidence,
        )
    )
    registry.register(
        Tool(
            name="get_recipe_catalog",
            description="Return the available recipe catalog (read-only).",
            input_schema={"type": "object", "properties": {}},
            handler=get_recipe_catalog,
        )
    )
    registry.register(
        Tool(
            name="validate_record",
            description="Run deterministic record checks and return their observations.",
            input_schema={
                "type": "object",
                "required": ["record_id"],
                "properties": {"record_id": {"type": "string"}},
            },
            handler=validate_record,
        )
    )
    return registry
