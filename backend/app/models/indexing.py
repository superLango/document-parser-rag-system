"""S1 索引存储模型：向量块、全文溯源块、KB BM25 统计。

与旧项目（Milvus/Popo）无任何依赖；存储全部落在 PostgreSQL + pgvector，
所有表带 kb_id 并启用 RLS（迁移 009 中建策略）。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

# BGE-M3 输出维度（D2 已确认：1024）
EMBEDDING_DIM = 1024


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DocumentChunk(Base):
    """向量检索主表：每行一个子块，携带双向量（title/content）与结构化字段。

    title_vector 编码层级面包屑（hierarchy_path + title），负责章节定位；
    content_vector 编码 content_for_embedding（表格增强文本前置），负责语义召回；
    bm25_tokens 为 jieba 词元计数（JSONB + GIN 索引），供稀疏路候选过滤。
    """

    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_id", name="uq_document_chunks_doc_chunk"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    kb_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    # 业务块 ID：'{document_id}_p{parent_idx}_{child_idx}'
    chunk_id: Mapped[str] = mapped_column(String(128), nullable=False)
    parent_chunk_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    chunk_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    hierarchy_path: Mapped[str] = mapped_column(Text, default="", nullable=False)
    title: Mapped[str] = mapped_column(Text, default="", nullable=False)
    level: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    has_table: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    semantic_label: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    source_pages: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # 表格增强/题注前置后的嵌入文本；None 时按 content 编码
    content_for_embedding: Mapped[str | None] = mapped_column(Text, nullable=True)
    parent_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    title_vector: Mapped[list | None] = mapped_column(
        Vector(EMBEDDING_DIM), nullable=True
    )
    content_vector: Mapped[list | None] = mapped_column(
        Vector(EMBEDDING_DIM), nullable=True
    )
    bm25_tokens: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=utcnow, nullable=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class TextChunk(Base):
    """全文溯源表（D5，lightRAG text_chunks 思路）。

    与 document_chunks 分离：向量表负责检索，本表保存块原文+元数据，
    供问答溯源、引用展示与审计；文档删除时随 FK 级联清理。
    """

    __tablename__ = "text_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_id", name="uq_text_chunks_doc_chunk"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    kb_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    # 关联 document_chunks.id（UUID），避免与业务 chunk_id 字符串混淆
    document_chunk_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("document_chunks.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    chunk_id: Mapped[str] = mapped_column(String(128), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    heading: Mapped[str] = mapped_column(Text, default="", nullable=False)
    tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # 列名保持 metadata（与迁移/API 契约一致），属性名避开 SQLAlchemy 保留字
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=utcnow, nullable=True
    )


class KbBm25Stats(Base):
    """KB 级 BM25 增量统计（D4）。

    payload 结构：{"n_docs": int, "total_len": int, "doc_freq": {token: df}}。
    随文档索引增量更新，version 作为乐观锁，避免并发索引/重建互相覆盖。
    """

    __tablename__ = "kb_bm25_stats"

    kb_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        primary_key=True,
    )
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
