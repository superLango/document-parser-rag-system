"""phase2 新表：qa_sessions/qa_messages/notifications/kb_backups + documents.search_vector。

Revision ID: 002_phase2_tables
Revises: 001_baseline
Create Date: 2026-08-02

新增表（阶段 2-4 用）：
- qa_sessions / qa_messages：问答会话与消息（RLS 按 kb_id）
- notifications：通知中心（按 user_id，不走 RLS）
- kb_backups：KB 备份记录（RLS 按 kb_id）

修改表：
- documents +search_vector（tsvector 生成列 + GIN 索引，全文搜索用）
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision = "002_phase2_tables"
down_revision = "001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---------- qa_sessions ----------
    op.create_table(
        "qa_sessions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("kb_id", UUID(as_uuid=True), sa.ForeignKey("knowledge_bases.id"), nullable=False, index=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("title", sa.String(255), nullable=False, default="未命名会话"),
        sa.Column("doc_ids", sa.JSON, nullable=True, comment="关联文档 ID 列表"),
        sa.Column("message_count", sa.Integer, nullable=False, default=0),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        comment="问答会话表（RLS 按 kb_id）",
    )

    # ---------- qa_messages ----------
    op.create_table(
        "qa_messages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("session_id", UUID(as_uuid=True), sa.ForeignKey("qa_sessions.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("role", sa.String(20), nullable=False, comment="user/assistant/system"),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("citations", sa.JSON, nullable=True, comment="引用来源"),
        sa.Column("tokens", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, index=True),
        comment="问答消息表",
    )

    # ---------- notifications ----------
    op.create_table(
        "notifications",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("type", sa.String(32), nullable=False, comment="task_done/task_failed/system/audit_alert"),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("content", sa.Text, nullable=True),
        sa.Column("read", sa.Boolean, nullable=False, default=False, index=True),
        sa.Column("resource_type", sa.String(32), nullable=True),
        sa.Column("resource_id", sa.String(64), nullable=True),
        sa.Column("kb_id", UUID(as_uuid=True), nullable=True, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, index=True),
        comment="通知中心（按 user_id，不走 RLS）",
    )
    op.create_index("ix_notifications_user_read", "notifications", ["user_id", "read"])

    # ---------- kb_backups ----------
    op.create_table(
        "kb_backups",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("kb_id", UUID(as_uuid=True), sa.ForeignKey("knowledge_bases.id"), nullable=False, index=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("file_size", sa.BigInteger, nullable=False, default=0),
        sa.Column("status", sa.String(20), nullable=False, default="completed", comment="completed/failed"),
        sa.Column("item_counts", sa.JSON, nullable=True, comment="各资源备份条数"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, index=True),
        comment="KB 备份记录（RLS 按 kb_id）",
    )

    # ---------- documents.search_vector（全文搜索）----------
    op.execute(
        """
        ALTER TABLE documents
        ADD COLUMN IF NOT EXISTS search_vector tsvector
        GENERATED ALWAYS AS (
            to_tsvector('simple', coalesce(filename, '') || ' ' || coalesce(parsed_text, ''))
        ) STORED
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_documents_search_vector ON documents USING GIN(search_vector)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_documents_search_vector")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS search_vector")
    op.drop_table("kb_backups")
    op.drop_index("ix_notifications_user_read", table_name="notifications")
    op.drop_table("notifications")
    op.drop_table("qa_messages")
    op.drop_table("qa_sessions")
