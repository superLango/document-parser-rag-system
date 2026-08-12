"""010_term_glossary: 专业术语集（term_bases / terms）+ RLS。

S8 术语集模块 S1：两张 KB 域表，软删 + 部分唯一索引（deleted_at IS NULL），
RLS 策略复用 009 模式（SELECT=成员，写=owner/admin/editor）。
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID

from alembic import op

revision = "010_term_glossary"
down_revision = "009_vector_indexing"
branch_labels = None
depends_on = None

ROLE = "hansondoc_kb_effective_role(kb_id, hansondoc_current_user())"

TABLES = ("term_bases", "terms")


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
        "term_bases",
        sa.Column("id", PgUUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("kb_id", PgUUID(as_uuid=True), sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("source_type", sa.String(16), nullable=False, server_default="manual"),
        sa.Column("source_config", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("columns", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("column_aliases", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("sync_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("created_by", PgUUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "idx_term_bases_kb", "term_bases", ["kb_id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "uq_term_bases_kb_name", "term_bases", ["kb_id", "name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "terms",
        sa.Column("id", PgUUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("kb_id", PgUUID(as_uuid=True), sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("term_base_id", PgUUID(as_uuid=True), sa.ForeignKey("term_bases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("term_name", sa.String(256), nullable=False),
        sa.Column("standard_name", sa.String(256), nullable=False, server_default=""),
        sa.Column("english_term", sa.String(256), nullable=False, server_default=""),
        sa.Column("definition", sa.Text(), nullable=False, server_default=""),
        sa.Column("category", sa.String(128), nullable=False, server_default=""),
        sa.Column("standard_number", sa.String(128), nullable=False, server_default=""),
        sa.Column("synonyms", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("aliases", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("extras", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("reviewed_by", PgUUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", PgUUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_terms_kb_base", "terms", ["kb_id", "term_base_id"], postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_index("idx_terms_kb_category", "terms", ["kb_id", "category"], postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_index("idx_terms_kb_status", "terms", ["kb_id", "status"], postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_index(
        "uq_terms_kb_base_name", "terms", ["kb_id", "term_base_id", "term_name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    for table, prefix in (("term_bases", "tbase"), ("terms", "term")):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
        _create_policies(table, prefix)


def downgrade() -> None:
    for table, prefix in (("term_bases", "tbase"), ("terms", "term")):
        _drop_policies(table, prefix)
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")
    op.drop_table("terms")
    op.drop_table("term_bases")
