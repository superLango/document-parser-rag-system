"""Pydantic DTOs for the platform API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    username: str
    display_name: str = ""
    role: str = "admin"


class UserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8, max_length=256)
    display_name: str = ""
    role: Literal["admin", "user"] = "user"


class UserAdminUpdate(BaseModel):
    display_name: str | None = None
    role: Literal["admin", "user"] | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=256)


class UserAdminOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    username: str
    display_name: str = ""
    role: str = "user"
    is_active: bool = True
    created_at: datetime


class ProfileUpdate(BaseModel):
    display_name: str = Field(min_length=1, max_length=128)


class PasswordChange(BaseModel):
    old_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=8, max_length=256)


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = ""


class WorkspaceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = None


class WorkspaceOut(BaseModel):
    id: str
    name: str
    description: str = ""
    owner_id: str
    role: str = "member"
    member_count: int = 0
    kb_count: int = 0
    created_at: datetime


class WorkspaceMemberCreate(BaseModel):
    username: str | None = None
    user_id: str | None = None
    role: Literal["admin", "member"] = "member"


class WorkspaceMemberUpdate(BaseModel):
    role: Literal["owner", "admin", "member"]


class WorkspaceMemberOut(BaseModel):
    user_id: str
    username: str
    display_name: str = ""
    role: str
    created_at: datetime


class InvitationCreate(BaseModel):
    role: Literal["admin", "member"] = "member"
    note: str = ""
    expires_minutes: int | None = Field(default=None, ge=1, le=525600)


class InvitationOut(BaseModel):
    id: str
    workspace_id: str
    role: str
    note: str = ""
    status: str = "pending"
    expires_at: datetime
    accepted_at: datetime | None = None
    revoked_at: datetime | None = None
    created_at: datetime
    token: str | None = None


class InvitationAcceptOut(BaseModel):
    workspace_id: str
    workspace_name: str
    role: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


class KnowledgeBaseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = ""
    workspace_id: str | None = None


class KnowledgeBaseUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = None


class KnowledgeBaseOut(BaseModel):
    id: str
    workspace_id: str
    name: str
    description: str = ""
    owner_id: str
    role: str = ""
    created_at: datetime
    document_count: int = 0
    member_count: int = 0


class KnowledgeBaseMemberCreate(BaseModel):
    username: str | None = None
    user_id: str | None = None
    role: Literal["owner", "editor", "viewer"] = "viewer"


class KnowledgeBaseMemberUpdate(BaseModel):
    role: Literal["owner", "editor", "viewer"]


class KnowledgeBaseMemberOut(BaseModel):
    user_id: str
    username: str
    display_name: str = ""
    role: str
    created_at: datetime


class ModuleOut(BaseModel):
    key: str
    name: str
    summary: str
    description: str
    status: Literal["active", "planned"]
    input_types: list[str] = Field(default_factory=list)
    highlights: list[str] = Field(default_factory=list)
    kb_id: str | None = None
    role: str = ""
    document_count: int = 0
    task_count: int = 0
    pending_review_count: int = 0
    confirmed_count: int = 0
    created_at: datetime | None = None


class TaskOut(BaseModel):
    document_id: str
    kb_id: str | None = None
    job_id: str
    kind: str = "standard_extraction"
    version: int = 1
    locked: bool = False
    status: str = "queued"
    stage: str = "created"
    progress: int = 0
    error: str | None = None
    failure_code: str | None = None
    result_status: str | None = None
    summary: dict = Field(default_factory=dict)
    source_name: str | None = None
    created_at: str | None = None


class DocumentOut(BaseModel):
    id: str
    kb_id: str
    workspace_id: str | None = None
    file_name: str
    sha256: str
    status: str
    job_id: str | None = None
    review_status: Literal["draft", "review", "confirmed"] = "draft"
    review_version: int = 1
    confirmed_job_id: str | None = None
    confirmed_by: str | None = None
    confirmed_at: datetime | None = None
    results_job_id: str | None = None
    results_synced_at: datetime | None = None
    standard_no: str | None = None
    title: str | None = None
    created_at: datetime
    file_size: int = 0
    page_count: int = 0
    latest_schema_name: str | None = None
    history_count: int = 0
    task: TaskOut | None = None


class DocumentReviewRequest(BaseModel):
    action: Literal["submit", "confirm"]
    reason: str = ""


class DocumentReviewOut(BaseModel):
    document_id: str
    review_status: Literal["draft", "review", "confirmed"]
    review_version: int
    job_id: str | None = None
    confirmed_job_id: str | None = None
    pending_new_terms: int = 0
    confirmed_by: str | None = None
    confirmed_at: datetime | None = None
    message: str = ""


class DocumentFeedbackRequest(BaseModel):
    """User-reported problem on one extracted record/table."""

    category: str = "other"
    record_id: str | None = None
    property: str | None = None
    table_id: str | None = None
    feature: str | None = None
    page_no: int | None = None
    grade: str | None = None
    condition: str | None = None
    description: str = ""
    expected_value: str | None = None
    source_quote: str | None = None


class ShareOut(BaseModel):
    token: str
    expires_at: datetime
    path: str


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    scopes: list[str] = Field(
        default_factory=lambda: ["documents:read", "documents:write", "tasks:read"]
    )
    workspace_id: str | None = None
    kb_ids: list[str] | None = None


class ApiKeyOut(BaseModel):
    id: str
    name: str
    prefix: str
    scopes: list[str]
    workspace_id: str
    kb_ids: list[str] = Field(default_factory=list)
    created_at: datetime
    revoked_at: datetime | None = None
    key: str | None = None


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    actor_id: str
    actor_type: str
    workspace_id: str = ""
    action: str
    target_type: str
    target_id: str
    detail: str
    created_at: datetime


class NewTermReviewRequest(BaseModel):
    type: Literal["category", "item", "method"]
    raw: str = Field(min_length=1, max_length=255)
    action: Literal["accept", "map", "reject"]
    business_code: str | None = None
    business_name: str | None = None
    target_code: str | None = None
    category_code: str | None = None
    category_name: str | None = None
    standard_no: str | None = None
    reason: str = ""


class DictionaryAliasCreate(BaseModel):
    type: Literal["category", "item", "method"]
    business_code: str = Field(min_length=1, max_length=64)
    alias: str = Field(min_length=1, max_length=255)


class DictionaryEntryCreate(BaseModel):
    business_code: str | None = Field(default=None, max_length=64)
    business_name: str = Field(min_length=1, max_length=255)
    family: str | None = None
    aliases: list[str] = Field(default_factory=list)
    standard_no: str | None = None
    category_code: str | None = None
    category_name: str | None = None
    facets: dict[str, list[str]] = Field(default_factory=dict)


class DictionaryEntryUpdate(BaseModel):
    business_name: str | None = Field(default=None, min_length=1, max_length=255)
    family: str | None = None
    aliases: list[str] | None = None
    standard_no: str | None = None
    category_code: str | None = None
    category_name: str | None = None
    status: Literal["active", "inactive"] | None = None


class DictionarySyncRequest(BaseModel):
    source: Literal["snapshot"] = "snapshot"


class ReviewEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    document_id: str
    term_type: str
    raw: str
    action: str
    target_code: str | None = None
    business_code: str | None = None
    business_name: str | None = None
    actor_id: str
    reason: str = ""
    created_at: datetime


class FieldReviewRequest(BaseModel):
    field_path: str = Field(min_length=5, max_length=255)
    action: Literal["accept", "edit", "reject"]
    old_value: dict = Field(default_factory=dict)
    new_value: dict | None = None
    reason: str = ""


class FieldReviewBatchRequest(BaseModel):
    events: list[FieldReviewRequest]


class FieldReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    document_id: str
    job_id: str
    version: int
    field_path: str
    action: str
    old_value: dict
    new_value: dict | None = None
    reason: str = ""
    reviewer: str
    created_at: datetime


class FieldDiffOut(BaseModel):
    field_path: str
    record_id: str
    property: str
    action: str
    machine: dict | None = None
    human: dict | None = None
    reason: str = ""
    reviewer: str
    created_at: str
    changed: bool = False


class RiskFieldOut(BaseModel):
    field_path: str
    record_id: str
    property: str
    level: str
    reasons: list[str] = Field(default_factory=list)
    evidence_id: str | None = None
    page_no: int | None = None


class DocumentRiskOut(BaseModel):
    document_id: str
    level: str
    counts: dict[str, int] = Field(default_factory=dict)
    high_risk_fields: list[RiskFieldOut] = Field(default_factory=list)
    fields: list[RiskFieldOut] = Field(default_factory=list)
