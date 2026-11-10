"""Business dictionary adapters, indexing and version diff."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ..contracts import BusinessDictionary, BusinessDictionaryEntry
from .normalize import (
    normalize_item_name,
    normalize_standard_no,
    standard_base,
)


class DictionaryAdapter:
    source = "json"

    def load(self) -> BusinessDictionary:
        raise NotImplementedError


class JsonDictionaryAdapter(DictionaryAdapter):
    source = "json"

    def __init__(self, path: str | Path, override_path: str | Path | None = None):
        self.path = Path(path)
        self.override_path = Path(override_path) if override_path else None

    def load(self) -> BusinessDictionary:
        base = BusinessDictionary.model_validate_json(
            self.path.read_text(encoding="utf-8")
        )
        if self.override_path and self.override_path.exists():
            override = BusinessDictionary.model_validate_json(
                self.override_path.read_text(encoding="utf-8")
            )
            base = merge_dictionaries(base, override)
        return base


class ApiDictionaryAdapter(DictionaryAdapter):
    source = "api"

    def __init__(self, fetcher: Callable[[], dict], version: str = "api"):
        self.fetcher = fetcher
        self.version = version

    def load(self) -> BusinessDictionary:
        payload = self.fetcher()
        payload.setdefault("version", self.version)
        payload.setdefault("source", "api")
        return BusinessDictionary.model_validate(payload)


class DbDictionaryAdapter(DictionaryAdapter):
    source = "db"

    def __init__(self, loader: Callable[[], dict], version: str = "db"):
        self.loader = loader
        self.version = version

    def load(self) -> BusinessDictionary:
        payload = self.loader()
        payload.setdefault("version", self.version)
        payload.setdefault("source", "db")
        return BusinessDictionary.model_validate(payload)


def load_dictionary(
    project_root: str | Path,
    source: str = "json",
    *,
    api_fetcher: Callable[[], dict] | None = None,
    db_loader: Callable[[], dict] | None = None,
    use_override: bool = True,
) -> BusinessDictionary:
    root = Path(project_root)
    if source == "api":
        if api_fetcher is None:
            raise ValueError("api dictionary requires api_fetcher")
        return ApiDictionaryAdapter(api_fetcher).load()
    if source == "db":
        if db_loader is None:
            raise ValueError("db dictionary requires db_loader")
        return DbDictionaryAdapter(db_loader).load()
    adapter = JsonDictionaryAdapter(
        root / "configs" / "business_dictionary.json",
        root / "configs" / "business_dictionary.local.json" if use_override else None,
    )
    return adapter.load()


def merge_dictionaries(
    base: BusinessDictionary, override: BusinessDictionary
) -> BusinessDictionary:
    entries: dict[tuple[str, str], BusinessDictionaryEntry] = {}
    for entry in base.entries:
        entries[(entry.type, entry.business_code)] = entry
    for entry in override.entries:
        existing = entries.get((entry.type, entry.business_code))
        if existing is None:
            entries[(entry.type, entry.business_code)] = entry
            continue
        merged = existing.model_copy(deep=True)
        merged.business_name = entry.business_name or merged.business_name
        merged.family = entry.family or merged.family
        merged.facets = {**merged.facets, **entry.facets}
        merged.aliases = sorted(
            {*merged.aliases, *entry.aliases}, key=len, reverse=True
        )
        merged.standard_no = entry.standard_no or merged.standard_no
        merged.status = entry.status
        entries[(entry.type, entry.business_code)] = merged
    return BusinessDictionary(
        version=override.version or base.version,
        source=override.source if override.entries else base.source,
        entries=list(entries.values()),
    )


DICTIONARY_FILENAMES: dict[str, str] = {
    "category": "categories.json",
    "item": "items.json",
    "method": "methods.json",
}


def dictionary_file_for_type(directory: str | Path, entry_type: str) -> Path:
    try:
        filename = DICTIONARY_FILENAMES[entry_type]
    except KeyError as exc:
        raise ValueError(f"unknown dictionary type: {entry_type}") from exc
    return Path(directory) / filename


def split_dictionary(dictionary: BusinessDictionary) -> dict[str, BusinessDictionary]:
    """Split one mixed dictionary into the three independent dictionaries."""

    return {
        entry_type: BusinessDictionary(
            version=dictionary.version,
            source=dictionary.source,
            entries=[
                entry.model_copy(deep=True)
                for entry in dictionary.entries
                if entry.type == entry_type
            ],
        )
        for entry_type in DICTIONARY_FILENAMES
    }


def write_dictionary_parts(
    directory: str | Path,
    dictionary: BusinessDictionary,
    *,
    version: str | None = None,
) -> dict[str, Path]:
    """Write categories/items/methods as independent JSON files."""

    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    parts = split_dictionary(dictionary)
    paths: dict[str, Path] = {}
    for entry_type, part in parts.items():
        if version:
            part = part.model_copy(update={"version": version})
        path = dictionary_file_for_type(target, entry_type)
        path.write_text(
            json.dumps(part.model_dump(mode="json"), ensure_ascii=False, indent=2)
            + "\n",
            encoding="utf-8",
        )
        paths[entry_type] = path
    return paths


def load_dictionary_path(path: str | Path) -> BusinessDictionary:
    """Load a split dictionary directory or a legacy single JSON file."""

    target = Path(path)
    if target.is_file():
        return JsonDictionaryAdapter(target, None).load()
    if not target.is_dir():
        raise FileNotFoundError(f"business dictionary not found: {target}")

    parts: list[tuple[str, BusinessDictionary]] = []
    for entry_type in DICTIONARY_FILENAMES:
        file = dictionary_file_for_type(target, entry_type)
        if not file.exists():
            continue
        parts.append(
            (
                entry_type,
                BusinessDictionary.model_validate_json(
                    file.read_text(encoding="utf-8")
                ),
            )
        )
    if parts:
        entries: list[BusinessDictionaryEntry] = []
        for entry_type, part in parts:
            entries.extend(
                entry.model_copy(update={"type": entry_type})
                for entry in part.entries
            )
        versions = {part.version for _, part in parts}
        version = (
            next(iter(versions))
            if len(versions) == 1
            else "|".join(f"{entry_type}:{part.version}" for entry_type, part in parts)
        )
        return BusinessDictionary(
            version=version,
            source=parts[0][1].source,
            entries=entries,
        )
    for legacy_name in (
        "business_dictionary.json",
        "business_dictionary.hanson.json",
    ):
        legacy = target / legacy_name
        if legacy.exists():
            return JsonDictionaryAdapter(legacy, None).load()
    raise FileNotFoundError(f"business dictionary not found: {target}")


def diff_dictionaries(
    old: BusinessDictionary, new: BusinessDictionary
) -> dict:
    old_map = {(entry.type, entry.business_code): entry for entry in old.entries}
    new_map = {(entry.type, entry.business_code): entry for entry in new.entries}
    added = sorted(code for code in new_map if code not in old_map)
    removed = sorted(code for code in old_map if code not in new_map)
    changed = []
    for key in sorted(set(old_map) & set(new_map)):
        before = old_map[key]
        after = new_map[key]
        if before.model_dump() != after.model_dump():
            changed.append(
                {
                    "type": key[0],
                    "code": key[1],
                    "before": before.model_dump(),
                    "after": after.model_dump(),
                }
            )
    return {
        "old_version": old.version,
        "new_version": new.version,
        "added": added,
        "removed": removed,
        "changed": changed,
    }


@dataclass
class DictionaryIndex:
    dictionary: BusinessDictionary
    name_index: dict[tuple[str, str], list[BusinessDictionaryEntry]]
    alias_index: dict[tuple[str, str], list[BusinessDictionaryEntry]]
    family_index: dict[str, list[BusinessDictionaryEntry]]
    standard_index: dict[str, list[BusinessDictionaryEntry]]
    category_name_index: dict[str, list[BusinessDictionaryEntry]] = field(
        default_factory=dict
    )
    category_alias_index: dict[str, list[BusinessDictionaryEntry]] = field(
        default_factory=dict
    )
    item_by_category: dict[str, list[BusinessDictionaryEntry]] = field(
        default_factory=dict
    )

    @property
    def has_categories(self) -> bool:
        return bool(self.category_name_index)

    @classmethod
    def build(cls, dictionary: BusinessDictionary) -> "DictionaryIndex":
        name_index: dict[tuple[str, str], list[BusinessDictionaryEntry]] = {}
        alias_index: dict[tuple[str, str], list[BusinessDictionaryEntry]] = {}
        family_index: dict[str, list[BusinessDictionaryEntry]] = {}
        standard_index: dict[str, list[BusinessDictionaryEntry]] = {}
        category_name_index: dict[str, list[BusinessDictionaryEntry]] = {}
        category_alias_index: dict[str, list[BusinessDictionaryEntry]] = {}
        item_by_category: dict[str, list[BusinessDictionaryEntry]] = {}
        for entry in dictionary.entries:
            if entry.status != "active":
                continue
            if entry.type == "category":
                _add(category_name_index, normalize_item_name(entry.business_name), entry)
                for alias in entry.aliases:
                    _add(category_alias_index, normalize_item_name(alias), entry)
            elif entry.type == "item":
                _add(name_index, (entry.type, normalize_item_name(entry.business_name)), entry)
                for alias in entry.aliases:
                    _add(alias_index, (entry.type, normalize_item_name(alias)), entry)
                if entry.family:
                    family_index.setdefault(entry.family, []).append(entry)
                if entry.category_code:
                    item_by_category.setdefault(entry.category_code, []).append(entry)
            else:
                if entry.standard_no:
                    _add(
                        standard_index,
                        standard_base(entry.standard_no),
                        entry,
                    )
                _add(name_index, ("method", normalize_item_name(entry.business_name)), entry)
                for alias in entry.aliases:
                    _add(alias_index, ("method", normalize_item_name(alias)), entry)
        return cls(
            dictionary=dictionary,
            name_index=name_index,
            alias_index=alias_index,
            family_index=family_index,
            standard_index=standard_index,
            category_name_index=category_name_index,
            category_alias_index=category_alias_index,
            item_by_category=item_by_category,
        )


def _add(index: dict, key, entry: BusinessDictionaryEntry) -> None:
    index.setdefault(key, [])
    if all(item.business_code != entry.business_code for item in index[key]):
        index[key].append(entry)
