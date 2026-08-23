"""专业术语集模型（S8 术语集模块）：术语集 + 术语条目。

全部表带 kb_id 并启用 RLS（迁移 010）；删除采用硬删（对齐原项目，
deleted_at 字段保留仅用于兼容旧数据，新数据不再写入）。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

# 数据源类型
SOURCE_TYPE_MANUAL = "manual"
SOURCE_TYPE_API = "api"
SOURCE_TYPE_DB = "db"
SOURCE_TYPES = frozenset({SOURCE_TYPE_MANUAL, SOURCE_TYPE_API, SOURCE_TYPE_DB})

# 术语状态
TERM_STATUS_ACTIVE = "active"
TERM_STATUS_PENDING = "pending"
TERM_STATUS_REJECTED = "rejected"
TERM_STATUSES = frozenset({TERM_STATUS_ACTIVE, TERM_STATUS_PENDING, TERM_STATUS_REJECTED})


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TermBase(Base):
    """术语集：一组术语条目的容器，支持 manual/api/db 三种来源。"""

    __tablename__ = "term_bases"
    __table_args__ = (
        # 唯一索引（deleted_at 兼容旧软删数据）
        Index(
            "uq_term_bases_kb_name", "kb_id", "name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kb_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    source_type: Mapped[str] = mapped_column(
        String(16), default=SOURCE_TYPE_MANUAL, nullable=False
    )
    # api/db 连接配置（password 等凭据入库前脱敏，响应时掩码）
    source_config: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    # 列定义 [{name, type, label}]
    columns: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    # 新表头名 → 原始字段/内置字段
    column_aliases: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    sync_enabled: Mapped[bool] = mapped_column(default=False, nullable=False)
    # 定时同步 cron 表达式（5 段标准 cron；空 = 未配置定时同步）
    sync_cron: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    # 下次执行时间（调度器计算，供前端展示）
    sync_next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 最近一次定时同步状态：idle / success / failed
    sync_status: Mapped[str] = mapped_column(String(16), default="idle", nullable=False)
    # 最近一次同步失败原因（截断存储）
    sync_last_error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), onupdate=utcnow, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Term(Base):
    """术语条目：标准/原始术语、同义词、别名与分类。

    审核流：手动创建默认 active；外部同步默认 pending，需 review。
    """

    __tablename__ = "terms"
    __table_args__ = (
        Index(
            "uq_terms_kb_base_name", "kb_id", "term_base_id", "term_name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kb_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True, nullable=False
    )
    term_base_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("term_bases.id", ondelete="CASCADE"), index=True, nullable=False
    )
    term_name: Mapped[str] = mapped_column(String(256), nullable=False)
    standard_name: Mapped[str] = mapped_column(String(256), default="", nullable=False)
    english_term: Mapped[str] = mapped_column(String(256), default="", nullable=False)
    definition: Mapped[str] = mapped_column(Text, default="", nullable=False)
    category: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    standard_number: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    synonyms: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    aliases: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    extras: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default=TERM_STATUS_ACTIVE, nullable=False)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), onupdate=utcnow, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
