"""Versioned concept dictionary: user wording -> business concept -> evidence."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from .measures import normalize

DATA_FILE = Path(__file__).with_name("data") / "concepts.json"


@dataclass(frozen=True)
class Concept:
    concept_id: str
    name: str
    aliases: tuple[str, ...]
    parents: tuple[str, ...] = ()
    measures: tuple[str, ...] = ()
    section_kind: str = ""
    conditions: tuple[str, ...] = ()
    anti_conditions: tuple[str, ...] = ()
    languages: tuple[str, ...] = ("zh",)

    def terms(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys((*self.aliases, *self.parents)))


@dataclass
class ConceptDictionary:
    version: str
    concepts: list[Concept] = field(default_factory=list)

    def match(self, text: str) -> tuple[Concept, str] | None:
        """Longest dictionary term contained in the (normalized) utterance."""
        normalized = normalize(text)
        best: tuple[int, Concept, str] | None = None
        for concept in self.concepts:
            for term in concept.terms():
                token = normalize(term)
                if token and token in normalized and (best is None or len(token) > best[0]):
                    best = (len(token), concept, term)
        if best is None:
            return None
        return best[1], best[2]

    def by_kind(self, kind: str) -> list[Concept]:
        return [concept for concept in self.concepts if concept.section_kind == kind]

    def by_id(self, concept_id: str) -> Concept | None:
        return next(
            (concept for concept in self.concepts if concept.concept_id == concept_id),
            None,
        )


def load_dictionary(path: str | Path | None = None) -> ConceptDictionary:
    return _load(Path(path) if path else DATA_FILE)


@lru_cache(maxsize=8)
def _load(path: Path) -> ConceptDictionary:
    payload: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
    concepts = [
        Concept(
            concept_id=str(item["concept_id"]),
            name=str(item.get("name") or item["concept_id"]),
            aliases=tuple(str(alias) for alias in item.get("aliases") or ()),
            parents=tuple(str(parent) for parent in item.get("parents") or ()),
            measures=tuple(str(measure) for measure in item.get("measures") or ()),
            section_kind=str(item.get("section_kind") or ""),
            conditions=tuple(str(value) for value in item.get("conditions") or ()),
            anti_conditions=tuple(str(value) for value in item.get("anti_conditions") or ()),
            languages=tuple(str(value) for value in item.get("languages") or ("zh",)),
        )
        for item in payload.get("concepts") or []
    ]
    return ConceptDictionary(version=str(payload.get("version") or ""), concepts=concepts)
