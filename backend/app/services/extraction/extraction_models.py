"""E3 抽取数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ExtractionTarget:
    feature: str
    category_id: str
    template_id: str
    description: str = ""
    return_type: str = "array"
    extraction_strategy: str = "auto"
    fixed_query: str = ""
    query_sources: list[dict] = field(default_factory=list)
    query_terms: list[str] = field(default_factory=list)
    top_k: int | None = None
    max_tokens: int | None = None
    confidence_threshold: float | None = None
    fields: list[dict] = field(default_factory=list)
    schema: dict = field(default_factory=dict)
    hits: list[dict] = field(default_factory=list)
    hit_score: float | None = None
    hit_count: int = 0
    term_data: dict[str, list[dict]] = field(default_factory=dict)


@dataclass
class CategoryResult:
    feature: str
    records: list[dict] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)
    hit_score: float | None = None
    hit_count: int = 0

    def to_dict(self) -> dict:
        return {
            "feature": self.feature,
            "records": self.records,
            "rejected": self.rejected,
            "missing_fields": self.missing_fields,
            "hit_score": self.hit_score,
            "hit_count": self.hit_count,
        }


@dataclass
class SkippedFeature:
    feature: str
    reason: str
    score: float | None = None
