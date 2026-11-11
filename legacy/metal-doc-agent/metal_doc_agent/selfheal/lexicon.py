"""Learned lexicon overlay.

The business dictionary is user-owned and read-only for the agent. Learned
surface forms go to a separate append-only file and are merged at load time,
so no dictionary file is ever modified. Conflicts with an existing mapping are
rejected instead of overridden.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from ..contracts import BusinessDictionary, BusinessDictionaryEntry
from ..canonicalize.dictionary import normalize_item_name

PROTECTED_DICTIONARY_FILES = (
    "configs/dictionaries/categories.json",
    "configs/dictionaries/items.json",
    "configs/dictionaries/methods.json",
    "configs/business_dictionary.hanson.json",
    "configs/business_dictionary.local.json",
)
LEARNED_DIR = "configs/learned"
LEARNED_LEXICON = "lexicon.jsonl"
LEARNED_RULES = "rules.jsonl"


def dictionary_paths(project_root: str | Path) -> list[Path]:
    root = Path(project_root)
    return [root / name for name in PROTECTED_DICTIONARY_FILES]


def dictionary_hashes(project_root: str | Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in dictionary_paths(project_root):
        if not path.exists():
            continue
        hashes[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def dictionary_unchanged(
    before: dict[str, str], project_root: str | Path
) -> tuple[bool, str]:
    after = dictionary_hashes(project_root)
    changed = [
        Path(path).name
        for path, digest in before.items()
        if after.get(path) != digest
    ]
    added = [Path(path).name for path in after if path not in before]
    if changed or added:
        return False, "词典文件被修改：" + "、".join(changed + added)
    return True, "词典文件未改动"


def lexicon_path(project_root: str | Path) -> Path:
    return Path(project_root) / LEARNED_DIR / LEARNED_LEXICON


def load_learned_entries(project_root: str | Path) -> list[dict[str, Any]]:
    path = lexicon_path(project_root)
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict) and item.get("surface") and item.get("canonical"):
            rows.append(item)
    return rows


def add_learned_alias(
    project_root: str | Path,
    *,
    surface: str,
    canonical: str,
    source_feedback: str = "",
    kind: str = "alias",
) -> tuple[dict[str, Any] | None, str]:
    """Append one learned surface form if it does not conflict with the dictionary."""

    normalized_surface = normalize_item_name(surface)
    normalized_canonical = normalize_item_name(canonical)
    if not normalized_surface or not normalized_canonical:
        return None, "空别名或空标准名"
    if normalized_surface == normalized_canonical:
        return None, "别名与标准名相同"

    from ..schema_projection import load_dictionary_index

    index = load_dictionary_index(project_root)
    if index is not None:
        existing = index.alias_index.get(("item", normalized_surface)) or index.name_index.get(
            ("item", normalized_surface)
        )
        if existing and all(
            normalize_item_name(entry.business_name) != normalized_canonical
            for entry in existing
        ):
            names = "、".join(entry.business_name for entry in existing)
            return None, f"冲突：{surface} 已映射到 {names}"
        item_entries = index.name_index.get(("item", normalized_canonical)) or []
        if not item_entries:
            return None, f"标准名 {canonical} 不在业务词典中，拒绝新增项目"
    path = lexicon_path(project_root)
    for row in load_learned_entries(project_root):
        if row.get("surface") == surface and row.get("canonical") == canonical:
            return row, "已存在"
        if row.get("surface") == surface and row.get("canonical") != canonical:
            return None, f"冲突：学习层已把 {surface} 映射到 {row.get('canonical')}"
    entry = {
        "surface": surface,
        "canonical": canonical,
        "kind": kind,
        "source_feedback": source_feedback,
        "created_at": _now(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry, "ok"


def apply_learned_lexicon(
    dictionary: BusinessDictionary, project_root: str | Path
) -> BusinessDictionary:
    """Merge learned surface forms as aliases without touching source files."""

    learned = load_learned_entries(project_root)
    if not learned:
        return dictionary
    entries = list(dictionary.entries)
    item_by_name: dict[str, int] = {
        normalize_item_name(entry.business_name): index
        for index, entry in enumerate(entries)
        if entry.type == "item" and entry.status == "active"
    }
    occupied: dict[str, str] = {}
    for entry in entries:
        if entry.type != "item":
            continue
        occupied[normalize_item_name(entry.business_name)] = entry.business_name
        for alias in entry.aliases:
            occupied[normalize_item_name(alias)] = entry.business_name
    added = 0
    for row in learned:
        canonical = row.get("canonical") or ""
        surface = row.get("surface") or ""
        index = item_by_name.get(normalize_item_name(canonical))
        if index is None or not surface:
            continue
        entry = entries[index]
        normalized = normalize_item_name(surface)
        owner = occupied.get(normalized)
        if owner is not None and owner != entry.business_name:
            continue
        if normalized in {normalize_item_name(alias) for alias in entry.aliases}:
            continue
        clone = entry.model_copy(deep=True)
        clone.aliases.append(surface)
        entries[index] = clone
        occupied[normalized] = entry.business_name
        added += 1
    if not added:
        return dictionary
    return dictionary.model_copy(update={"entries": entries})


def record_learned_rule(
    project_root: str | Path, payload: dict[str, Any]
) -> None:
    path = Path(project_root) / LEARNED_DIR / LEARNED_RULES
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _now() -> str:
    import time

    return time.strftime("%Y-%m-%dT%H:%M:%S")


def normalize(text: str) -> str:
    return re.sub(r"\s+", "", str(text or ""))
