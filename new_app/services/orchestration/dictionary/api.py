# ruff: noqa: B008
"""Business dictionary endpoint.

The baseline snapshot is the legacy ``business_dictionary.json``. M8 owns the
formal import/reconciliation; this module serves the query page and accepts
manual JSON imports from the UI.
"""

import json
import os
import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter(prefix="/internal/dictionary")

DATA_FILE = Path(
    os.getenv("DICTIONARY_DATA_FILE")
    or (
        Path(__file__).resolve().parent.parent
        / "data"
        / "dictionary"
        / "business_dictionary.json"
    )
)
REQUIRED_FIELDS = ("business_code", "business_name", "type")


class DictionaryImport(BaseModel):
    entries: list[dict] = Field(default_factory=list)
    replace: bool = False


def load_dictionary() -> dict:
    return json.loads(DATA_FILE.read_text(encoding="utf-8"))


def write_dictionary(payload: dict) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    # 保留现有文件的换行风格与结尾换行，避免导入后整份文件产生无意义 diff。
    existing = DATA_FILE.read_bytes() if DATA_FILE.exists() else b""
    newline = "\r\n" if b"\r\n" in existing else "\n"
    handle, temp_name = tempfile.mkstemp(dir=DATA_FILE.parent, suffix=".json")
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline=newline) as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            if not existing or existing.endswith(b"\n"):
                stream.write("\n")
        Path(temp_name).replace(DATA_FILE)
    except Exception:
        Path(temp_name).unlink(missing_ok=True)
        raise


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


@router.post("/import")
def import_entries(body: DictionaryImport) -> dict:
    """Merge imported entries by ``(type, business_code)``.

    ``replace=true`` rewrites the snapshot with only the uploaded entries; the
    default merges and overwrites entries with the same key.
    """
    if not body.entries:
        raise HTTPException(status_code=400, detail="entries is empty")
    current = load_dictionary()
    base_entries = [] if body.replace else list(current.get("entries") or [])
    merged = {
        (str(item.get("type") or ""), str(item.get("business_code") or "")): item
        for item in base_entries
    }
    created = updated = skipped = 0
    for raw in body.entries:
        if not isinstance(raw, dict) or any(
            not str(raw.get(field) or "").strip() for field in REQUIRED_FIELDS
        ):
            skipped += 1
            continue
        key = (str(raw["type"]), str(raw["business_code"]))
        if key in merged:
            updated += 1
        else:
            created += 1
        merged[key] = {**merged.get(key, {}), **raw}

    entries = list(merged.values())
    families: dict[str, int] = {}
    for item in entries:
        name = str(item.get("family") or "unclassified")
        families[name] = families.get(name, 0) + 1
    version = str(current.get("version") or "manual")
    payload = {
        **current,
        "version": version,
        "source": current.get("source") or "manual-import",
        "stats": {
            **(current.get("stats") or {}),
            "entries": len(entries),
        },
        "entries": entries,
    }
    write_dictionary(payload)
    return {
        "version": version,
        "total": len(entries),
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "families": families,
    }
