"""Feedback, triage, repair, verification and promotion contracts."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

FeedbackStatus = Literal[
    "open",
    "processing",
    "proposed",
    "verifying",
    "verified",
    "applied",
    "shadow",
    "promoted",
    "discarded",
    "needs_more_info",
]
RootCause = Literal[
    "ocr_error",
    "table_structure",
    "recipe_binding",
    "extraction_rule",
    "value_parsing",
    "template_schema",
    "model_extraction",
    "dictionary",
    "display",
    "unknown",
]
RepairScope = Literal["data", "recipe", "template", "prompt", "engine", "display", "none"]


class FeedbackCreate(BaseModel):
    run_id: str
    category: str
    target: dict[str, Any] = Field(default_factory=dict)
    description: str
    expected_value: str | None = None
    source_quote: str | None = None
    reporter: str = "operator"


class FeedbackMessage(BaseModel):
    role: Literal["user", "agent", "system"]
    content: str
    at: str


class TriageDecision(BaseModel):
    root_cause: RootCause = "unknown"
    repair_scope: RepairScope = "none"
    confidence: float = Field(default=0.5, ge=0, le=1)
    evidence: list[str] = Field(default_factory=list)
    summary: str = ""
    needs_human: bool = False


class CodeFile(BaseModel):
    path: str
    content: str
    status: Literal["added", "modified"] = "modified"
    diff: str = ""


class CodePatch(BaseModel):
    base_version: str = ""
    files: list[CodeFile] = Field(default_factory=list)


class CodeGuardViolation(BaseModel):
    code: str
    message: str
    file: str = ""
    line: int = 0


class CodeGuardReport(BaseModel):
    passed: bool = False
    violations: list[CodeGuardViolation] = Field(default_factory=list)
    stats: dict[str, Any] = Field(default_factory=dict)


class RepairProposal(BaseModel):
    proposal_id: str = ""
    root_cause: RootCause = "unknown"
    scope: RepairScope = "none"
    summary: str = ""
    patch: dict[str, Any] = Field(default_factory=dict)
    code_patch: CodePatch | None = None
    guard: CodeGuardReport | None = None
    test_plan: list[str] = Field(default_factory=list)
    risk: Literal["low", "medium", "high"] = "low"
    needs_human: bool = False
    confidence: float = Field(default=0.5, ge=0, le=1)


class CandidateRef(BaseModel):
    recipe_id: str
    base_version: str
    candidate_version: str
    digest: str
    patch: dict[str, Any] = Field(default_factory=dict)
    patch_chain: list[str] = Field(default_factory=list)


class VerificationDiff(BaseModel):
    added: list[dict[str, Any]] = Field(default_factory=list)
    removed: list[dict[str, Any]] = Field(default_factory=list)
    changed: list[dict[str, Any]] = Field(default_factory=list)


class RegressionStats(BaseModel):
    documents: int = 0
    field_f1_delta: float = 0.0
    new_errors: int = 0


class VerificationPackage(BaseModel):
    proposal_id: str
    before_run: str
    after_run: str = ""
    diff: VerificationDiff = Field(default_factory=VerificationDiff)
    regression: RegressionStats = Field(default_factory=RegressionStats)
    affected_targets: list[dict[str, Any]] = Field(default_factory=list)
    user_summary: str = ""
    artifacts: list[str] = Field(default_factory=list)
    passed: bool = False
    record_count: int = 0
    records_digest: str = ""
    accepted_tables: list[str] = Field(default_factory=list)
    accepted_fields: list[str] = Field(default_factory=list)
    field_digests: dict[str, str] = Field(default_factory=dict)
    changed_in_accepted: list[dict[str, Any]] = Field(default_factory=list)
    requires_confirmation: bool = False
    checks: list[dict[str, Any]] = Field(default_factory=list)
    decision: str = ""
    action_tier: str = ""
    coverage_before: dict[str, Any] = Field(default_factory=dict)
    coverage_after: dict[str, Any] = Field(default_factory=dict)
    after_diagnostics: dict[str, Any] = Field(default_factory=dict)


class AcceptedSnapshot(BaseModel):
    document_id: str
    document_version: int = 1
    run_id: str
    feedback_id: str | None = None
    records: int = 0
    records_digest: str = ""
    accepted_tables: list[str] = Field(default_factory=list)
    accepted_fields: list[str] = Field(default_factory=list)
    field_digests: dict[str, str] = Field(default_factory=dict)
    actor: str = "operator"
    created_at: str = ""


class FeedbackDetail(BaseModel):
    id: str
    run_id: str
    document_id: str
    category: str
    target: dict[str, Any] = Field(default_factory=dict)
    description: str
    expected_value: str | None = None
    source_quote: str | None = None
    status: FeedbackStatus = "open"
    messages: list[FeedbackMessage] = Field(default_factory=list)
    root_cause: dict[str, Any] = Field(default_factory=dict)
    suggestions: list[dict[str, Any]] = Field(default_factory=list)
    triage: TriageDecision | None = None
    proposal: RepairProposal | None = None
    candidate: CandidateRef | None = None
    verification: VerificationPackage | None = None
    created_at: str = ""
    updated_at: str = ""
    resolved_at: str | None = None


class FeedbackVerifyIn(BaseModel):
    decision: Literal["approve", "reject"]
    reason: str = ""
    actor: str
    confirm_accepted_change: bool = False


class CodeApprovalIn(BaseModel):
    """Human approval for an L3 engine proposal before bundle publish."""

    actor: str
    reason: str = ""
    confirm: bool = False
    verification_id: str = ""


class PromotionRecord(BaseModel):
    id: str
    feedback_id: str | None = None
    recipe_id: str
    from_version: str
    to_version: str
    channel: str
    action: Literal["promote", "discard", "rollback"]
    actor: str
    note: str = ""
    created_at: str = ""
