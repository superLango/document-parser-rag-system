"""E3 术语集加载（类别展开 + Prompt 占位符数据）。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.glossary import TERM_STATUS_ACTIVE, Term


async def load_term_base(db: AsyncSession, kb_id, term_base_id, limit: int = 1000) -> list[dict]:
    rows = (
        await db.execute(
            select(Term).where(
                Term.kb_id == kb_id,
                Term.term_base_id == term_base_id,
                Term.status == TERM_STATUS_ACTIVE,
            ).limit(limit)
        )
    ).scalars().all()
    return [
        {
            "term_name": t.term_name,
            "standard_name": t.standard_name,
            "english_term": t.english_term,
            "definition": t.definition,
            "category": t.category,
            "synonyms": t.synonyms or [],
            "aliases": t.aliases or [],
            "standard_number": t.standard_number,
            "extras": t.extras or {},
        }
        for t in rows
    ]


def _read(row: dict, field: str):
    if field in row and row[field] not in (None, ""):
        return row[field]
    return row.get("extras", {}).get(field)


def field_values(rows: list[dict], field: str) -> list[str]:
    out: list[str] = []
    for r in rows:
        v = _read(r, field)
        if isinstance(v, list):
            out.extend(str(x) for x in v if x not in (None, ""))
        elif v not in (None, ""):
            out.append(str(v))
    return list(dict.fromkeys(out))


def distinct_field_values(rows: list[dict], field: str, limit: int = 200) -> list[str]:
    return field_values(rows, field)[:limit]
