"""Method matching against the business dictionary."""

from __future__ import annotations

import re

from ..contracts import CanonicalMatch
from .dictionary import DictionaryIndex
from .normalize import (
    extract_standards,
    normalize_item_name,
    normalize_standard_no,
    standard_base,
)

SPLIT_RE = re.compile(r"[、,，;；]+")
INTERNAL_REF_RE = re.compile(
    r"^(?:[A-Z](?:\.\d+)+|[A-Z]?\.?\d+(?:\.\d+)+|附\s*录\s*[A-Z])$"
)
YEAR_SUFFIX_RE = re.compile(r"(?:-|:)\s*((?:19|20)?\d{2})\s*$")


def method_year(standard_no: str | None) -> int:
    """Return a comparable publication year from a standard number."""

    match = YEAR_SUFFIX_RE.search(normalize_standard_no(standard_no))
    if match is None:
        return 0
    raw = match.group(1)
    if len(raw) == 4:
        return int(raw)
    value = int(raw)
    return 2000 + value if value <= 29 else 1900 + value


def latest_version(entries: list) -> object | None:
    """Pick the latest version when all entries share the same standard base."""

    if not entries:
        return None
    bases = {standard_base(entry.standard_no) for entry in entries if entry.standard_no}
    if len(bases) != 1:
        return None
    return max(
        entries,
        key=lambda entry: (
            method_year(entry.standard_no),
            bool(method_year(entry.standard_no)),
            normalize_standard_no(entry.standard_no),
            entry.business_code,
        ),
    )


def match_method(
    raw: str,
    index: DictionaryIndex,
    evidence: list[str] | None = None,
    *,
    name_hint: str | None = None,
) -> CanonicalMatch:
    version = index.dictionary.version
    evidence = evidence or []
    standards = extract_standards(raw)
    for standard in standards:
        entries = index.standard_index.get(standard_base(standard), [])
        if len(entries) == 1:
            return _match(raw, entries[0], "exact", 1.0, version, evidence)
        if len(entries) > 1:
            exact = [
                entry
                for entry in entries
                if normalize_standard_no(entry.standard_no)
                == normalize_standard_no(standard)
            ]
            if exact:
                # Always promote to the latest edition carried by the
                # method dictionary, matching the business normalization rule.
                latest = latest_version(entries)
                return _match(
                    raw,
                    latest or exact[0],
                    "exact",
                    1.0,
                    version,
                    evidence,
                    reason="同一标准多版本，取最新版本",
                )
            latest = latest_version(entries)
            if latest is None:
                return _ambiguous(
                    raw, entries, version, evidence, "多个方法标准号，需人工确认"
                )
            return _match(
                raw,
                latest,
                "exact",
                0.99,
                version,
                evidence,
                reason="同一标准多版本，取最新版本",
            )
    if not standards and INTERNAL_REF_RE.match(raw.strip()):
        return CanonicalMatch(
            raw=raw,
            match_type="new",
            score=0.0,
            dictionary_version=version,
            evidence=evidence,
            status="new",
            reason="内部条款引用，不建立方法",
        )
    for name in (name_hint, raw):
        if not name:
            continue
        entries = index.name_index.get(("method", normalize_item_name(name)), [])
        if len(entries) == 1:
            return _match(raw, entries[0], "exact", 1.0, version, evidence)
        if len(entries) > 1:
            latest = latest_version(entries)
            if latest is not None:
                return _match(
                    raw,
                    latest,
                    "exact",
                    0.99,
                    version,
                    evidence,
                    reason="同一方法多版本，取最新版本",
                )
        entries = index.alias_index.get(("method", normalize_item_name(name)), [])
        if len(entries) == 1:
            return _match(raw, entries[0], "alias", 0.98, version, evidence)
        if len(entries) > 1:
            latest = latest_version(entries)
            if latest is not None:
                return _match(
                    raw,
                    latest,
                    "alias",
                    0.98,
                    version,
                    evidence,
                    reason="同一方法多版本，取最新版本",
                )
    return CanonicalMatch(
        raw=raw,
        match_type="new",
        score=0.0,
        dictionary_version=version,
        evidence=evidence,
        status="new",
        reason="业务词典无匹配方法",
    )


def match_method_cell(
    raw: str,
    index: DictionaryIndex,
    evidence: list[str] | None = None,
) -> list[CanonicalMatch]:
    parts = [part.strip() for part in SPLIT_RE.split(raw or "") if part.strip()]
    if not parts:
        return []
    matches: list[CanonicalMatch] = []
    seen: set[str] = set()
    for part in parts:
        match = match_method(part, index, evidence)
        key = match.canonical_id or match.raw
        if key in seen:
            continue
        seen.add(key)
        matches.append(match)
    return matches


def _match(
    raw: str,
    entry,
    kind: str,
    score: float,
    version: str,
    evidence: list,
    reason: str | None = None,
) -> CanonicalMatch:
    return CanonicalMatch(
        raw=raw,
        canonical_id=entry.business_code,
        canonical_name=entry.business_name,
        match_type=kind,
        score=round(score, 4),
        dictionary_version=version,
        evidence=evidence,
        status="matched",
        reason=reason,
    )


def _ambiguous(raw: str, entries: list, version: str, evidence: list, reason: str) -> CanonicalMatch:
    return CanonicalMatch(
        raw=raw,
        canonical_id=entries[0].business_code,
        canonical_name=entries[0].business_name,
        match_type="ambiguous",
        score=1.0,
        dictionary_version=version,
        evidence=evidence,
        status="ambiguous",
        reason=reason,
    )
