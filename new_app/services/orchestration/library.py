"""Standard library index.

Cross-standard expansion needs to answer one question first: *do we have the
body of the referenced standard?*  The index maps a normalized standard number
to the uploaded document that carries it, plus a coarse status
(``indexed`` → ``ocr_ready`` → ``parsed``) and the categories/grades that its
parse produced.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from .models import Document, Run, StandardIndex

STANDARD_RE = re.compile(
    r"(?P<org>GB\s*/\s*T|GBT|GB|GJB\s*/\s*Z|GJB|JB\s*/\s*T|YB\s*/\s*T|YS\s*/\s*T|"
    r"HB\s*/\s*Z|HB|ASTM|ASME|AMS(?:-STD)?|ISO|EN|DIN|JIS|NB\s*/\s*T|API|QJ|"
    r"Q\s*/\s*[A-Za-z0-9]+)"
    r"[\s_-]*(?P<num>[A-Z]{0,3}\s*\d+(?:[.\-]\d+)*)",
    re.IGNORECASE,
)
ORG_ALIASES = {
    "GBT": "GB/T",
    "GBIT": "GB/T",
    "GB": "GB",
    "GJB": "GJB",
    "JBT": "JB/T",
    "JB": "JB",
    "YBT": "YB/T",
    "YB": "YB",
    "YST": "YS/T",
    "YS": "YS",
    "HBT": "HB/T",
    "HB": "HB",
    "ASTM": "ASTM",
    "ASME": "ASME",
    "AMS-STD": "AMS",
    "AMS": "AMS",
    "ISO": "ISO",
    "EN": "EN",
    "DIN": "DIN",
    "JIS": "JIS",
    "API": "API",
    "QJ": "QJ",
    "NBT": "NB/T",
    "NB": "NB",
}
FILENAME_NOISE_RE = re.compile(
    r"(?:[-—_ ]*(?:过期|作废|现行|有效|已废止|--+|\+\+?))+$", re.IGNORECASE
)
YEAR_RE = re.compile(r"^(?P<base>.+?)[-—–－](?P<year>\d{4}|\d{2})$")
# ASTM/AMS/ASME print two-digit years ("B862-23"); other orgs use part numbers
# that can also be two digits, so only strip a two-digit year for these.
TWO_DIGIT_YEAR_ORGS = {"ASTM", "AMS", "ASME"}


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(value or ""))).strip()


def normalize_standard_no(value: Any) -> str:
    text = _clean(value).upper().replace("—", "-").replace("–", "-").replace("－", "-")
    match = STANDARD_RE.search(text)
    if match is None:
        return re.sub(r"\s+", "", text)
    org = re.sub(r"\s+", "", match.group("org")).upper()
    org = ORG_ALIASES.get(org, org)
    number = re.sub(r"\s+", "", match.group("num")).upper()
    return f"{org} {number}"


def split_edition(standard_no: str) -> tuple[str, str]:
    """Split ``GB/T 14845-2026`` into ``("GB/T 14845", "2026")``."""
    match = YEAR_RE.match(_clean(standard_no).upper())
    if match is None:
        return standard_no, ""
    base = match.group("base").strip()
    year = match.group("year")
    if not base:
        return standard_no, ""
    if len(year) == 2:
        org = base.split(" ")[0].upper()
        if org not in TWO_DIGIT_YEAR_ORGS:
            return standard_no, ""
        year = str(1900 + int(year) if int(year) >= 70 else 2000 + int(year))
    return base, year


def parse_filename(filename: str) -> dict[str, str]:
    """Extract ``standard_no`` / ``edition`` / ``title`` from a filename."""
    stem = re.sub(r"\.(?:pdf|md|markdown|txt)$", "", _clean(filename), flags=re.I)
    stem = FILENAME_NOISE_RE.sub("", stem).strip()
    match = STANDARD_RE.search(stem)
    if match is None:
        return {"standard_no": "", "edition": "", "title": stem[:256]}
    standard_no = normalize_standard_no(match.group(0))
    standard_no, edition = split_edition(standard_no)
    rest = FILENAME_NOISE_RE.sub("", stem[match.end() :]).strip(" -_—–:：")
    if len(rest) <= 1 and rest.isalpha():
        # "AMS5663P" 的 P 是修订号，不是标题。
        rest = ""
    return {"standard_no": standard_no, "edition": edition, "title": rest[:256]}


def _edition_key(edition: str) -> int:
    try:
        return int(edition)
    except (TypeError, ValueError):
        return 0


def latest_row(rows: Iterable[StandardIndex]) -> StandardIndex | None:
    """Newest edition wins; rows without an edition rank last."""
    items = [row for row in rows if row is not None]
    if not items:
        return None
    return max(
        items,
        key=lambda row: (
            _edition_key(str(row.edition or "")),
            row.updated_at or datetime.min.replace(tzinfo=UTC),
        ),
    )


def to_dict(row: StandardIndex) -> dict[str, Any]:
    return {
        "id": row.id,
        "document_id": row.document_id,
        "standard_no": row.standard_no or "",
        "edition": row.edition or "",
        "title": row.title or "",
        "source_kind": row.source_kind or "upload",
        "status": row.status or "indexed",
        "page_count": int(row.page_count or 0),
        "categories": list(row.categories or []),
        "grades": list(row.grades or []),
        "latest_run_id": row.latest_run_id or "",
    }


async def ensure_index(session) -> dict[str, StandardIndex]:
    """Upsert every document into the index (idempotent, runs from filename)."""
    documents = (await session.execute(select(Document))).scalars().all()
    rows = (await session.execute(select(StandardIndex))).scalars().all()
    existing = {row.document_id: row for row in rows}
    changed = False
    for document in documents:
        parsed = parse_filename(document.filename)
        row = existing.get(document.id)
        if row is None:
            row = StandardIndex(
                document_id=document.id,
                standard_no=parsed["standard_no"],
                edition=parsed["edition"],
                title=parsed["title"],
                source_kind="upload",
                status="indexed",
                categories=[],
                grades=[],
            )
            session.add(row)
            existing[document.id] = row
            changed = True
            continue
        if not row.standard_no and parsed["standard_no"]:
            row.standard_no = parsed["standard_no"]
            row.edition = parsed["edition"]
            if not row.title:
                row.title = parsed["title"]
            row.updated_at = datetime.now(UTC)
            changed = True
    if changed:
        await session.commit()
    return existing


def _record_categories(records: list[dict[str, Any]]) -> list[str]:
    values: set[str] = set()
    for record in records or []:
        for prop in (record.get("properties") or {}).values():
            if not isinstance(prop, dict):
                continue
            category = str(prop.get("business_category") or prop.get("feature") or "").strip()
            if category:
                values.add(category)
    return sorted(values)


def _record_grades(records: list[dict[str, Any]]) -> list[str]:
    return sorted(
        {
            str(record.get("grade") or "").strip()
            for record in records or []
            if str(record.get("grade") or "").strip()
        }
    )


async def refresh_from_run(
    session,
    run: Run,
    *,
    references: dict[str, Any] | None = None,
    records: list[dict[str, Any]] | None = None,
    page_count: int = 0,
) -> StandardIndex | None:
    """Update the index row after OCR/sandbox so sources become resolvable."""
    row = (
        await session.execute(
            select(StandardIndex).where(StandardIndex.document_id == run.document_id)
        )
    ).scalars().first()
    if row is None:
        document = await session.get(Document, run.document_id)
        if document is None:
            return None
        parsed = parse_filename(document.filename)
        row = StandardIndex(
            document_id=document.id,
            standard_no=parsed["standard_no"],
            edition=parsed["edition"],
            title=parsed["title"],
            source_kind="upload",
            status="indexed",
            categories=[],
            grades=[],
        )
        session.add(row)
    self_standard = normalize_standard_no((references or {}).get("self_standard") or "")
    if self_standard:
        self_standard, edition = split_edition(self_standard)
        row.standard_no = self_standard
        if edition:
            row.edition = edition
    if records is not None:
        row.status = "parsed"
        row.categories = _record_categories(records)
        row.grades = _record_grades(records)
    elif row.status == "indexed":
        row.status = "ocr_ready"
    row.page_count = int(page_count or row.page_count or 0)
    row.latest_run_id = run.id
    row.updated_at = datetime.now(UTC)
    await session.commit()
    return row


async def find_standard(session, standard_no: str) -> list[StandardIndex]:
    key = normalize_standard_no(standard_no)
    if not key:
        return []
    rows = (await session.execute(select(StandardIndex))).scalars().all()
    matched: list[StandardIndex] = []
    for row in rows:
        if normalize_standard_no(row.standard_no) == key:
            matched.append(row)
    return matched
