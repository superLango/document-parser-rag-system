"""Field risk scoring for review prioritisation (M4.1-05, M4.3 高风险拦截)."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..contracts import DocumentResult, Evidence
from ..tablegrid.normalize import ELEMENTS

HIGH_RISK_PROPERTIES = {
    "Rm",
    "Rp0.2",
    "A",
    "Z",
    "KV2",
    "KU2",
    "HB",
    "HBW",
    "HRC",
    "HV",
    "CEV",
    "Pcm",
    *ELEMENTS,
}

# Open bounds (≥/≤/range) are the norm for every element limit in a chemistry
# table, so grading them all "medium" turned the review queue into noise (6756
# medium fields, 0 high). Medium is reserved for open bounds on properties a
# human must actually confirm (direction, condition, unit); routine element
# limits stay low and are covered by batch accept.
REVIEW_MEDIUM_PROPERTIES = {
    "Rm",
    "Rp0.2",
    "A",
    "A50mm",
    "Z",
    "KV2",
    "KU2",
    "HB",
    "HBW",
    "HRC",
    "HRB",
    "HV",
    "CEV",
    "Pcm",
}

LEVEL_ORDER = {"high": 0, "medium": 1, "low": 2}


@dataclass(frozen=True)
class FieldRisk:
    field_path: str
    record_id: str
    property: str
    level: str
    reasons: list[str] = field(default_factory=list)
    evidence_id: str | None = None
    page_no: int | None = None

    def to_dict(self) -> dict:
        return {
            "field_path": self.field_path,
            "record_id": self.record_id,
            "property": self.property,
            "level": self.level,
            "reasons": self.reasons,
            "evidence_id": self.evidence_id,
            "page_no": self.page_no,
        }


def field_risks(
    result: DocumentResult, evidence: list[Evidence] | None = None
) -> list[FieldRisk]:
    evidence_index = {item.evidence_id: item for item in (evidence or [])}
    risks: list[FieldRisk] = []
    for record in result.records:
        for prop, value in record.properties.items():
            reasons: list[str] = []
            level = "low"
            if not value.evidence_id:
                reasons.append("missing_evidence_id")
                level = "high"
            elif evidence_index and value.evidence_id not in evidence_index:
                reasons.append("evidence_not_resolved")
                level = "high"
            if value.comparator in {"eq", "min", "max"} and value.value is None:
                reasons.append("numeric_value_missing")
                level = "high"
            if value.comparator == "range" and (value.lower is None or value.upper is None):
                reasons.append("range_bound_missing")
                level = "high"
            if (
                value.comparator in {"min", "max", "range"}
                and level == "low"
                and prop in REVIEW_MEDIUM_PROPERTIES
            ):
                reasons.append("comparator_condition")
                level = "medium"
            if (
                value.value is not None
                and not value.unit
                and prop not in {"A", "Z"}
                and level == "low"
            ):
                reasons.append("unit_missing")
                level = "medium"
            risks.append(
                FieldRisk(
                    field_path=f"records.{record.record_id}.properties.{prop}",
                    record_id=record.record_id,
                    property=prop,
                    level=level,
                    reasons=reasons,
                    evidence_id=value.evidence_id or None,
                    page_no=(
                        evidence_index[value.evidence_id].page_no
                        if value.evidence_id in evidence_index
                        else None
                    ),
                )
            )
    risks.sort(key=lambda item: (LEVEL_ORDER[item.level], item.field_path))
    return risks


def document_risk_level(risks: list[FieldRisk]) -> str:
    if any(item.level == "high" for item in risks):
        return "high"
    if any(item.level == "medium" for item in risks):
        return "medium"
    return "low"


def risk_summary(
    result: DocumentResult, evidence: list[Evidence] | None = None
) -> dict:
    risks = field_risks(result, evidence)
    counts = {"high": 0, "medium": 0, "low": 0}
    for item in risks:
        counts[item.level] += 1
    return {
        "doc_id": result.document.doc_id,
        "level": document_risk_level(risks),
        "counts": counts,
        "high_risk_fields": [
            item.to_dict() for item in risks if item.level == "high"
        ],
        "fields": [item.to_dict() for item in risks],
    }


def coverage_of_high_risk(
    risks: list[FieldRisk], reviewed_paths: set[str]
) -> dict:
    high = [item for item in risks if item.level == "high"]
    if not high:
        return {"high_fields": 0, "reviewed": 0, "rate": 1.0}
    reviewed = sum(1 for item in high if item.field_path in reviewed_paths)
    return {
        "high_fields": len(high),
        "reviewed": reviewed,
        "rate": round(reviewed / len(high), 4),
    }
