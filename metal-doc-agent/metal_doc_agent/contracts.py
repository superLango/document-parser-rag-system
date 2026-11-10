"""Pydantic contracts shared by every pipeline stage.

The contracts are deliberately explicit: artifacts are versioned, evidence is
mandatory for extracted values, and missing values are represented as status
instead of guessed numbers.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from . import __version__ as PACKAGE_VERSION

SCHEMA_VERSION = "0.1.0"


class Contract(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class Artifact(Contract):
    """Version header shared by persisted artifacts.

    ``created_at`` is stamped by the run manifest until object storage lands in
    M1-02; see docs/schemas.md for the v0 artifact envelope rules.
    """

    schema_version: str = SCHEMA_VERSION
    producer_version: str = PACKAGE_VERSION


class DocumentMeta(Contract):
    doc_id: str
    source_path: str
    file_name: str
    standard_no: str | None = None
    title: str | None = None
    version: str | None = None
    page_count: int = 0
    sha256: str | None = None


class DocumentProfile(Contract):
    doc_id: str
    doc_type: Literal[
        "gb_t", "gjb", "enterprise", "agreement", "classification", "other"
    ] = "other"
    material_family: str | None = None
    product_form: str | None = None
    has_toc: bool | None = None
    table_count: int = 0
    table_profiles: list[str] = Field(default_factory=list)
    coverage_template: str | None = None
    notes: list[str] = Field(default_factory=list)


class Page(Contract):
    page_no: int
    markdown: str
    image_path: str | None = None
    layout_path: str | None = None


class Merge(Contract):
    row: int
    col: int
    rowspan: int = 1
    colspan: int = 1
    text: str = ""
    is_header: bool = False


class TableBlock(Contract):
    block_id: str
    start_row: int
    header_rows: int
    header_paths: list[list[str]] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)


class TableGrid(Artifact):
    table_id: str
    page_no: int
    caption: str | None = None
    context: str | None = None
    n_rows: int = 0
    n_cols: int = 0
    header_rows: int = 1
    rows: list[list[str]] = Field(default_factory=list)
    header_paths: list[list[str]] = Field(default_factory=list)
    merges: list[Merge] = Field(default_factory=list)
    units: list[str] = Field(default_factory=list)
    footnotes: list[str] = Field(default_factory=list)
    profile: str = "unknown"
    orientation: str = "grade_rows"
    blocks: list[TableBlock] = Field(default_factory=list)
    raw_html: str = ""
    continuation_of: str | None = None
    merged_pages: list[int] = Field(default_factory=list)


class TableIRCell(Contract):
    """Semantic cell of the unified table IR (P6-B).

    The grid itself stays in :class:`TableGrid`; this contract adds the
    per-cell facts extraction needs — what the column means, what the value
    type is, and which evidence id the value would carry. Empty cells are not
    persisted: a missing ``(row, col)`` is an empty cell.
    """

    row: int
    col: int
    text: str
    raw_role: Literal["header", "data", "footnote"] = "data"
    role: Literal[
        "header",
        "row_key",
        "row_index",
        "condition",
        "measure",
        "method",
        "remark",
        "footnote",
        "unknown",
    ] = "unknown"
    header_path: list[str] = Field(default_factory=list)
    property: str | None = None
    unit: str | None = None
    value_type: Literal[
        "number", "range", "text", "placeholder", "na", "unknown"
    ] = "unknown"
    comparator: Literal[
        "eq", "min", "max", "range", "text", "na", "unknown"
    ] = "unknown"
    rowspan: int = 1
    colspan: int = 1
    evidence_id: str = ""


class TableIRBlock(Contract):
    block_id: str
    start_row: int
    header_rows: int = 1
    header_paths: list[list[str]] = Field(default_factory=list)


class TableIR(Artifact):
    """Document-independent semantic view of one :class:`TableGrid`."""

    table_id: str
    page_no: int
    caption: str | None = None
    profile: str = "unknown"
    orientation: str = "grade_rows"
    header_rows: int = 1
    n_rows: int = 0
    n_cols: int = 0
    header_paths: list[list[str]] = Field(default_factory=list)
    cells: list[TableIRCell] = Field(default_factory=list)
    blocks: list[TableIRBlock] = Field(default_factory=list)
    units: list[str] = Field(default_factory=list)
    footnotes: list[str] = Field(default_factory=list)
    continuation_of: str | None = None
    merged_pages: list[int] = Field(default_factory=list)


class TableIRBundle(Artifact):
    doc_id: str
    tables: list[TableIR] = Field(default_factory=list)


class OutlineNode(Contract):
    node_id: str
    kind: Literal["document", "clause", "table", "figure", "appendix", "page"]
    title: str
    clause_id: str | None = None
    page_no: int | None = None
    level: int = 0
    parent_id: str | None = None
    normative: bool = True


class OutlineGraph(Artifact):
    doc_id: str
    nodes: list[OutlineNode] = Field(default_factory=list)


class Evidence(Contract):
    evidence_id: str
    page_no: int
    table_id: str | None = None
    row: int | None = None
    col: int | None = None
    quote: str = ""
    bbox: list[float] | None = None
    artifact_uri: str | None = None


class ExtractedValue(Contract):
    raw: str
    value: float | None = None
    text: str | None = None
    unit: str | None = None
    comparator: Literal["eq", "min", "max", "range", "text", "na"] = "eq"
    lower: float | None = None
    upper: float | None = None
    condition: str | None = None
    evidence_id: str = ""


class Record(Contract):
    record_id: str
    source_table_id: str | None = None
    grade: str | None = None
    grade_level: str | None = None
    condition: str | None = None
    facets: dict[str, str] = Field(default_factory=dict)
    properties: dict[str, ExtractedValue] = Field(default_factory=dict)


class ClauseRecord(Contract):
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
    fields: dict[str, ExtractedValue] = Field(default_factory=dict)
    applies_to: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    status: Literal["found", "missing", "ambiguous", "not_applicable"] = "found"


class InspectionItem(Contract):
    item: str
    category: str | None = None
    quantities: dict[str, str] = Field(default_factory=dict)
    sample_location: str | None = None
    condition: str | None = None
    requirement: str | None = None
    requirement_clause: str | None = None
    method_clause: str | None = None
    method_standard: str | None = None
    status: Literal["found", "ambiguous", "not_applicable"] = "found"
    evidence_id: str | None = None
    note: str | None = None


class ClassificationItem(Contract):
    grade: str
    old_grade: str | None = None
    state: str | None = None
    old_state: str | None = None
    meaning: str | None = None
    status: Literal["found", "ambiguous", "not_applicable"] = "found"
    evidence_id: str | None = None


class ReferenceEdge(Contract):
    raw: str
    standard_no: str | None = None
    title: str | None = None
    edition: str | None = None
    dated: bool = False
    relation: Literal["normative", "informative", "table_note", "clause", "other"] = "normative"
    clause_id: str | None = None
    page_no: int | None = None
    resolved: bool = False
    resolved_doc_id: str | None = None
    resolution_basis: str | None = None
    status: Literal["current", "superseded", "conflict", "unknown"] | None = None
    superseded_by: str | None = None
    relevance: Literal["schema", "method", "informative", "unknown"] | None = None
    expand: bool = False
    selection_reason: str | None = None


class ReferenceGraph(Artifact):
    doc_id: str
    references: list[ReferenceEdge] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    budget: dict[str, Any] = Field(default_factory=dict)


class CrossStandardTask(Contract):
    task_id: str
    doc_id: str
    inspection_item: str | None = None
    missing_fields: list[str] = Field(default_factory=list)
    requirement_standard: str
    requirement_edition: str | None = None
    method_standard: str | None = None
    clause_id: str | None = None
    page_no: int | None = None
    quote: str | None = None
    optional: bool = False
    status: Literal[
        "needed", "resolved", "candidate", "needs_source", "not_found", "ignored"
    ] = "needed"
    resolution_basis: str | None = None
    resolved_doc_id: str | None = None
    resolved_source_file: str | None = None
    resolved_pages: int | None = None
    gap: str | None = None
    expansion: dict | None = None
    merge: dict | None = None
    provenance: list[dict] = Field(default_factory=list)
    error: str | None = None


class RecipeSignature(Contract):
    profile: str = "unknown"
    orientation: str = "grade_rows"
    n_cols: int = 0
    blocks: int = 0
    tokens: list[str] = Field(default_factory=list)
    multi_header: bool = False
    unit_set: list[str] = Field(default_factory=list)


class Recipe(Artifact):
    recipe_id: str
    version: int = 1
    status: Literal["active", "candidate", "retired"] = "active"
    profile: str = "unknown"
    signature: RecipeSignature = Field(default_factory=RecipeSignature)
    bindings: dict = Field(default_factory=dict)
    rules: dict = Field(default_factory=dict)
    coverage_template: str | None = None
    business_dictionary: str | None = None


class ColumnBinding(Contract):
    column: int
    header_path: list[str] = Field(default_factory=list)
    item_family: str = "unknown"
    item_raw: str | None = None
    property: str | None = None
    role: Literal[
        "row_key", "row_index", "condition", "measure", "method", "remark", "unknown"
    ] = "unknown"
    unit: str | None = None
    facets: dict[str, str] = Field(default_factory=dict)
    confidence: float = 0.0
    status: Literal["bound", "conflict", "ambiguous", "unmapped"] = "unmapped"
    reason: str | None = None
    evidence: dict = Field(default_factory=dict)


class ItemGroup(Contract):
    group_id: str
    item_family: str
    item_raw: str | None = None
    columns: list[int] = Field(default_factory=list)
    facets: dict[str, str] = Field(default_factory=dict)
    status: str = "bound"


class ColumnBindingResult(Artifact):
    table_id: str
    recipe_id: str | None = None
    match_status: Literal["exact", "candidate", "unknown"] = "unknown"
    bindings: list[ColumnBinding] = Field(default_factory=list)
    item_groups: list[ItemGroup] = Field(default_factory=list)
    conflicts: list[dict] = Field(default_factory=list)
    ambiguous: list[dict] = Field(default_factory=list)
    unmapped_columns: list[int] = Field(default_factory=list)


class PropertyMatch(Contract):
    """Match of one detected property against a business 检测项目."""

    raw: str
    canonical_id: str | None = None
    canonical_name: str | None = None
    match_type: Literal[
        "exact", "alias", "semantic", "edit_distance", "new", "ambiguous"
    ] = "new"
    score: float = 0.0
    category_code: str | None = None
    category_name: str | None = None
    dictionary_version: str = ""
    status: Literal["matched", "new", "ambiguous"] = "new"
    reason: str | None = None


class ItemInventoryEntry(Contract):
    item_raw: str
    item_canonical: str | None = None
    item_family: str = "unknown"
    facets: dict[str, str] = Field(default_factory=dict)
    properties: list[str] = Field(default_factory=list)
    method_standard: str | None = None
    source: Literal[
        "inspection_table", "property_table", "clause", "reference", "manual"
    ] = "clause"
    clause_id: str | None = None
    page_no: int | None = None
    table_id: str | None = None
    evidence: list[str] = Field(default_factory=list)
    status: Literal[
        "confirmed", "probable", "new", "ambiguous", "not_applicable"
    ] = "probable"
    business_code: str | None = None
    business_name: str | None = None
    match_type: str | None = None
    match_score: float | None = None
    business_category_code: str | None = None
    business_category_name: str | None = None
    category_match_type: str | None = None
    property_matches: list[PropertyMatch] = Field(default_factory=list)
    method_code: str | None = None
    method_name: str | None = None
    method_match_type: str | None = None
    dictionary_version: str | None = None


class ItemInventory(Artifact):
    doc_id: str
    items: list[ItemInventoryEntry] = Field(default_factory=list)
    unknown_candidates: list[dict] = Field(default_factory=list)
    not_applicable: list[dict] = Field(default_factory=list)
    coverage: dict = Field(default_factory=dict)
    recipe_ids: list[str] = Field(default_factory=list)


class ExtractionField(Contract):
    name: str
    canonical_name: str
    required: bool = True
    source: Literal["table", "clause", "both"] = "both"
    profiles: list[str] = Field(default_factory=list)
    note: str | None = None


class ExtractionPlan(Artifact):
    template: str = "product_full"
    fields: list[ExtractionField] = Field(default_factory=list)


class CoverageItem(Contract):
    field: str
    required: bool = True
    status: Literal["found", "missing", "ambiguous", "not_applicable"] = "missing"
    expected_locations: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    reason: str | None = None


class CoveragePlan(Artifact):
    standard_no: str | None = None
    template: str = "product_full"
    items: list[CoverageItem] = Field(default_factory=list)


class TableClauseLink(Contract):
    table_id: str
    clause_id: str | None = None
    clause_title: str | None = None
    page_no: int | None = None
    basis: Literal[
        "explicit", "caption", "section", "nearest", "continuation", "none"
    ] = "none"
    confidence: float = 0.0
    evidence: str | None = None


class TableLinkResult(Artifact):
    doc_id: str
    links: list[TableClauseLink] = Field(default_factory=list)
    orphans: list[dict] = Field(default_factory=list)
    coverage: dict = Field(default_factory=dict)


class CoverageAudit(Artifact):
    doc_id: str
    status: Literal["pass", "review", "fail"] = "review"
    items: list[CoverageItem] = Field(default_factory=list)
    gaps: list[dict] = Field(default_factory=list)
    stats: dict = Field(default_factory=dict)


class BusinessDictionaryEntry(Contract):
    business_code: str
    business_name: str
    type: Literal["category", "item", "method"] = "item"
    family: str | None = None
    facets: dict[str, list[str]] = Field(default_factory=dict)
    aliases: list[str] = Field(default_factory=list)
    standard_no: str | None = None
    category_code: str | None = None
    category_name: str | None = None
    status: Literal["active", "inactive", "pending"] = "active"
    version: str | None = None


class BusinessDictionary(Artifact):
    version: str
    source: Literal["json", "api", "db", "offline_snapshot"] = "json"
    entries: list[BusinessDictionaryEntry] = Field(default_factory=list)


class CanonicalMatch(Contract):
    raw: str
    canonical_id: str | None = None
    canonical_name: str | None = None
    match_type: Literal[
        "exact",
        "alias",
        "granularity",
        "semantic",
        "edit_distance",
        "new",
        "ambiguous",
    ] = "new"
    score: float = 0.0
    dictionary_version: str = ""
    evidence: list[str] = Field(default_factory=list)
    status: Literal["matched", "new", "ambiguous"] = "new"
    reason: str | None = None
    category_code: str | None = None
    category_name: str | None = None


class NewTerm(Contract):
    type: Literal["category", "item", "method"] = "item"
    raw: str
    family: str | None = None
    facets: dict[str, str] = Field(default_factory=dict)
    suggested_code: str | None = None
    reason: str = ""
    evidence: list[str] = Field(default_factory=list)
    frequency: int = 1
    status: Literal["pending", "active", "rejected"] = "pending"
    dictionary_version: str | None = None


class AlignmentResult(Artifact):
    doc_id: str
    dictionary_version: str
    item_matches: list[CanonicalMatch] = Field(default_factory=list)
    property_matches: list[PropertyMatch] = Field(default_factory=list)
    method_matches: list[CanonicalMatch] = Field(default_factory=list)
    new_terms: list[NewTerm] = Field(default_factory=list)
    summary: dict = Field(default_factory=dict)


class NewTermStore(Artifact):
    dictionary_version: str = ""
    terms: list[NewTerm] = Field(default_factory=list)


class ValidationIssue(Contract):
    level: Literal["L0", "L1", "L2", "L3", "L3.5", "L4", "L5"]
    code: str
    message: str
    record_id: str | None = None
    field: str | None = None
    evidence_id: str | None = None
    severity: Literal["info", "warn", "error"] = "warn"


class AuditReport(Artifact):
    doc_id: str
    status: Literal["pass", "review", "fail"] = "review"
    issues: list[ValidationIssue] = Field(default_factory=list)
    coverage: CoveragePlan | None = None
    stats: dict[str, Any] = Field(default_factory=dict)


class DocumentResult(Artifact):
    document: DocumentMeta
    profile: DocumentProfile | None = None
    tables: list[TableGrid] = Field(default_factory=list)
    records: list[Record] = Field(default_factory=list)
    inspection_items: list[InspectionItem] = Field(default_factory=list)
    classification_items: list[ClassificationItem] = Field(default_factory=list)
    clauses: list[ClauseRecord] = Field(default_factory=list)
    references: ReferenceGraph | None = None
    coverage: CoveragePlan | None = None
    quality: AuditReport | None = None
    artifacts: dict[str, str] = Field(default_factory=dict)


class ArtifactEntry(Contract):
    path: str
    role: str
    content_type: str = "application/json"
    size: int = 0
    sha256: str
    required: bool = True


class ArtifactManifest(Artifact):
    job_id: str
    doc_id: str
    created_at: str
    artifacts: list[ArtifactEntry] = Field(default_factory=list)


class JobState(Contract):
    job_id: str
    lane: Literal["production", "explore", "human"] = "production"
    status: Literal["queued", "running", "succeeded", "failed", "review"] = "queued"
    stage: str = "created"
    doc_path: str
    out_dir: str
    error: str | None = None
    failure_code: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    finished_at: str | None = None
    idempotency_key: str | None = None
    source_name: str | None = None
    source_sha256: str | None = None
    options: dict[str, str] = Field(default_factory=dict)
    progress: int = 0
    attempts: int = 0
    result_status: str | None = None
    artifact_manifest: str | None = None
    summary: dict[str, int] = Field(default_factory=dict)
