"""005_documents_phase1: 文档解析 Phase 1 数据模型 + KB RLS 策略。

- documents / document_tasks / task_outbox / task_dead_letter
- RLS 辅助函数（hansondoc_current_kb / hansondoc_is_superuser /
  hansondoc_kb_effective_role）
- documents / document_tasks 启用 RLS 并 FORCE（含群组并集授权）
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "005_documents_phase1"
down_revision = "004_p2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("kb_id", UUID(as_uuid=True), sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("file_type", sa.String(32), nullable=True),
        sa.Column("file_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("object_key", sa.String(512), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("process_status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("page_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("markdown_path", sa.String(512), nullable=True),
        sa.Column("layout_path", sa.String(512), nullable=True),
        sa.Column("error", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True, onupdate=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_documents_kb_id", "documents", ["kb_id"])
    op.create_index("ix_documents_kb_status", "documents", ["kb_id", "status"])
    op.create_index("ix_documents_sha256", "documents", ["sha256"])

    op.create_table(
        "document_tasks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("kb_id", UUID(as_uuid=True), sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_id", UUID(as_uuid=True), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("task_id", sa.String(64), nullable=False),
        sa.Column("type", sa.String(32), nullable=False, server_default="document_parse"),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("checkpoint", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("error", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True, onupdate=sa.func.now()),
    )
    op.create_index("ix_document_tasks_task_id", "document_tasks", ["task_id"], unique=True)
    op.create_index("ix_document_tasks_kb_id", "document_tasks", ["kb_id"])
    op.create_index("ix_document_tasks_document_id", "document_tasks", ["document_id"])

    op.create_table(
        "task_outbox",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("task_id", sa.String(64), nullable=False),
        sa.Column("type", sa.String(32), nullable=False, server_default="document_parse"),
        sa.Column("payload", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("enqueued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
    )
    op.create_index("ix_task_outbox_task_id", "task_outbox", ["task_id"], unique=True)
    op.create_index("ix_task_outbox_status", "task_outbox", ["status"])

    op.create_table(
        "task_dead_letter",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("task_id", sa.String(64), nullable=False),
        sa.Column("type", sa.String(32), nullable=False, server_default="document_parse"),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_task_dead_letter_task_id", "task_dead_letter", ["task_id"])

    # ---------- RLS 辅助函数 ----------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION hansondoc_current_kb() RETURNS uuid AS $$
            SELECT NULLIF(current_setting('app.current_kb', true), '')::uuid
        $$ LANGUAGE sql STABLE;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION hansondoc_is_superuser() RETURNS boolean AS $$
            SELECT COALESCE(current_setting('app.is_superuser', true), '') = 'true'
        $$ LANGUAGE sql STABLE;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION hansondoc_kb_effective_role(p_kb uuid, p_user uuid)
        RETURNS text AS $$
            SELECT t.role FROM (
                SELECT role,
                       CASE role WHEN 'owner' THEN 4 WHEN 'admin' THEN 3
                                 WHEN 'editor' THEN 2 ELSE 1 END AS rk
                  FROM kb_members
                 WHERE kb_id = p_kb AND user_id = p_user AND status = 'active'
                UNION ALL
                SELECT kga.role,
                       CASE kga.role WHEN 'admin' THEN 3 WHEN 'editor' THEN 2 ELSE 1 END AS rk
                  FROM kb_group_access kga
                  JOIN group_members gm ON gm.group_id = kga.group_id
                 WHERE kga.kb_id = p_kb AND gm.user_id = p_user AND kga.role <> 'owner'
            ) t
            ORDER BY rk DESC, role
            LIMIT 1
        $$ LANGUAGE sql STABLE;
        """
    )

    # ---------- documents RLS ----------
    op.execute("ALTER TABLE documents ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE documents FORCE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY doc_select ON documents FOR SELECT USING (
            hansondoc_is_superuser()
            OR (
                hansondoc_current_kb() = kb_id
                AND hansondoc_kb_effective_role(
                    kb_id, current_setting('app.user_id', true)::uuid
                ) IS NOT NULL
            )
        );
        """
    )
    op.execute(
        """
        CREATE POLICY doc_insert ON documents FOR INSERT WITH CHECK (
            hansondoc_is_superuser()
            OR (
                hansondoc_current_kb() = kb_id
                AND hansondoc_kb_effective_role(
                    kb_id, current_setting('app.user_id', true)::uuid
                ) IN ('owner', 'admin', 'editor')
            )
        );
        """
    )
    op.execute(
        """
        CREATE POLICY doc_update ON documents FOR UPDATE USING (
            hansondoc_is_superuser()
            OR (
                hansondoc_current_kb() = kb_id
                AND hansondoc_kb_effective_role(
                    kb_id, current_setting('app.user_id', true)::uuid
                ) IN ('owner', 'admin', 'editor')
            )
        ) WITH CHECK (
            hansondoc_is_superuser()
            OR (
                hansondoc_current_kb() = kb_id
                AND hansondoc_kb_effective_role(
                    kb_id, current_setting('app.user_id', true)::uuid
                ) IN ('owner', 'admin', 'editor')
            )
        );
        """
    )
    op.execute(
        """
        CREATE POLICY doc_delete ON documents FOR DELETE USING (
            hansondoc_is_superuser()
            OR (
                hansondoc_current_kb() = kb_id
                AND hansondoc_kb_effective_role(
                    kb_id, current_setting('app.user_id', true)::uuid
                ) IN ('owner', 'admin', 'editor')
            )
        );
        """
    )

    # ---------- document_tasks RLS ----------
    op.execute("ALTER TABLE document_tasks ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE document_tasks FORCE ROW LEVEL SECURITY;")
    for op_name, command in [
        ("task_select", "SELECT"),
        ("task_update", "UPDATE"),
        ("task_delete", "DELETE"),
    ]:
        op.execute(
            f"""
            CREATE POLICY {op_name} ON document_tasks FOR {command} USING (
                hansondoc_is_superuser()
                OR (
                    hansondoc_current_kb() = kb_id
                    AND hansondoc_kb_effective_role(
                        kb_id, current_setting('app.user_id', true)::uuid
                    ) IS NOT NULL
                )
            );
            """
        )
    op.execute(
        """
        CREATE POLICY task_insert ON document_tasks FOR INSERT WITH CHECK (
            hansondoc_is_superuser()
            OR (
                hansondoc_current_kb() = kb_id
                AND hansondoc_kb_effective_role(
                    kb_id, current_setting('app.user_id', true)::uuid
                ) IS NOT NULL
            )
        );
        """
    )


def downgrade() -> None:
    op.drop_table("task_dead_letter")
    op.drop_table("task_outbox")
    op.drop_table("document_tasks")
    op.drop_table("documents")
    op.execute("DROP FUNCTION IF EXISTS hansondoc_kb_effective_role(uuid, uuid);")
    op.execute("DROP FUNCTION IF EXISTS hansondoc_is_superuser();")
    op.execute("DROP FUNCTION IF EXISTS hansondoc_current_kb();")
