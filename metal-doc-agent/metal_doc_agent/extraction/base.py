"""Extractor interface and shared output type."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from ..contracts import DocumentMeta, Evidence, Record, TableGrid


@dataclass
class ExtractionOutput:
    records: list[Record] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)


class Extractor(Protocol):
    name: str

    def extract(self, table: TableGrid, document: DocumentMeta) -> ExtractionOutput:
        ...
