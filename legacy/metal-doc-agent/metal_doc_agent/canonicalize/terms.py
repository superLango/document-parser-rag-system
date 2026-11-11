"""New-term store: pending terms, promotion and rejection."""

from __future__ import annotations

import json
from pathlib import Path

from ..contracts import (
    BusinessDictionary,
    BusinessDictionaryEntry,
    NewTerm,
    NewTermStore,
)
from .normalize import normalize_item_name


def load_new_terms(path: str | Path) -> NewTermStore:
    target = Path(path)
    if not target.exists():
        return NewTermStore()
    return NewTermStore.model_validate_json(target.read_text(encoding="utf-8"))


def save_new_terms(store: NewTermStore, path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(store.model_dump(mode="json"), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )


def merge_new_terms(
    store: NewTermStore, terms: list[NewTerm], *, keep_missing: bool = True
) -> NewTermStore:
    index: dict[tuple, NewTerm] = {}
    for term in store.terms:
        index[_key(term)] = term
    incoming: set[tuple] = set()
    for term in terms:
        key = _key(term)
        incoming.add(key)
        existing = index.get(key)
        if existing is None:
            index[key] = term
            continue
        existing.frequency += term.frequency
        for evidence in term.evidence:
            if evidence not in existing.evidence:
                existing.evidence.append(evidence)
        if existing.status == "pending" and term.status != "pending":
            existing.status = term.status
    if not keep_missing:
        index = {
            key: term for key, term in index.items() if key in incoming
        }
    return NewTermStore(
        dictionary_version=store.dictionary_version
        or (terms[0].dictionary_version if terms else "")
        or "",
        terms=sorted(
            index.values(), key=lambda term: (term.type, term.raw, term.family or "")
        ),
    )


def find_term(
    store: NewTermStore, raw: str, term_type: str | None = None
) -> NewTerm | None:
    target = normalize_item_name(raw)
    for term in store.terms:
        if normalize_item_name(term.raw) != target:
            continue
        if term_type and term.type != term_type:
            continue
        return term
    return None


def promote_term(
    store: NewTermStore,
    raw: str,
    *,
    business_code: str,
    business_name: str | None = None,
    override_path: str | Path,
    version: str | None = None,
    term_type: str | None = None,
) -> NewTerm:
    term = find_term(store, raw, term_type)
    if term is None:
        raise ValueError(f"new term not found: {raw}")
    term.status = "active"
    term.suggested_code = business_code
    dictionary = _load_override(override_path, version or store.dictionary_version)
    facets = {
        key: [value] for key, value in term.facets.items() if value
    }
    entry = BusinessDictionaryEntry(
        business_code=business_code,
        business_name=business_name or term.raw,
        type=term.type,
        family=term.family,
        facets=facets,
        aliases=[term.raw],
        standard_no=None,
        status="active",
        version=version or store.dictionary_version,
    )
    dictionary.entries = [
        item
        for item in dictionary.entries
        if not (item.type, item.business_code) == (entry.type, entry.business_code)
    ] + [entry]
    _write_override(dictionary, override_path)
    return term


def reject_term(
    store: NewTermStore, raw: str, term_type: str | None = None
) -> NewTerm:
    term = find_term(store, raw, term_type)
    if term is None:
        raise ValueError(f"new term not found: {raw}")
    term.status = "rejected"
    return term


def _key(term: NewTerm) -> tuple:
    return (
        term.type,
        normalize_item_name(term.raw),
        term.family or "",
        tuple(sorted(term.facets.items())),
    )


def _load_override(path: str | Path, version: str) -> BusinessDictionary:
    target = Path(path)
    if not target.exists():
        return BusinessDictionary(version=version, source="json", entries=[])
    return BusinessDictionary.model_validate_json(
        target.read_text(encoding="utf-8")
    )


def _write_override(dictionary: BusinessDictionary, path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(dictionary.model_dump(mode="json"), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
