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


async def get_table(arguments: dict[str, Any], context: dict[str, Any]) -> Any:
    """Return a bounded row range of one table (paged, read-only)."""
    table_id = str(arguments.get("table_id") or "")
    table = _tables(context).get(table_id)
    if table is None:
        return {
            "error": "table_not_found",
            "available_tables": sorted(_tables(context))[:20],
        }
    rows = table.get("rows") if isinstance(table.get("rows"), list) else []
    offset = max(0, int(arguments.get("offset") or 0))
    limit = max(1, min(int(arguments.get("limit") or 10), 30))
    headers: list[str] = []
    paths = table.get("header_paths") or []
    if paths and isinstance(paths[0], list):
        for path in paths:
            headers.extend(str(cell) for cell in path if str(cell).strip())
    elif isinstance(paths, list):
        headers.extend(str(cell) for cell in paths if str(cell).strip())
    headers.extend(str(cell) for cell in (table.get("headers") or []))
    return {
        "table_id": table_id,
        "page_no": table.get("page_no"),
        "caption": table.get("caption"),
        "profile": table.get("profile"),
        "orientation": table.get("orientation"),
        "n_rows": len(rows),
        "headers": list(dict.fromkeys(headers))[:80],
        "offset": offset,
        "rows": rows[offset : offset + limit],
        "has_more": offset + limit < len(rows),
    }


async def get_records(arguments: dict[str, Any], context: dict[str, Any]) -> Any:
    table_id = str(arguments.get("table_id") or "")
    record_id = str(arguments.get("record_id") or "")
    offset = max(0, int(arguments.get("offset") or 0))
    limit = max(1, min(int(arguments.get("limit") or 20), 50))
    records = [
        item
        for item in _records(context)
        if (not table_id or item.get("table_id") == table_id)
        and (not record_id or item.get("record_id") == record_id)
    ]
    compact = [
        {
            "record_id": item.get("record_id"),
            "table_id": item.get("table_id"),
            "grade": item.get("grade"),
            "condition_key": item.get("condition_key"),
            "properties": {
                name: {
                    "raw": (value or {}).get("raw"),
                    "unit": (value or {}).get("unit"),
                }
                for name, value in (item.get("properties") or {}).items()
            },
        }
        for item in records[offset : offset + limit]
    ]
    return {
        "count": len(records),
        "offset": offset,
        "records": compact,
        "has_more": offset + limit < len(records),
    }


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


async def escalate_to_human(arguments: dict[str, Any], context: dict[str, Any]) -> Any:
    """声明需要人工介入；由上层将其转换为 needs_human 队列项。"""
    reason = str(arguments.get("reason") or "").strip()
    if not reason:
        return {"error": "reason_required"}
    table_ids = arguments.get("table_ids") or context.get("needs_human_tables") or []
    return {
        "status": "human_required",
        "reason": reason[:500],
        "table_ids": [str(item) for item in table_ids][:50],
    }


async def _post_json(url: str, payload: dict[str, Any]) -> Any:
    import httpx

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        return response.json()


async def run_sandbox(_: dict[str, Any], context: dict[str, Any]) -> Any:
    """按上下文中的 sandbox_request 触发一次沙箱执行。"""
    from ..config import settings

    request = context.get("sandbox_request")
    if not isinstance(request, dict):
        return {"error": "sandbox_request_missing"}
    if not settings.sandbox_url:
        return {"error": "sandbox_not_configured"}
    result = await _post_json(
        f"{settings.sandbox_url.rstrip('/')}/internal/sandbox:execute", request
    )
    if isinstance(result, dict):
        return {
            "status": result.get("status"),
            "records": len(result.get("records") or []),
            "warnings": (result.get("warnings") or [])[:10],
        }
    return result


async def request_review(_: dict[str, Any], context: dict[str, Any]) -> Any:
    """按上下文中的 review_request 触发一次审核。"""
    from ..config import settings

    request = context.get("review_request")
    if not isinstance(request, dict):
        return {"error": "review_request_missing"}
    if not settings.review_url:
        return {"error": "review_not_configured"}
    result = await _post_json(
        f"{settings.review_url.rstrip('/')}/internal/review:run", request
    )
    if isinstance(result, dict):
        return {
            "decision": result.get("decision"),
            "findings": len(result.get("findings") or []),
            "score": result.get("score"),
        }
    return result


async def _library_get(path: str, params: dict[str, Any]) -> Any:
    import os

    import httpx

    from ..config import settings

    base = settings.orchestration_url or os.getenv("ORCHESTRATION_URL", "")
    if not base:
        return {"error": "orchestration_not_configured"}
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(
                f"{base.rstrip('/')}{path}", params=params
            )
    except Exception as exc:  # noqa: BLE001 - tool observations are returned
        return {"error": f"library_unavailable: {exc}"}
    if response.status_code != 200:
        return {
            "error": f"library_error_{response.status_code}",
            "detail": response.text[:300],
        }
    return response.json()


async def library_search(arguments: dict[str, Any], context: dict[str, Any]) -> Any:
    return await _library_get(
        "/internal/library/search",
        {
            "q": str(arguments.get("q") or ""),
            "standard_no": str(arguments.get("standard_no") or ""),
            "limit": max(1, min(int(arguments.get("limit") or 5), 20)),
        },
    )


async def library_outline(arguments: dict[str, Any], context: dict[str, Any]) -> Any:
    return await _library_get(
        "/internal/library/outline",
        {"standard_no": str(arguments.get("standard_no") or "")},
    )


async def library_section(arguments: dict[str, Any], context: dict[str, Any]) -> Any:
    return await _library_get(
        "/internal/library/section",
        {
            "standard_no": str(arguments.get("standard_no") or ""),
            "clause_id": str(arguments.get("clause_id") or ""),
            "page_no": int(arguments.get("page_no") or 0),
        },
    )


async def library_table(arguments: dict[str, Any], context: dict[str, Any]) -> Any:
    return await _library_get(
        "/internal/library/table",
        {
            "standard_no": str(arguments.get("standard_no") or ""),
            "table_id": str(arguments.get("table_id") or ""),
            "page_no": int(arguments.get("page_no") or 0),
            "offset": max(0, int(arguments.get("offset") or 0)),
            "limit": max(1, min(int(arguments.get("limit") or 20), 40)),
        },
    )


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
            name="get_table",
            description=(
                "Return table metadata, headers and a bounded row range "
                "(offset/limit, read-only)."
            ),
            input_schema={
                "type": "object",
                "required": ["table_id"],
                "properties": {
                    "table_id": {"type": "string"},
                    "offset": {"type": "integer", "minimum": 0},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 30},
                },
            },
            handler=get_table,
        )
    )
    registry.register(
        Tool(
            name="get_records",
            description="Return extracted records, optionally filtered by table_id/record_id.",
            input_schema={
                "type": "object",
                "properties": {
                    "table_id": {"type": "string"},
                    "record_id": {"type": "string"},
                    "offset": {"type": "integer", "minimum": 0},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50},
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
    registry.register(
        Tool(
            name="escalate_to_human",
            description="Declare that a table or record needs human review.",
            input_schema={
                "type": "object",
                "required": ["reason"],
                "properties": {
                    "reason": {"type": "string"},
                    "table_ids": {"type": "array", "items": {"type": "string"}},
                },
            },
            permission="write",
            handler=escalate_to_human,
        )
    )
    registry.register(
        Tool(
            name="run_sandbox",
            description="Execute the provided sandbox_request and return a summary.",
            input_schema={"type": "object", "properties": {}},
            permission="write",
            handler=run_sandbox,
        )
    )
    registry.register(
        Tool(
            name="request_review",
            description="Run the provided review_request and return the decision summary.",
            input_schema={"type": "object", "properties": {}},
            permission="write",
            handler=request_review,
        )
    )
    registry.register(
        Tool(
            name="library_search",
            description=(
                "Search a referenced standard (already indexed in the local "
                "library) for a keyword; returns page/clause snippets."
            ),
            input_schema={
                "type": "object",
                "required": ["q", "standard_no"],
                "properties": {
                    "q": {"type": "string"},
                    "standard_no": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                },
            },
            handler=library_search,
            timeout_seconds=25.0,
        )
    )
    registry.register(
        Tool(
            name="library_outline",
            description="Return the clause and table outline of a referenced standard.",
            input_schema={
                "type": "object",
                "required": ["standard_no"],
                "properties": {"standard_no": {"type": "string"}},
            },
            handler=library_outline,
            timeout_seconds=25.0,
        )
    )
    registry.register(
        Tool(
            name="library_section",
            description="Read one clause or page of a referenced standard (bounded).",
            input_schema={
                "type": "object",
                "required": ["standard_no"],
                "properties": {
                    "standard_no": {"type": "string"},
                    "clause_id": {"type": "string"},
                    "page_no": {"type": "integer", "minimum": 0},
                },
            },
            handler=library_section,
            timeout_seconds=25.0,
        )
    )
    registry.register(
        Tool(
            name="library_table",
            description=(
                "Read a bounded row range of one table in a referenced standard."
            ),
            input_schema={
                "type": "object",
                "required": ["standard_no"],
                "properties": {
                    "standard_no": {"type": "string"},
                    "table_id": {"type": "string"},
                    "page_no": {"type": "integer", "minimum": 0},
                    "offset": {"type": "integer", "minimum": 0},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 40},
                },
            },
            handler=library_table,
            timeout_seconds=25.0,
        )
    )
    return registry
