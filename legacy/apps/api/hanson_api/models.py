"""P0 platform models: users, knowledge bases, documents, tasks, API keys, audit."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def new_id() -> str:
    return uuid.uuid4().hex


def utcnow() -> datetime:
    # SQLite stores naive UTC; keep every model consistent.
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(128), default="")
    hashed_password: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(32), default="admin")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text, default="")
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"
    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", name="uq_workspace_member"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id"), index=True
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(32), default="member")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Invitation(Base):
    __tablename__ = "invitations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id"), index=True
    )
    invited_by: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(32), default="member")
    token_hash: Mapped[str] = mapped_column(
        String(64), unique=True, index=True
    )
    note: Mapped[str] = mapped_column(String(255), default="")
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    accepted_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class KnowledgeBase(Base):
    __tablename__ = "knowledge_bases"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id"), index=True
    )
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text, default="")
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    # 内建模块工作区标记：{"module": "standard_split", "builtin": true}
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class KnowledgeBaseMember(Base):
    __tablename__ = "knowledge_base_members"
    __table_args__ = (
        UniqueConstraint("kb_id", "user_id", name="uq_kb_member"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    kb_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_bases.id"), index=True
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(32), default="owner")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    kb_id: Mapped[str] = mapped_column(ForeignKey("knowledge_bases.id"), index=True)
    file_name: Mapped[str] = mapped_column(String(255))
    source_path: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    standard_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="uploaded")
    review_status: Mapped[str] = mapped_column(String(16), default="draft")
    review_version: Mapped[int] = mapped_column(default=1)
    confirmed_job_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    confirmed_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    results_job_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    results_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    job_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class DocumentTask(Base):
    __tablename__ = "document_tasks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id"), index=True
    )
    job_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(32), default="standard_extraction")
    version: Mapped[int] = mapped_column(default=1)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class IntegrationTask(Base):
    """一站式对接任务：task_id 贯穿上传、OCR 与结构化抽取。"""

    __tablename__ = "integration_tasks"

    task_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kb_id: Mapped[str] = mapped_column(ForeignKey("knowledge_bases.id"), index=True)
    document_id: Mapped[str | None] = mapped_column(
        ForeignKey("documents.id"), nullable=True, index=True
    )
    prompt_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    schema_template_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    filename: Mapped[str] = mapped_column(String(255), default="")
    ocr_status: Mapped[str] = mapped_column(String(16), default="pending")
    ocr_progress: Mapped[int] = mapped_column(default=0)
    extract_status: Mapped[str] = mapped_column(String(16), default="pending")
    extract_progress: Mapped[int] = mapped_column(default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    result_version: Mapped[int | None] = mapped_column(nullable=True)
    created_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, onupdate=utcnow
    )


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(128))
    prefix: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    hashed_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    scopes: Mapped[str] = mapped_column(String(255), default="documents:read")
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id"), index=True
    )
    kb_ids: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    actor_id: Mapped[str] = mapped_column(String(32), index=True)
    actor_type: Mapped[str] = mapped_column(String(16), default="user")
    workspace_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    target_type: Mapped[str] = mapped_column(String(32), default="")
    target_id: Mapped[str] = mapped_column(String(32), default="")
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ReviewEvent(Base):
    __tablename__ = "review_events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id"), index=True
    )
    term_type: Mapped[str] = mapped_column(String(16))
    raw: Mapped[str] = mapped_column(String(255))
    action: Mapped[str] = mapped_column(String(16))
    target_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    business_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    business_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    actor_id: Mapped[str] = mapped_column(String(32), index=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class FieldReviewEvent(Base):
    __tablename__ = "field_review_events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id"), index=True
    )
    job_id: Mapped[str] = mapped_column(String(32), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    field_path: Mapped[str] = mapped_column(String(255))
    action: Mapped[str] = mapped_column(String(16))
    old_value: Mapped[dict] = mapped_column(JSON, default=dict)
    new_value: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    reviewer: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class DocumentItem(Base):
    __tablename__ = "document_items"
    __table_args__ = (
        UniqueConstraint(
            "document_id", "job_id", "item_index", name="uq_document_item"
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id"), index=True
    )
    job_id: Mapped[str] = mapped_column(String(32), index=True)
    version: Mapped[int] = mapped_column(default=1)
    item_index: Mapped[int] = mapped_column(Integer)
    item_raw: Mapped[str] = mapped_column(String(255), default="")
    item_canonical: Mapped[str | None] = mapped_column(String(255), nullable=True)
    item_family: Mapped[str] = mapped_column(String(64), default="")
    facets: Mapped[dict] = mapped_column(JSON, default=dict)
    properties: Mapped[list] = mapped_column(JSON, default=list)
    property_matches: Mapped[list] = mapped_column(JSON, default=list)
    business_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    business_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    business_category_code: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    business_category_name: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    match_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    method_standard: Mapped[str | None] = mapped_column(String(255), nullable=True)
    method_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    method_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class DocumentRecord(Base):
    __tablename__ = "document_records"
    __table_args__ = (
        UniqueConstraint(
            "document_id", "job_id", "record_id", name="uq_document_record"
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id"), index=True
    )
    job_id: Mapped[str] = mapped_column(String(32), index=True)
    version: Mapped[int] = mapped_column(default=1)
    record_id: Mapped[str] = mapped_column(String(255))
    source_table_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    grade: Mapped[str | None] = mapped_column(String(128), nullable=True)
    grade_level: Mapped[str | None] = mapped_column(String(64), nullable=True)
    condition: Mapped[str | None] = mapped_column(String(255), nullable=True)
    facets: Mapped[dict] = mapped_column(JSON, default=dict)
    properties: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class DocumentClause(Base):
    __tablename__ = "document_clauses"
    __table_args__ = (
        UniqueConstraint(
            "document_id", "job_id", "clause_id", name="uq_document_clause"
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id"), index=True
    )
    job_id: Mapped[str] = mapped_column(String(32), index=True)
    version: Mapped[int] = mapped_column(default=1)
    clause_id: Mapped[str] = mapped_column(String(255))
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    page_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    kind: Mapped[str] = mapped_column(String(64), default="")
    fields: Mapped[dict] = mapped_column(JSON, default=dict)
    applies_to: Mapped[list] = mapped_column(JSON, default=list)
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(32), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class EvidenceIndex(Base):
    __tablename__ = "evidence_index"
    __table_args__ = (
        UniqueConstraint(
            "document_id", "job_id", "evidence_id", name="uq_evidence_index"
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id"), index=True
    )
    job_id: Mapped[str] = mapped_column(String(32), index=True)
    version: Mapped[int] = mapped_column(default=1)
    evidence_id: Mapped[str] = mapped_column(String(255))
    page_no: Mapped[int] = mapped_column(Integer)
    table_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    row: Mapped[int | None] = mapped_column(Integer, nullable=True)
    col: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quote_text: Mapped[str] = mapped_column(Text, default="")
    bbox: Mapped[list | None] = mapped_column(JSON, nullable=True)
    artifact_uri: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
