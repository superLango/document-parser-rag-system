"""系统对接任务模型：上传→OCR→结构化抽取 一站式（task_id 统一追踪）。"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class IntegrationTask(Base):
    """对接任务：task_id 贯穿 OCR 解析与结构化抽取。"""

    __tablename__ = "integration_tasks"
    __table_args__ = (
        Index("idx_integration_tasks_doc", "document_id"),
    )

    task_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kb_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    prompt_id: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    schema_template_id: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    filename: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    ocr_status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    ocr_progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    extract_status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    extract_progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    result_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), onupdate=utcnow, nullable=True)
