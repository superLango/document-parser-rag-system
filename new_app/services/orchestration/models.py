from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def new_id() -> str:
    return str(uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    filename: Mapped[str] = mapped_column(String(512))
    content_type: Mapped[str] = mapped_column(String(128), default="application/octet-stream")
    size: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str] = mapped_column(String(64), index=True, unique=True)
    storage_key: Mapped[str] = mapped_column(String(1024))
    status: Mapped[str] = mapped_column(String(32), default="uploaded")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DocumentVersion(Base):
    __tablename__ = "document_versions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    storage_key: Mapped[str] = mapped_column(String(1024))
    sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class StandardIndex(Base):
    """标准号 → 文档正文索引；跨标准抽取按标准号查找被引正文。"""

    __tablename__ = "standard_index"
    __table_args__ = (
        UniqueConstraint("document_id", name="uq_standard_index_document"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    standard_no: Mapped[str] = mapped_column(String(64), default="", index=True)
    edition: Mapped[str] = mapped_column(String(8), default="")
    title: Mapped[str] = mapped_column(String(256), default="")
    source_kind: Mapped[str] = mapped_column(String(16), default="upload")
    # indexed / ocr_ready / parsed / failed
    status: Mapped[str] = mapped_column(String(24), default="indexed")
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    categories: Mapped[list] = mapped_column(JSON, default=list)
    grades: Mapped[list] = mapped_column(JSON, default=list)
    latest_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class IntegrationTask(Base):
    """One-stop integration task: external task_id bound to a local document.

    The external contract keeps ``kb_id`` / ``prompt_id`` for compatibility,
    but the current platform has no knowledge base or prompt store, so they are
    only persisted for traceability.
    """

    __tablename__ = "integration_tasks"

    task_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    kb_id: Mapped[str] = mapped_column(String(64), default="")
    prompt_id: Mapped[str] = mapped_column(String(64), default="")
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    schema_template_id: Mapped[str] = mapped_column(String(64), default="")
    filename: Mapped[str] = mapped_column(String(512), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    document_version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32), default="RECEIVED", index=True)
    stage: Mapped[str] = mapped_column(String(32), default="RECEIVED")
    # 0-100，阶段级进度；长文档/多人复核时可看到当前完成比例。
    progress: Mapped[int] = mapped_column(Integer, default=0)
    trace_id: Mapped[str] = mapped_column(String(64), index=True)
    recipe_channel: Mapped[str] = mapped_column(String(32), default="stable")
    idempotency_key: Mapped[str | None] = mapped_column(
        String(64), nullable=True, unique=True, index=True
    )
    engine_version: Mapped[str] = mapped_column(String(32), default="0.0.0")
    parser_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    repair_of: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    repair_attempt: Mapped[int] = mapped_column(Integer, default=0)
    recipe_override: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    result_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RunStage(Base):
    __tablename__ = "run_stages"
    __table_args__ = (UniqueConstraint("run_id", "stage", name="uq_run_stages_run_stage"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    stage: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), default="pending")
    input_refs: Mapped[dict] = mapped_column(JSON, default=dict)
    output_refs: Mapped[dict] = mapped_column(JSON, default=dict)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)


class RunEvent(Base):
    __tablename__ = "run_events"
    __table_args__ = (UniqueConstraint("run_id", "sequence", name="uq_run_events_run_sequence"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(64))
    stage: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(1024))
    sha256: Mapped[str] = mapped_column(String(64))
    bytes: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditEvent(Base):
    """跨 run 的审计事件（配方晋升/放弃/回滚等）。"""

    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    type: Mapped[str] = mapped_column(String(64), index=True)
    subject_type: Mapped[str] = mapped_column(String(64), default="recipe")
    subject_id: Mapped[str] = mapped_column(String(128), index=True)
    actor: Mapped[str] = mapped_column(String(128), default="operator")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReviewReport(Base):
    __tablename__ = "review_reports"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(32))
    ruleset_version: Mapped[str] = mapped_column(String(32), default="m1")
    stats: Mapped[dict] = mapped_column(JSON, default=dict)
    degraded: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Finding(Base):
    __tablename__ = "findings"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    report_id: Mapped[str] = mapped_column(
        ForeignKey("review_reports.id", ondelete="CASCADE"), index=True
    )
    source: Mapped[str] = mapped_column(String(32), default="deterministic")
    category: Mapped[str] = mapped_column(String(64))
    severity: Mapped[str] = mapped_column(String(32))
    target: Mapped[dict] = mapped_column(JSON, default=dict)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    rule_id: Mapped[str] = mapped_column(String(64), default="")
    observed: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_refs: Mapped[list] = mapped_column(JSON, default=list)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    status: Mapped[str] = mapped_column(String(32), default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    dedupe_key: Mapped[str | None] = mapped_column(
        String(64), nullable=True, unique=True, index=True
    )
    category: Mapped[str] = mapped_column(String(64))
    target: Mapped[dict] = mapped_column(JSON, default=dict)
    description: Mapped[str] = mapped_column(Text)
    expected_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="open")
    root_cause: Mapped[dict] = mapped_column(JSON, default=dict)
    messages: Mapped[list] = mapped_column(JSON, default=list)
    triage: Mapped[dict] = mapped_column(JSON, default=dict)
    proposal: Mapped[dict] = mapped_column(JSON, default=dict)
    verification: Mapped[dict] = mapped_column(JSON, default=dict)
    candidate: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AcceptedSnapshot(Base):
    __tablename__ = "accepted_snapshots"
    __table_args__ = (
        UniqueConstraint("document_id", "records_digest", name="uq_snapshot_doc_digest"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    document_version: Mapped[int] = mapped_column(Integer, default=1)
    run_id: Mapped[str] = mapped_column(String(64), default="")
    feedback_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    records: Mapped[int] = mapped_column(Integer, default=0)
    records_digest: Mapped[str] = mapped_column(String(64), default="")
    accepted_tables: Mapped[list] = mapped_column(JSON, default=list)
    accepted_fields: Mapped[list] = mapped_column(JSON, default=list)
    field_digests: Mapped[dict] = mapped_column(JSON, default=dict)
    actor: Mapped[str] = mapped_column(String(128), default="operator")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ShadowDocument(Base):
    __tablename__ = "shadow_documents"

    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True
    )
    added_by: Mapped[str] = mapped_column(String(128), default="operator")
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ShadowBatch(Base):
    __tablename__ = "shadow_batches"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    recipe_id: Mapped[str] = mapped_column(String(128), index=True)
    from_version: Mapped[str] = mapped_column(String(32), default="")
    candidate_version: Mapped[str] = mapped_column(String(32), default="")
    feedback_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    required_documents: Mapped[int] = mapped_column(Integer, default=10)
    completed: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    actor: Mapped[str] = mapped_column(String(128), default="operator")
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    deadline_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ShadowResult(Base):
    __tablename__ = "shadow_results"
    __table_args__ = (
        UniqueConstraint("batch_id", "document_id", name="uq_shadow_batch_document"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    batch_id: Mapped[str] = mapped_column(
        ForeignKey("shadow_batches.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[str] = mapped_column(String(64), index=True)
    stable_run_id: Mapped[str] = mapped_column(String(64), default="")
    shadow_run_id: Mapped[str] = mapped_column(String(64), default="")
    passed: Mapped[bool] = mapped_column(Boolean, default=False)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Promotion(Base):
    __tablename__ = "promotions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    feedback_id: Mapped[str | None] = mapped_column(
        ForeignKey("feedback.id", ondelete="CASCADE"), nullable=True, index=True
    )
    recipe_id: Mapped[str] = mapped_column(String(128))
    from_version: Mapped[str] = mapped_column(String(32), default="")
    to_version: Mapped[str] = mapped_column(String(32), default="")
    channel: Mapped[str] = mapped_column(String(32), default="stable")
    action: Mapped[str] = mapped_column(String(32), default="promote")
    actor: Mapped[str] = mapped_column(String(128), default="operator")
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
