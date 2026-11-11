# ruff: noqa: B008
"""Read-only business dictionary endpoint.

The baseline snapshot is the legacy ``business_dictionary.json``. M8 owns the
formal import/reconciliation; this module only serves the query page.
"""

import json
from pathlib import Path

from fastapi import APIRouter, Query

router = APIRouter(prefix="/internal/dictionary")

DATA_FILE = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "dictionary"
    / "business_dictionary.json"
)


def load_dictionary() -> dict:
    return json.loads(DATA_FILE.read_text(encoding="utf-8"))


@router.get("")
def list_entries(
    type: str = Query(default=""),
    q: str = Query(default=""),
    family: str = Query(default=""),
    status: str = Query(default=""),
    limit: int = Query(default=500, ge=1, le=2000),
) -> dict:
    payload = load_dictionary()
    entries = list(payload.get("entries") or [])
    if type:
        entries = [item for item in entries if item.get("type") == type]
    if family:
        entries = [item for item in entries if item.get("family") == family]
    if status:
        entries = [item for item in entries if item.get("status") == status]
    keyword = q.strip().lower()
    if keyword:
        entries = [
            item
            for item in entries
            if keyword
            in " ".join(
                [
                    str(item.get("business_code") or ""),
                    str(item.get("business_name") or ""),
                    str(item.get("family") or ""),
                    " ".join(str(alias) for alias in item.get("aliases") or []),
                ]
            ).lower()
        ]
    families: dict[str, int] = {}
    for item in entries:
        key = str(item.get("family") or "unclassified")
        families[key] = families.get(key, 0) + 1
    return {
        "version": payload.get("version") or "",
        "source": payload.get("source") or "",
        "total": len(entries),
        "families": families,
        "entries": entries[:limit],
    }
