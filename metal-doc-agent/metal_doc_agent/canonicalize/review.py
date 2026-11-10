"""Business term review: override dictionary writes and alignment refresh.

P3 closes the loop without writing the upstream business system:

* accepted/mapped terms go into ``configs/business_dictionary.local.json``;
* rejected terms stay in ``new_terms.json`` with status ``rejected``;
* the current job's alignment is recomputed so the document reflects the decision.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ..contracts import (
    AlignmentResult,
    BusinessDictionary,
    BusinessDictionaryEntry,
    ItemInventory,
    NewTerm,
    NewTermStore,
)
from .align import align_inventory
from .dictionary import DictionaryIndex, merge_dictionaries, write_dictionary_parts
from .normalize import normalize_item_name
from .terms import load_new_terms, save_new_terms

REVIEW_ACTIONS = {"accept", "map", "reject"}


def find_new_term(
    store: NewTermStore, term_type: str, raw: str
) -> NewTerm | None:
    target = normalize_item_name(raw)
    for term in store.terms:
        if term.type == term_type and normalize_item_name(term.raw) == target:
            return term
    return None


def review_new_term(
    dictionary: BusinessDictionary,
    override_path: str | Path,
    term: NewTerm,
    action: str,
    *,
    business_code: str | None = None,
    business_name: str | None = None,
    target_code: str | None = None,
    category_code: str | None = None,
    category_name: str | None = None,
    standard_no: str | None = None,
) -> tuple[BusinessDictionary, str, str]:
    """Apply one review decision.

    Returns ``(merged_dictionary, applied_code, term_status)``.
    ``reject`` leaves the dictionary untouched.
    """

    if action not in REVIEW_ACTIONS:
        raise ValueError(f"unknown review action: {action}")
    if action == "reject":
        return dictionary, "", "rejected"

    if action == "map":
        if not target_code:
            raise ValueError("map requires target_code")
        target = next(
            (
                entry
                for entry in dictionary.entries
                if entry.type == term.type
                and entry.business_code == target_code
                and entry.status == "active"
            ),
            None,
        )
        if target is None:
            raise ValueError(f"target dictionary entry not found: {target_code}")
        entry = BusinessDictionaryEntry(
            business_code=target.business_code,
            business_name=target.business_name,
            type=term.type,
            family=target.family,
            facets=target.facets,
            aliases=[term.raw],
            standard_no=target.standard_no,
            category_code=target.category_code,
            category_name=target.category_name,
            status="active",
            version=target.version or dictionary.version,
        )
        applied_code = target.business_code
    else:
        code = business_code or _generated_code(term)
        name = business_name or term.raw
        entry = BusinessDictionaryEntry(
            business_code=code,
            business_name=name,
            type=term.type,
            family=term.family,
            facets={
                key: [value]
                for key, value in term.facets.items()
                if key != "business_category" and value
            },
            aliases=[term.raw] if name != term.raw else [],
            standard_no=standard_no
            or (term.raw if term.type == "method" else None),
            category_code=category_code,
            category_name=category_name,
            status="active",
            version=dictionary.version,
        )
        applied_code = code

    target = Path(override_path)
    if target.is_dir() or not target.suffix:
        # Split dictionaries: write the affected entry into the matching
        # categories/items/methods file and keep all three files in sync.
        merged = merge_dictionaries(
            dictionary,
            BusinessDictionary(
                version=dictionary.version,
                source="offline_snapshot",
                entries=[entry],
            ),
        )
        write_dictionary_parts(target, merged)
        return merged, applied_code, "active"

    override = load_override(override_path, dictionary.version)
    _upsert(override, entry)
    save_dictionary(override_path, override)
    return merge_dictionaries(dictionary, override), applied_code, "active"


def load_override(path: str | Path, version: str) -> BusinessDictionary:
    target = Path(path)
    if not target.exists():
        return BusinessDictionary(version=version, source="offline_snapshot", entries=[])
    return BusinessDictionary.model_validate_json(
        target.read_text(encoding="utf-8")
    )


def save_dictionary(path: str | Path, dictionary: BusinessDictionary) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(dictionary.model_dump(mode="json"), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )


def reapply_alignment(
    out_dir: str | Path,
    dictionary: BusinessDictionary,
    *,
    category_mode: str = "advisory",
) -> tuple[AlignmentResult, NewTermStore]:
    """Recompute alignment for one job and refresh its artifacts."""

    root = Path(out_dir)
    inventory = ItemInventory.model_validate_json(
        (root / "item_inventory.json").read_text(encoding="utf-8")
    )
    index = DictionaryIndex.build(dictionary)
    aligned, result = align_inventory(
        inventory, index, category_mode=category_mode
    )

    previous_path = root / "new_terms.json"
    previous = load_new_terms(previous_path) if previous_path.exists() else NewTermStore()
    status_by_key = {
        (term.type, normalize_item_name(term.raw)): term.status
        for term in previous.terms
        if term.status != "pending"
    }
    for term in result.new_terms:
        status = status_by_key.get((term.type, normalize_item_name(term.raw)))
        if status:
            term.status = status
    store = NewTermStore(
        dictionary_version=dictionary.version, terms=result.new_terms
    )

    (root / "item_inventory_aligned.json").write_text(
        json.dumps(aligned.model_dump(mode="json"), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    (root / "alignment.json").write_text(
        json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    save_new_terms(store, previous_path)
    return result, store


def _generated_code(term: NewTerm) -> str:
    digest = hashlib.sha1(term.raw.encode("utf-8")).hexdigest()[:8]
    return f"LOCAL:{term.type.upper()}:{digest}"


def _upsert(
    override: BusinessDictionary, entry: BusinessDictionaryEntry
) -> None:
    for index, existing in enumerate(override.entries):
        if (
            existing.type == entry.type
            and existing.business_code == entry.business_code
        ):
            merged = existing.model_copy(deep=True)
            merged.business_name = entry.business_name or merged.business_name
            merged.family = entry.family or merged.family
            merged.facets = {**merged.facets, **entry.facets}
            merged.aliases = sorted(
                {*merged.aliases, *entry.aliases}, key=len, reverse=True
            )
            merged.standard_no = entry.standard_no or merged.standard_no
            merged.category_code = entry.category_code or merged.category_code
            merged.category_name = entry.category_name or merged.category_name
            merged.status = entry.status
            override.entries[index] = merged
            return
    override.entries.append(entry)
