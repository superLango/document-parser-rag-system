"""Edition profile storage and OCR signature extraction."""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any

from .models import EditionProfile, TableSignature, now_iso

DEFAULT_ROOT = Path(__file__).resolve().parents[1] / "recipe_registry" / "data" / "editions"
MEASURE_TOKENS = (
    "抗拉强度", "屈服强度", "规定塑性延伸强度", "上屈服强度", "下屈服强度",
    "断后伸长率", "断面收缩率", "冲击吸收能量", "冲击功", "布氏硬度",
    "洛氏硬度", "维氏硬度", "断裂韧度", "弯曲", "碳当量", "pcm",
    "rm", "rp0.2", "rp1.0", "reh", "rel", "a", "z", "kv2", "ku2", "ku5",
    "hb", "hbw", "hrc", "hrb", "hv", "kic",
)
CAPTION_KEY_RE = re.compile(r"(?:表|table)\s*([a-z]?\.?\s*\d+(?:\.\d+)?)", re.IGNORECASE)
STANDARD_RE = re.compile(
    r"(GB\s*/\s*T|GBT|GB|GJB|JB|HB|YS\s*/\s*T|YST|YS|YB|ASTM|ASME|AMS|ISO|EN|DIN|API|NB)"
    r"[\s_\-]*([A-Z]{0,2})[\s_\-]*(\d+(?:\.\d+)?)"
    r"(?:\s*[-_—]\s*(\d{4}|[A-Z]|\d{2})|([A-Z]))?",
    re.IGNORECASE,
)
PARTS_STANDARD_RE = re.compile(
    r"(ISO|EN|DIN)\s*(\d+(?:\.\d+)?)-(\d+)(?:\s*[-_—]\s*(\d{4}))?",
    re.IGNORECASE,
)


def resolve_standard(filename: str) -> tuple[str, str] | None:
    """Resolve ``(standard_id, edition)`` from a filename like ``GBT 1591-2018``.

    Returns ``None`` when the filename carries no recognisable standard code;
    adaptation is then skipped instead of guessing an edition.
    """
    stem = Path(filename or "").stem.upper()
    parts = PARTS_STANDARD_RE.search(stem)
    if parts:
        prefix, number, part, year = parts.groups()
        return f"{prefix} {number}-{part}", year or "UNKNOWN"
    match = STANDARD_RE.search(stem)
    if not match:
        return None
    prefix, letter, number, dated, revision = match.groups()
    prefix = re.sub(r"\s+", "", prefix)
    prefix = {"GBT": "GB/T", "YST": "YS/T"}.get(prefix, prefix)
    designation = f"{letter}{number}" if letter else number
    standard_id = f"{prefix} {designation}"
    edition = dated or revision or "UNKNOWN"
    return standard_id, edition


def normalize_signature(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).lower()
    text = re.sub(r"\s+", "", text)
    return text


def caption_key(caption: str) -> str:
    match = CAPTION_KEY_RE.search(unicodedata.normalize("NFKC", caption or ""))
    if not match:
        return ""
    return re.sub(r"\s+", "", match.group(1)).upper()


def header_measures(headers: list[str]) -> list[str]:
    measures = []
    for header in headers:
        lowered = header.lower()
        for token in MEASURE_TOKENS:
            if token.isascii():
                # ``a``/``z`` must not match the unit suffix of ``MPa``.
                if re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", lowered):
                    if token not in measures:
                        measures.append(token)
            elif token in lowered and token not in measures:
                measures.append(token)
    return measures


def signature_of(table: dict[str, Any]) -> TableSignature:
    headers = [
        normalize_signature(" / ".join(str(part) for part in path if part))
        for path in (table.get("header_paths") or [])
    ]
    return TableSignature(
        caption=str(table.get("caption") or ""),
        profile=str(table.get("profile") or "unknown"),
        n_cols=int(table.get("n_cols") or len(headers)),
        header_signature=headers,
        measures=header_measures(headers),
    )


class EditionStore:
    """One JSON file per (standard, edition), mirroring the recipe registry."""

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root) if root else DEFAULT_ROOT

    @staticmethod
    def build(
        standard_id: str,
        edition: str,
        ocr: dict[str, Any],
        *,
        document_sha256: str = "",
        page_count: int | None = None,
        sample_doc_id: str = "",
        recipe_pins: dict[str, str] | None = None,
    ) -> EditionProfile:
        tables = [signature_of(table) for table in (ocr.get("tables") or [])]
        pages = page_count if page_count is not None else len(ocr.get("pages") or [])
        return EditionProfile(
            standard_id=standard_id,
            edition=edition,
            document_sha256=document_sha256,
            page_count=pages,
            tables=tables,
            recipe_pins=dict(recipe_pins or {}),
            sample_doc_id=sample_doc_id,
            created_at=now_iso(),
        )

    def path(self, standard_id: str, edition: str) -> Path:
        safe = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]+", "_", standard_id)
        return self.root / safe / f"{edition}.json"

    def save(self, profile: EditionProfile) -> Path:
        path = self.path(profile.standard_id, profile.edition)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(profile.model_dump(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return path

    def get(self, standard_id: str, edition: str) -> EditionProfile | None:
        path = self.path(standard_id, edition)
        if not path.exists():
            return None
        return EditionProfile.model_validate_json(path.read_text(encoding="utf-8"))

    def list(self) -> list[dict[str, str]]:
        if not self.root.exists():
            return []
        found: list[dict[str, str]] = []
        for path in sorted(self.root.glob("*/*.json")):
            try:
                profile = EditionProfile.model_validate_json(
                    path.read_text(encoding="utf-8")
                )
            except ValueError:
                continue
            found.append(
                {
                    "standard_id": profile.standard_id,
                    "edition": profile.edition,
                    "sample_doc_id": profile.sample_doc_id,
                    "tables": str(len(profile.tables)),
                }
            )
        return found
