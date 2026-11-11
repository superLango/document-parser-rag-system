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
    "promoted",
    "discarded",
    "needs_more_info",
]
RootCause = Literal[
    "ocr_error",
    "table_structure",
    "recipe_binding",
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


class RepairProposal(BaseModel):
    proposal_id: str = ""
    root_cause: RootCause = "unknown"
    scope: RepairScope = "none"
    summary: str = ""
    patch: dict[str, Any] = Field(default_factory=dict)
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


class PromotionRecord(BaseModel):
    id: str
    feedback_id: str
    recipe_id: str
    from_version: str
    to_version: str
    channel: str
    action: Literal["promote", "discard", "rollback"]
    actor: str
    note: str = ""
    created_at: str = ""
