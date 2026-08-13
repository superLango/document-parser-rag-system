"""Phase 1 数据模型：文档、解析任务、事务性 Outbox、死信。"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kb_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True, nullable=False
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    file_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    object_key: Mapped[str] = mapped_column(String(512), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False)
    process_status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False)
    progress_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    progress_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    markdown_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    layout_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    pages_cleaned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # ---------- 独立索引阶段状态（S1/D8）：解析状态与索引状态互不覆盖 ----------
    index_status: Mapped[str] = mapped_column(
        String(32), default="not_indexed", server_default="not_indexed", nullable=False
    )
    index_progress: Mapped[int | None] = mapped_column(Integer, nullable=True)
    index_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    index_error: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # ---------- 结构化抽取状态（E1）：null=未抽取 / running / completed / failed ----------
    extraction_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), onupdate=utcnow, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DocumentTask(Base):
    __tablename__ = "document_tasks"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kb_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True, nullable=False
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    task_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    type: Mapped[str] = mapped_column(String(32), default="document_parse", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    checkpoint: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    error: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), onupdate=utcnow, nullable=True)


class TaskOutbox(Base):
    __tablename__ = "task_outbox"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    type: Mapped[str] = mapped_column(String(32), default="document_parse", nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    enqueued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class TaskDeadLetter(Base):
    __tablename__ = "task_dead_letter"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    type: Mapped[str] = mapped_column(String(32), default="document_parse", nullable=False)
    error: Mapped[str] = mapped_column(Text, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
