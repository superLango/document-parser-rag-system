"""016_extraction_result: 结构化抽取结果/历史表 + documents.extraction_status + RLS。

- extraction_results：每文档最新一条（kb_id+document_id 唯一）；
- extraction_history：历史版本归档（保留 50 条）；
- documents 增加 extraction_status（nullable：未抽取/completed/failed/running）；
- RLS 复用 012 模式：SELECT=成员，写=owner/admin/editor。
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID

revision = "016_extraction_result"
down_revision = "015_global_extraction_config"
branch_labels = None
depends_on = None

ROLE = "hansondoc_kb_effective_role(kb_id, hansondoc_current_user())"
TABLES = (("extraction_results", "eres"), ("extraction_history", "ehis"))


def _drop_policies(table: str, prefix: str) -> None:
    for name in (
        f"{prefix}_select",
        f"{prefix}_insert",
        f"{prefix}_update",
        f"{prefix}_delete",
    ):
        op.execute(f"DROP POLICY IF EXISTS {name} ON {table};")


def _create_policies(table: str, prefix: str) -> None:
    op.execute(
        f"""
        CREATE POLICY {prefix}_select ON {table} FOR SELECT USING (
            hansondoc_is_superuser()
            OR (hansondoc_current_kb() = kb_id AND {ROLE} IS NOT NULL)
        );
        """
    )
    for command, clause in (
        ("INSERT", "WITH CHECK"),
        ("UPDATE", "USING"),
        ("DELETE", "USING"),
    ):
        op.execute(
            f"""
            CREATE POLICY {prefix}_{command.lower()} ON {table} FOR {command} {clause} (
                hansondoc_is_superuser()
                OR (hansondoc_current_kb() = kb_id AND {ROLE} IN ('owner', 'admin', 'editor'))
            );
            """
        )


def upgrade() -> None:
    op.create_table(
        "extraction_results",
        sa.Column("id", PgUUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("kb_id", PgUUID(as_uuid=True), sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_id", PgUUID(as_uuid=True), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("schema_template_id", PgUUID(as_uuid=True), sa.ForeignKey("schema_templates.id", ondelete="SET NULL"), nullable=True),
        sa.Column("schema_name", sa.String(255), nullable=False, server_default=""),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("progress", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("categories", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("summary", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("timing", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("error", JSONB(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_extraction_results_kb", "extraction_results", ["kb_id"])
    op.create_index("idx_extraction_results_doc", "extraction_results", ["document_id"])
    op.create_unique_constraint("uq_extraction_results_kb_doc", "extraction_results", ["kb_id", "document_id"])

    op.create_table(
        "extraction_history",
        sa.Column("id", PgUUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("kb_id", PgUUID(as_uuid=True), sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_id", PgUUID(as_uuid=True), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("schema_template_id", PgUUID(as_uuid=True), sa.ForeignKey("schema_templates.id", ondelete="SET NULL"), nullable=True),
        sa.Column("schema_name", sa.String(255), nullable=False, server_default=""),
        sa.Column("categories", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("summary", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("timing", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("extracted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_extraction_history_kb", "extraction_history", ["kb_id"])
    op.create_index("idx_extraction_history_doc", "extraction_history", ["document_id", "archived_at"])

    op.add_column("documents", sa.Column("extraction_status", sa.String(32), nullable=True))

    for table, prefix in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
        _create_policies(table, prefix)


def downgrade() -> None:
    for table, prefix in reversed(TABLES):
        _drop_policies(table, prefix)
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")
    op.drop_column("documents", "extraction_status")
    op.drop_table("extraction_history")
    op.drop_table("extraction_results")
