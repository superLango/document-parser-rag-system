"""Golden set models, loading and validation.

The golden set is human-owned truth: labels must be transcribed from the source
standard, never copied from a model or parser output. The models here mirror the
runtime contracts closely enough to score predictions, while keeping the
annotation format explicit and reviewable.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from .contracts import SCHEMA_VERSION, Contract

DOC_TYPES = ("gb_t", "gjb", "enterprise", "agreement", "classification", "other")
SOURCE_TYPES = ("digital_native", "scanned", "hybrid", "unknown")
TABLE_PROFILES = (
    "chemical_composition",
    "mechanical_properties",
    "inspection",
    "classification",
    "dimension",
    "unknown",
)
COMPARATORS = ("eq", "min", "max", "range", "text", "na")
SPLITS = ("mini", "dev", "heldout")


class GoldEvidence(Contract):
    page_no: int
    table_id: str | None = None
    row: int | None = None
    col: int | None = None
    clause_id: str | None = None
    quote: str


class GoldValue(Contract):
    raw: str
    value: float | None = None
    text: str | None = None
    unit: str | None = None
    comparator: Literal["eq", "min", "max", "range", "text", "na"] = "eq"
    lower: float | None = None
    upper: float | None = None
    condition: str | None = None
    evidence: GoldEvidence


class GoldRecord(Contract):
    record_id: str
    grade: str | None = None
    grade_level: str | None = None
    condition: str | None = None
    facets: dict[str, str] = Field(default_factory=dict)
    properties: dict[str, GoldValue] = Field(default_factory=dict)
    note: str | None = None


class GoldInspectionItem(Contract):
    item: str
    category: str | None = None
    quantities: dict[str, str] = Field(default_factory=dict)
    sample_location: str | None = None
    requirement_clause: str | None = None
    method_clause: str | None = None
    method_standard: str | None = None
    status: Literal["found", "ambiguous", "not_applicable"] = "found"
    evidence: GoldEvidence
    note: str | None = None


class GoldClassificationItem(Contract):
    grade: str
    old_grade: str | None = None
    state: str | None = None
    old_state: str | None = None
    meaning: str | None = None
    status: Literal["found", "ambiguous", "not_applicable"] = "found"
    evidence: GoldEvidence
    note: str | None = None


class GoldTable(Contract):
    table_id: str
    page_no: int | None = None
    caption: str | None = None
    profile: str
    orientation: str = "grade_rows"
    scope: Literal["full", "partial"] = "full"
    note: str | None = None
    records: list[GoldRecord] = Field(default_factory=list)
    inspection_items: list[GoldInspectionItem] = Field(default_factory=list)
    classification_items: list[GoldClassificationItem] = Field(default_factory=list)


class GoldClause(Contract):
    clause_id: str
    title: str | None = None
    page_no: int | None = None
    kind: Literal[
        "scope",
        "normative_reference",
        "terms",
        "technical_requirement",
        "inspection",
        "sampling",
        "test_method",
        "delivery",
        "packaging",
        "other",
    ] = "other"
    status: Literal["found", "missing", "ambiguous", "not_applicable"] = "found"
    fields: dict[str, GoldValue] = Field(default_factory=dict)
    applies_to: list[str] = Field(default_factory=list)
    evidence: GoldEvidence | None = None
    note: str | None = None


class AnnotationMeta(Contract):
    status: Literal["draft", "reviewed", "verified"] = "draft"
    annotator: str = "unassigned"
    reviewers: list[str] = Field(default_factory=list)
    updated_at: str | None = None
    notes: list[str] = Field(default_factory=list)


class GoldDocument(Contract):
    schema_version: str = SCHEMA_VERSION
    doc_id: str
    standard_no: str | None = None
    title: str | None = None
    doc_type: Literal[
        "gb_t", "gjb", "enterprise", "agreement", "classification", "other"
    ] = "other"
    material: str | None = None
    product_form: str | None = None
    source_type: Literal["digital_native", "scanned", "hybrid", "unknown"] = "unknown"
    annotation: AnnotationMeta = Field(default_factory=AnnotationMeta)
    tables: list[GoldTable] = Field(default_factory=list)
    clauses: list[GoldClause] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class GoldDocEntry(Contract):
    doc_id: str
    standard_no: str | None = None
    title: str | None = None
    doc_type: Literal[
        "gb_t", "gjb", "enterprise", "agreement", "classification", "other"
    ] = "other"
    source_type: Literal["digital_native", "scanned", "hybrid", "unknown"] = "unknown"
    material: str | None = None
    product_form: str | None = None
    md_path: str
    pdf_path: str | None = None
    pages: int = 0
    tables: int = 0
    profiles: list[str] = Field(default_factory=list)
    split: Literal["mini", "dev", "heldout"] = "dev"
    priority: int = 2
    annotation_status: Literal["selected", "annotated"] = "selected"
    annotation_file: str | None = None
    notes: str | None = None


class GoldManifest(Contract):
    schema_version: str = SCHEMA_VERSION
    goldset_version: str = "v0"
    created_at: str | None = None
    corpus_root: str = "../标准文件"
    requirements: dict[str, Any] = Field(default_factory=dict)
    documents: list[GoldDocEntry] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


def load_gold_document(path: str | Path) -> GoldDocument:
    return GoldDocument.model_validate(
        json.loads(Path(path).read_text(encoding="utf-8"))
    )


def load_manifest(path: str | Path) -> GoldManifest:
    return GoldManifest.model_validate(
        json.loads(Path(path).read_text(encoding="utf-8"))
    )


def validate_gold_document(gold: GoldDocument) -> list[str]:
    issues: list[str] = []
    if not gold.tables and not gold.clauses:
        issues.append(f"{gold.doc_id}: document has neither tables nor clauses")

    seen_tables: set[str] = set()
    seen_records: set[str] = set()
    for table in gold.tables:
        prefix = f"{gold.doc_id}/{table.table_id}"
        if table.table_id in seen_tables:
            issues.append(f"{prefix}: duplicate table_id")
        seen_tables.add(table.table_id)
        if table.profile not in TABLE_PROFILES:
            issues.append(f"{prefix}: unknown profile {table.profile}")
        if table.profile in {"chemical_composition", "mechanical_properties"}:
            if not table.records:
                issues.append(f"{prefix}: profile {table.profile} has no records")
        if table.profile == "inspection" and not table.inspection_items:
            issues.append(f"{prefix}: inspection table has no inspection_items")
        if table.profile == "classification" and not (
            table.classification_items or table.records
        ):
            issues.append(f"{prefix}: classification table has no items")

        for record in table.records:
            if record.record_id in seen_records:
                issues.append(f"{prefix}: duplicate record_id {record.record_id}")
            seen_records.add(record.record_id)
            if not record.properties:
                issues.append(f"{prefix}/{record.record_id}: empty properties")
            for key, value in record.properties.items():
                issues.extend(_validate_value(f"{prefix}/{record.record_id}/{key}", value))
        for item in table.inspection_items:
            issues.extend(_validate_evidence(f"{prefix}/{item.item}", item.evidence))
        for item in table.classification_items:
            issues.extend(_validate_evidence(f"{prefix}/{item.grade}", item.evidence))

    seen_clauses: set[str] = set()
    for clause in gold.clauses:
        prefix = f"{gold.doc_id}/{clause.clause_id}"
        if clause.clause_id in seen_clauses:
            issues.append(f"{prefix}: duplicate clause_id")
        seen_clauses.add(clause.clause_id)
        for key, value in clause.fields.items():
            issues.extend(_validate_value(f"{prefix}/{key}", value))
        if clause.evidence:
            issues.extend(_validate_evidence(prefix, clause.evidence))
    return issues


def _validate_value(prefix: str, value: GoldValue) -> list[str]:
    issues = _validate_evidence(prefix, value.evidence)
    if value.comparator == "range":
        if value.lower is None or value.upper is None:
            issues.append(f"{prefix}: range needs lower and upper")
        elif value.lower > value.upper:
            issues.append(f"{prefix}: lower > upper")
    elif value.comparator in {"min", "max"} and value.value is None:
        issues.append(f"{prefix}: {value.comparator} needs numeric value")
    elif value.comparator == "text" and not (value.text or value.raw):
        issues.append(f"{prefix}: text comparator needs text")
    if value.comparator == "na" and value.value is not None:
        issues.append(f"{prefix}: na must not carry a value")
    return issues


def _validate_evidence(prefix: str, evidence: GoldEvidence) -> list[str]:
    issues: list[str] = []
    if evidence.page_no < 1:
        issues.append(f"{prefix}: evidence page_no must be >= 1")
    if not evidence.quote.strip():
        issues.append(f"{prefix}: evidence quote is empty")
    return issues


def validate_manifest(
    manifest: GoldManifest,
    goldset_dir: str | Path,
    strict_requirements: bool = False,
) -> list[str]:
    issues: list[str] = []
    base = Path(goldset_dir)
    corpus_base = (base / manifest.corpus_root).resolve()
    seen: set[str] = set()
    for entry in manifest.documents:
        if entry.doc_id in seen:
            issues.append(f"duplicate doc_id {entry.doc_id}")
        seen.add(entry.doc_id)
        if entry.md_path and not (corpus_base / entry.md_path).exists():
            issues.append(f"{entry.doc_id}: md_path not found: {entry.md_path}")
        if entry.pdf_path and not (corpus_base / entry.pdf_path).exists():
            issues.append(f"{entry.doc_id}: pdf_path not found: {entry.pdf_path}")
        if entry.annotation_file:
            annotation_path = base / entry.annotation_file
            if not annotation_path.exists():
                issues.append(f"{entry.doc_id}: annotation_file not found")
                continue
            gold = load_gold_document(annotation_path)
            if gold.doc_id != entry.doc_id:
                issues.append(
                    f"{entry.doc_id}: annotation doc_id mismatch {gold.doc_id}"
                )
            issues.extend(validate_gold_document(gold))

    if strict_requirements:
        issues.extend(_check_requirements(manifest))
    return issues


def _check_requirements(manifest: GoldManifest) -> list[str]:
    issues: list[str] = []
    requirements = manifest.requirements or {}
    counts: dict[str, int] = {"documents": len(manifest.documents)}
    for source_type in ("digital_native", "scanned", "hybrid"):
        counts[source_type] = sum(
            1 for entry in manifest.documents if entry.source_type == source_type
        )
    counts["doc_types"] = len({entry.doc_type for entry in manifest.documents})
    profiles = {profile for entry in manifest.documents for profile in entry.profiles}
    counts["table_profiles"] = len(profiles)
    counts["annotated"] = sum(
        1 for entry in manifest.documents if entry.annotation_status == "annotated"
    )

    for key, target in requirements.items():
        if not isinstance(target, int):
            continue
        actual = counts.get(key, 0)
        if actual < target:
            issues.append(
                f"requirement {key}: {actual} < {target} (goldset v0 gap)"
            )
    return issues


def goldset_summary(manifest: GoldManifest) -> dict[str, Any]:
    by_type: dict[str, int] = {}
    by_source: dict[str, int] = {}
    by_profile: dict[str, int] = {}
    by_split: dict[str, int] = {}
    for entry in manifest.documents:
        by_type[entry.doc_type] = by_type.get(entry.doc_type, 0) + 1
        by_source[entry.source_type] = by_source.get(entry.source_type, 0) + 1
        by_split[entry.split] = by_split.get(entry.split, 0) + 1
        for profile in entry.profiles:
            by_profile[profile] = by_profile.get(profile, 0) + 1
    return {
        "documents": len(manifest.documents),
        "annotated": sum(
            1 for entry in manifest.documents if entry.annotation_status == "annotated"
        ),
        "by_doc_type": by_type,
        "by_source_type": by_source,
        "by_profile": by_profile,
        "by_split": by_split,
    }
