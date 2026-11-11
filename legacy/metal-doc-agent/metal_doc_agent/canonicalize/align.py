"""Align ItemInventory with the business dictionary (M1.8).

Three business term sets are supported:

* 项目大类 (``category``) <- item groups (``ItemInventoryEntry``);
* 检测项目 (``item``) <- individual properties of a group;
* 试验方法 (``method``) <- cited standards.

Dictionaries that only contain flat items keep the previous behaviour: the
group is matched directly against ``item`` entries and no property matching is
attempted.
"""

from __future__ import annotations

from collections import Counter

from ..contracts import (
    AlignmentResult,
    CanonicalMatch,
    ItemInventory,
    NewTerm,
    PropertyMatch,
)
from .dictionary import DictionaryIndex
from .items import IDENTITY_DIMS, match_item, match_property
from .methods import match_method_cell
from .normalize import normalize_item_name

SKIP_FACETS = {"sampling_quantity", "sampling_position"}


def align_inventory(
    inventory: ItemInventory,
    index: DictionaryIndex,
    *,
    semantic=None,
    category_mode: str = "advisory",
) -> tuple[ItemInventory, AlignmentResult]:
    aligned = inventory.model_copy(deep=True)
    item_matches: list[CanonicalMatch] = []
    property_matches: list[PropertyMatch] = []
    method_matches: list[CanonicalMatch] = []
    new_terms: dict[tuple, NewTerm] = {}
    category_mode_enabled = index.has_categories
    strict_categories = category_mode_enabled and category_mode == "strict"
    excluded = 0

    for entry in aligned.items:
        match = match_item(entry, index, semantic=semantic)
        item_matches.append(match)
        entry.business_code = match.canonical_id
        entry.business_name = match.canonical_name
        entry.match_type = match.match_type
        entry.match_score = match.score
        entry.dictionary_version = match.dictionary_version
        if category_mode:
            entry.business_category_code = (
                match.category_code if match.status == "matched" else None
            )
            entry.business_category_name = (
                match.category_name if match.status == "matched" else None
            )
            entry.category_match_type = match.match_type
        if match.status == "new" and not category_mode_enabled:
            _add_new_term(
                new_terms,
                NewTerm(
                    type="item",
                    raw=entry.item_raw,
                    family=entry.item_family,
                    facets=_identity_facets(entry.facets),
                    reason=match.reason or "业务词典无匹配",
                    evidence=list(entry.evidence),
                    dictionary_version=match.dictionary_version,
                ),
            )

        if strict_categories and match.status != "matched":
            if (
                match.match_type == "ambiguous"
                and entry.item_family in {"hardness", "impact"}
            ):
                # “硬度试验”同时命中布氏/洛氏/维氏属于量纲歧义，不是未知
                # 大类。具体尺度由表格记录决定（HB/HRC/HV），因此保留项目，
                # 只把状态降为 probable。
                entry.status = "probable"
            else:
                # Strict category mode: the business category list defines the
                # extraction boundary. Unknown or ambiguous categories are not
                # projected and do not become category-level new terms.
                entry.status = "not_applicable"
                excluded += 1
                continue

        if category_mode_enabled:
            for prop in entry.properties:
                prop_match = match_property(
                    prop,
                    index,
                    category_code=entry.business_category_code,
                    category_name=entry.business_category_name,
                    evidence=list(entry.evidence),
                )
                entry.property_matches.append(prop_match)
                property_matches.append(prop_match)
                if prop_match.status == "new":
                    _add_new_term(
                        new_terms,
                        NewTerm(
                            type="item",
                            raw=prop,
                            family=entry.item_family,
                            facets=_category_facet(entry.business_category_name),
                            reason=(
                                f"检测项目未命中（项目大类："
                                f"{entry.business_category_name or entry.item_canonical or entry.item_raw}）"
                            ),
                            evidence=list(entry.evidence),
                            dictionary_version=prop_match.dictionary_version,
                        ),
                    )

        if entry.method_standard:
            matches = match_method_cell(
                entry.method_standard, index, entry.evidence
            )
            method_matches.extend(matches)
            matched = [item for item in matches if item.status == "matched"]
            if matched:
                entry.method_code = "、".join(
                    item.canonical_id or "" for item in matched
                )
                entry.method_name = "、".join(
                    item.canonical_name or "" for item in matched
                )
                entry.method_match_type = (
                    matched[0].match_type if len(matches) == 1 else "exact"
                )
            elif matches:
                entry.method_match_type = matches[0].match_type
            for method_match in matches:
                if method_match.status == "new" and "内部条款引用" not in (
                    method_match.reason or ""
                ):
                    _add_new_term(
                        new_terms,
                        NewTerm(
                            type="method",
                            raw=method_match.raw,
                            reason=method_match.reason or "业务词典无匹配方法",
                            evidence=list(entry.evidence),
                            dictionary_version=method_match.dictionary_version,
                        ),
                    )

    matches_by_key: dict[tuple, CanonicalMatch] = {}
    for match in method_matches:
        matches_by_key.setdefault(
            (
                match.canonical_id or normalize_item_name(match.raw),
                match.status,
            ),
            match,
        )
    method_matches = list(matches_by_key.values())
    property_matches = _dedupe_properties(property_matches)
    new_list = sorted(
        new_terms.values(),
        key=lambda term: (term.type, term.raw, term.family or ""),
    )
    summary = _summary(
        aligned, item_matches, property_matches, method_matches, new_list, excluded
    )
    result = AlignmentResult(
        doc_id=inventory.doc_id,
        dictionary_version=index.dictionary.version,
        item_matches=item_matches,
        property_matches=property_matches,
        method_matches=method_matches,
        new_terms=new_list,
        summary=summary,
    )
    return aligned, result


def _dedupe_properties(matches: list[PropertyMatch]) -> list[PropertyMatch]:
    deduped: dict[tuple, PropertyMatch] = {}
    for match in matches:
        deduped.setdefault(
            (match.canonical_id or normalize_item_name(match.raw), match.status),
            match,
        )
    return list(deduped.values())


def _add_new_term(store: dict[tuple, NewTerm], term: NewTerm) -> None:
    key = (
        term.type,
        normalize_item_name(term.raw),
        term.family or "",
        tuple(sorted(term.facets.items())),
    )
    existing = store.get(key)
    if existing is None:
        store[key] = term
        return
    existing.frequency += 1
    for evidence in term.evidence:
        if evidence not in existing.evidence:
            existing.evidence.append(evidence)


def _identity_facets(facets: dict[str, str]) -> dict[str, str]:
    return {
        key: value
        for key, value in facets.items()
        if key in IDENTITY_DIMS and value
    }


def _category_facet(name: str | None) -> dict[str, str]:
    return {"business_category": name} if name else {}


def _summary(
    inventory: ItemInventory,
    item_matches: list[CanonicalMatch],
    property_matches: list[PropertyMatch],
    method_matches: list[CanonicalMatch],
    new_terms: list[NewTerm],
    excluded: int = 0,
) -> dict:
    item_counts = Counter(match.status for match in item_matches)
    property_counts = Counter(match.status for match in property_matches)
    method_counts = Counter(match.status for match in method_matches)
    total_items = len(item_matches)
    total_properties = len(property_matches)
    total_methods = len(method_matches)
    return {
        "categories_total": total_items,
        "categories_matched": item_counts["matched"],
        "categories_new": item_counts["new"],
        "categories_ambiguous": item_counts["ambiguous"],
        "categories_excluded": excluded,
        "category_match_rate": _ratio(item_counts["matched"], total_items),
        "items_total": total_items,
        "items_matched": item_counts["matched"],
        "items_new": item_counts["new"],
        "items_ambiguous": item_counts["ambiguous"],
        "item_match_rate": _ratio(item_counts["matched"], total_items),
        "properties_total": total_properties,
        "properties_matched": property_counts["matched"],
        "properties_new": property_counts["new"],
        "properties_ambiguous": property_counts["ambiguous"],
        "property_match_rate": _ratio(property_counts["matched"], total_properties),
        "methods_total": total_methods,
        "methods_matched": method_counts["matched"],
        "methods_new": method_counts["new"],
        "methods_ambiguous": method_counts["ambiguous"],
        "method_match_rate": _ratio(method_counts["matched"], total_methods),
        "new_terms": len(new_terms),
        "new_categories": sum(1 for term in new_terms if term.type == "category"),
        "new_items": sum(1 for term in new_terms if term.type == "item"),
        "new_methods": sum(1 for term in new_terms if term.type == "method"),
        "dictionary_version": inventory.items[0].dictionary_version
        if inventory.items
        else None,
    }


def _ratio(numerator: float, denominator: float) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0
