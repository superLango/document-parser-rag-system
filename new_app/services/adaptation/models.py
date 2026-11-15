"""Edition-aware adaptation skeleton (P1-12).

A standard "edition" (GB/T 1591-2018, AMS 4050K, ...) gets a profile of its
table signatures.  New editions are compared against that profile so the
pipeline can decide between no action (L0), a profile patch (L1), a recipe
candidate (L2) or a code candidate (L3).  L2/L3 only produce plans here; the
sandbox verification and human diff gates stay in the orchestration layer.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class TableSignature(BaseModel):
    caption: str = ""
    profile: str = "unknown"
    n_cols: int = 0
    header_signature: list[str] = Field(default_factory=list)
    measures: list[str] = Field(default_factory=list)


class EditionProfile(BaseModel):
    standard_id: str
    edition: str
    document_sha256: str = ""
    page_count: int = 0
    tables: list[TableSignature] = Field(default_factory=list)
    # 该版本固定使用的配方版本；新版本适配不得自动改变旧版本的 pin。
    recipe_pins: dict[str, str] = Field(default_factory=dict)
    sample_doc_id: str = ""
    created_at: str = ""


class DriftKind(StrEnum):
    MISSING_TABLE = "missing_table"
    NEW_TABLE = "new_table"
    HEADER_CHANGED = "header_changed"
    MEASURE_LOST = "measure_lost"
    PROFILE_CHANGED = "profile_changed"


class DriftItem(BaseModel):
    kind: DriftKind
    table: str = ""
    detail: str = ""
    severity: str = "warning"  # info | warning | error


class DriftReport(BaseModel):
    standard_id: str
    edition: str
    expected_tables: int = 0
    matched_tables: int = 0
    drifts: list[DriftItem] = Field(default_factory=list)
    score: float = 1.0

    @property
    def critical(self) -> list[DriftItem]:
        return [item for item in self.drifts if item.severity == "error"]


class AdaptationLevel(StrEnum):
    L0_NONE = "L0"
    L1_PROFILE_PATCH = "L1"
    L2_RECIPE_CANDIDATE = "L2"
    L3_CODE_CANDIDATE = "L3"


class AdaptationPlan(BaseModel):
    level: AdaptationLevel
    reasons: list[str] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    requires_sandbox: bool = False
    requires_human: bool = False
    preserve_edition_pin: bool = True
