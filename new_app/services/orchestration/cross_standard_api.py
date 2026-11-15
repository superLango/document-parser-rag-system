# ruff: noqa: B008
"""Cross-standard task and standard-library endpoints.

The UI reads ``cross-standard`` for the task panel; the agent tools read the
library endpoints to locate clauses/tables inside a referenced standard.
"""

from __future__ import annotations

import json
import re
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from . import library
from .db import SessionLocal
from .models import Artifact
from .workflow import _cross_standard_source

router = APIRouter(prefix="/internal")


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


async def _latest_artifact(run_id: str, role: str) -> Artifact | None:
    async with SessionLocal() as session:
        result = await session.execute(
            select(Artifact)
            .where(Artifact.run_id == run_id, Artifact.role == role)
            .order_by(Artifact.created_at.desc())
        )
        return result.scalars().first()


@router.get("/runs/{run_id}/cross-standard")
async def get_cross_standard(run_id: str) -> dict[str, Any]:
    artifact = await _latest_artifact(run_id, "cross_standard")
    if artifact is None:
        return {"schema_version": "cross-standard/1", "tasks": [], "stats": {}}
    from .workflow import get_store

    try:
        return json.loads(await get_store().get_bytes(artifact.storage_key))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500, detail={"code": "ARTIFACT_READ_FAILED", "message": str(exc)}
        ) from exc


@router.get("/library/standards")
async def list_standards(q: str = Query(default="")) -> dict[str, Any]:
    async with SessionLocal() as session:
        rows = list((await library.ensure_index(session)).values())
    keyword = q.strip().lower()
    items = []
    for row in rows:
        payload = library.to_dict(row)
        haystack = " ".join(
            [payload["standard_no"], payload["edition"], payload["title"]]
        ).lower()
        if keyword and keyword not in haystack:
            continue
        items.append(payload)
    items.sort(key=lambda item: (item["standard_no"], item["edition"]))
    return {"total": len(items), "standards": items}


async def _resolve_source(standard_no: str) -> tuple[dict[str, Any], dict[str, Any]]:
    async with SessionLocal() as session:
        rows = await library.find_standard(session, standard_no)
    row = library.latest_row(rows)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "STANDARD_NOT_INDEXED", "message": standard_no},
        )
    source = await _cross_standard_source(row.document_id)
    return library.to_dict(row), source


@router.get("/library/search")
async def search_library(
    q: str = Query(..., min_length=1),
    standard_no: str = Query(default=""),
    limit: int = Query(default=5, ge=1, le=20),
) -> dict[str, Any]:
    if not standard_no:
        raise HTTPException(
            status_code=400,
            detail={"code": "STANDARD_REQUIRED", "message": "standard_no is required"},
        )
    meta, source = await _resolve_source(standard_no)
    needle = q.strip().lower()
    hits: list[dict[str, Any]] = []
    for page in source.get("pages") or []:
        text = str(page.get("markdown") or "")
        position = text.lower().find(needle)
        if position < 0:
            continue
        hits.append(
            {
                "kind": "text",
                "page_no": page.get("page_no") or 0,
                "snippet": _clean(text[max(0, position - 80) : position + 220]),
            }
        )
        if len(hits) >= limit:
            break
    for item in (source.get("inventory") or {}).get("items") or []:
        if not isinstance(item, dict):
            continue
        haystack = " ".join(
            [
                str(item.get("feature") or ""),
                str(item.get("item") or ""),
                str(item.get("requirement") or ""),
            ]
        ).lower()
        if needle not in haystack:
            continue
        hits.append(
            {
                "kind": "requirement",
                "feature": item.get("feature"),
                "page_no": item.get("page_no") or 0,
                "clause_id": item.get("clause_id") or "",
                "snippet": _clean(item.get("requirement"))[:300],
            }
        )
        if len(hits) >= limit:
            break
    return {"standard": meta, "hits": hits}


@router.get("/library/outline")
async def library_outline(standard_no: str = Query(...)) -> dict[str, Any]:
    meta, source = await _resolve_source(standard_no)
    clauses = [
        {
            "clause_id": item.get("clause_id") or "",
            "title": item.get("title") or "",
            "page_no": item.get("page_no") or 0,
        }
        for item in (source.get("clauses") or {}).get("clauses") or []
        if isinstance(item, dict)
    ]
    tables = [
        {
            "table_id": item.get("table_id") or "",
            "page_no": item.get("page_no") or 0,
            "caption": item.get("caption") or "",
            "profile": item.get("profile") or "",
            "header_paths": item.get("header_paths") or [],
        }
        for item in (source.get("result") or {}).get("tables") or []
        if isinstance(item, dict)
    ]
    return {
        "standard": meta,
        "clauses": clauses[:120],
        "tables": tables[:40],
        "features": [
            item.get("feature")
            for item in (source.get("inventory") or {}).get("items") or []
            if isinstance(item, dict) and item.get("feature")
        ],
    }


@router.get("/library/section")
async def library_section(
    standard_no: str = Query(...),
    clause_id: str = Query(default=""),
    page_no: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    meta, source = await _resolve_source(standard_no)
    if clause_id:
        for item in (source.get("clauses") or {}).get("clauses") or []:
            if isinstance(item, dict) and str(item.get("clause_id")) == clause_id:
                return {
                    "standard": meta,
                    "clause_id": clause_id,
                    "page_no": item.get("page_no") or 0,
                    "title": item.get("title") or "",
                    "text": _clean(item.get("text"))[:6000],
                }
    if page_no:
        for page in source.get("pages") or []:
            if int(page.get("page_no") or 0) == page_no:
                return {
                    "standard": meta,
                    "page_no": page_no,
                    "text": _clean(page.get("markdown"))[:6000],
                }
    raise HTTPException(
        status_code=404,
        detail={"code": "SECTION_NOT_FOUND", "message": f"{clause_id or page_no}"},
    )


@router.get("/library/table")
async def library_table(
    standard_no: str = Query(...),
    table_id: str = Query(default=""),
    page_no: int = Query(default=0, ge=0),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=40),
) -> dict[str, Any]:
    meta, source = await _resolve_source(standard_no)
    tables = [
        item
        for item in (source.get("result") or {}).get("tables") or []
        if isinstance(item, dict)
    ]
    chosen = None
    for item in tables:
        if table_id and str(item.get("table_id")) == table_id:
            chosen = item
            break
        if page_no and int(item.get("page_no") or 0) == page_no:
            chosen = item
            break
    if chosen is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "TABLE_NOT_FOUND", "message": f"{table_id or page_no}"},
        )
    rows = chosen.get("rows") or []
    headers: list[str] = []
    paths = chosen.get("header_paths") or []
    if paths and isinstance(paths[0], list):
        for path in paths:
            headers.extend(str(cell) for cell in path if str(cell).strip())
    elif isinstance(paths, list):
        headers.extend(str(cell) for cell in paths if str(cell).strip())
    headers.extend(str(cell) for cell in (chosen.get("headers") or []))
    return {
        "standard": meta,
        "table_id": chosen.get("table_id"),
        "page_no": chosen.get("page_no"),
        "caption": chosen.get("caption"),
        "headers": list(dict.fromkeys(headers))[:80],
        "rows": rows[offset : offset + limit],
        "offset": offset,
        "has_more": offset + limit < len(rows),
    }
