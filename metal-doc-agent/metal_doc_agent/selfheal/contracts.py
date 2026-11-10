"""Data contracts for the self-heal route.

The models intentionally mirror the plan document section 4 so the API, storage
and repair pipeline share one vocabulary. They are self-contained: nothing here
imports or mutates the production extraction contracts.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:16]}"


class FeedbackCategory(str, Enum):
    wrong_value = "wrong_value"
    missing_value = "missing_value"
    extra_value = "extra_value"
    wrong_unit = "wrong_unit"
    wrong_requirement = "wrong_requirement"
    wrong_table = "wrong_table"
    duplicate = "duplicate"
    other = "other"


class FeedbackStatus(str, Enum):
    open = "open"
    processing = "processing"
    fixed = "fixed"
    rejected = "rejected"
    needs_more_info = "needs_more_info"


class FindingSource(str, Enum):
    audit = "audit"
    user = "user"


class FindingVerdict(str, Enum):
    correct = "correct"
    wrong = "wrong"
    missing = "missing"
    extra = "extra"
    ambiguous = "ambiguous"
    unverifiable = "unverifiable"


class FindingStatus(str, Enum):
    open = "open"
    accepted = "accepted"
    rejected = "rejected"
    fixed = "fixed"
    quarantined = "quarantined"


class RepairLevel(str, Enum):
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"


class ProposalStatus(str, Enum):
    proposed = "proposed"
    sandbox = "sandbox"
    verified = "verified"
    applied = "applied"
    rolled_back = "rolled_back"
    rejected = "rejected"
    propose_only = "propose_only"


class GateDecision(str, Enum):
    accept = "accept"
    rollback = "rollback"
    propose_only = "propose_only"


class CandidateStatus(str, Enum):
    local = "local"
    shadow = "shadow"
    canary = "canary"
    global_ = "global"
    rejected = "rejected"


class FeedbackTarget(BaseModel):
    feature: str | None = None
    record_id: str | None = None
    property: str | None = None
    table_id: str | None = None
    page_no: int | None = None
    row: int | None = None
    col: int | None = None
    grade: str | None = None
    condition: str | None = None

    def key(self) -> str:
        parts = [
            self.feature or "",
            self.record_id or "",
            self.property or "",
            self.table_id or "",
            str(self.page_no or ""),
            str(self.row if self.row is not None else ""),
            str(self.col if self.col is not None else ""),
        ]
        return "|".join(parts)


class EvidenceRef(BaseModel):
    page_no: int | None = None
    table_id: str | None = None
    row: int | None = None
    col: int | None = None
    quote: str = ""
    clause_id: str | None = None


class FeedbackCreate(BaseModel):
    doc_id: str
    job_id: str
    user_id: str | None = None
    category: FeedbackCategory
    target: FeedbackTarget = Field(default_factory=FeedbackTarget)
    description: str = ""
    expected_value: str | None = None
    source_quote: str | None = None
    priority: str = "P0"


class FeedbackItem(BaseModel):
    feedback_id: str
    doc_id: str
    job_id: str
    user_id: str | None = None
    category: FeedbackCategory
    target: FeedbackTarget = Field(default_factory=FeedbackTarget)
    description: str = ""
    expected_value: str | None = None
    source_quote: str | None = None
    status: FeedbackStatus = FeedbackStatus.open
    priority: str = "P0"
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class FeedbackMessage(BaseModel):
    message_id: str = Field(default_factory=lambda: new_id("msg"))
    feedback_id: str
    role: str = "system"
    content: str
    created_at: str = Field(default_factory=now_iso)


class Finding(BaseModel):
    finding_id: str = Field(default_factory=lambda: new_id("fnd"))
    doc_id: str
    job_id: str
    source: FindingSource
    verdict: FindingVerdict
    target: FeedbackTarget = Field(default_factory=FeedbackTarget)
    expected: str | None = None
    observed: str | None = None
    evidence: list[EvidenceRef] = Field(default_factory=list)
    rule_code: str | None = None
    confidence: float = 0.5
    priority: str = "P1"
    status: FindingStatus = FindingStatus.open
    created_at: str = Field(default_factory=now_iso)

    def dedupe_key(self) -> str:
        return f"{self.doc_id}|{self.target.key()}|{self.verdict.value}"


class RepairProposal(BaseModel):
    proposal_id: str = Field(default_factory=lambda: new_id("prp"))
    finding_ids: list[str] = Field(default_factory=list)
    level: RepairLevel
    operator: str
    params: dict[str, Any] = Field(default_factory=dict)
    target_signature: str | None = None
    status: ProposalStatus = ProposalStatus.proposed
    artifact_dir: str | None = None
    created_at: str = Field(default_factory=now_iso)


class GateCheck(BaseModel):
    name: str
    passed: bool
    detail: str = ""


class GateResult(BaseModel):
    gate_id: str = Field(default_factory=lambda: new_id("gate"))
    proposal_id: str
    checks: list[GateCheck] = Field(default_factory=list)
    decision: GateDecision = GateDecision.propose_only
    created_at: str = Field(default_factory=now_iso)


class AuditRun(BaseModel):
    audit_run_id: str = Field(default_factory=lambda: new_id("aud"))
    doc_id: str
    job_id: str
    model: str
    packet_tables: int = 0
    packet_records: int = 0
    findings: int = 0
    status: str = "completed"
    detail: str = ""
    created_at: str = Field(default_factory=now_iso)


class CandidateRecipe(BaseModel):
    candidate_id: str = Field(default_factory=lambda: new_id("cand"))
    proposal_id: str
    signature: str
    operator: str
    params: dict[str, Any] = Field(default_factory=dict)
    status: CandidateStatus = CandidateStatus.local
    overlay_dir: str | None = None
    created_at: str = Field(default_factory=now_iso)


class CodePatchProposal(BaseModel):
    patch_id: str = Field(default_factory=lambda: new_id("patch"))
    proposal_id: str
    files: list[str] = Field(default_factory=list)
    diff: str = ""
    status: ProposalStatus = ProposalStatus.propose_only
    reason: str = ""
    created_at: str = Field(default_factory=now_iso)


class RepairOutcome(BaseModel):
    feedback_id: str
    status: FeedbackStatus
    finding_ids: list[str] = Field(default_factory=list)
    proposal_id: str | None = None
    level: RepairLevel | None = None
    decision: GateDecision | None = None
    reply: str = ""
    diff: dict[str, Any] | None = None
    iterations: int = 0


def content_hash(payload: Any) -> str:
    import json

    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
