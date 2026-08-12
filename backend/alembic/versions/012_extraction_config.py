"""012_extraction_config: 抽取配置（Schema/Prompt/规则/脚本）+ RLS。

M34 抽取配置四项复刻 S1：8 张 KB 域表，删除采用硬删（FK CASCADE），
RLS 策略复用 010 模式（SELECT=成员，写=owner/admin/editor）。
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID

from alembic import op

revision = "012_extraction_config"
down_revision = "011_hard_delete_glossary"
branch_labels = None
depends_on = None

ROLE = "hansondoc_kb_effective_role(kb_id, hansondoc_current_user())"

# 表 -> RLS 策略前缀
TABLES = (
    ("schema_templates", "sctpl"),
    ("schema_categories", "sccat"),
    ("schema_fields", "scfld"),
    ("prompt_templates", "ptmpl"),
    ("prompt_content", "ptcnt"),
    ("rule_groups", "rgrp"),
    ("rule_group_items", "rgitem"),
    ("kb_scripts", "scr"),
)


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
        "schema_templates",
        sa.Column("id", PgUUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("kb_id", PgUUID(as_uuid=True), sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_by", PgUUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_schema_templates_kb", "schema_templates", ["kb_id"])
    op.create_index("uq_schema_templates_kb_name", "schema_templates", ["kb_id", "name"], unique=True)

    op.create_table(
        "schema_categories",
        sa.Column("id", PgUUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("kb_id", PgUUID(as_uuid=True), sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("template_id", PgUUID(as_uuid=True), sa.ForeignKey("schema_templates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(128), nullable=False, server_default=""),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("return_type", sa.String(16), nullable=False, server_default="array"),
        sa.Column("extraction_strategy", sa.String(16), nullable=False, server_default="auto"),
        sa.Column("fixed_query", sa.Text(), nullable=False, server_default=""),
        sa.Column("confidence_threshold", sa.Float(), nullable=True),
        sa.Column("top_k", sa.Integer(), nullable=True),
        sa.Column("rerank_top_k", sa.Integer(), nullable=True),
        sa.Column("max_tokens", sa.Integer(), nullable=True),
        sa.Column("name_source", sa.String(16), nullable=False, server_default="manual"),
        sa.Column("name_term_base_id", PgUUID(as_uuid=True), sa.ForeignKey("term_bases.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name_term_field", sa.String(128), nullable=False, server_default=""),
        sa.Column("query_sources", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_schema_categories_kb", "schema_categories", ["kb_id"])
    op.create_index("idx_schema_categories_template", "schema_categories", ["kb_id", "template_id"])

    op.create_table(
        "schema_fields",
        sa.Column("id", PgUUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("kb_id", PgUUID(as_uuid=True), sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category_id", PgUUID(as_uuid=True), sa.ForeignKey("schema_categories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("type", sa.String(16), nullable=False, server_default="string"),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("example", sa.Text(), nullable=True),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_schema_fields_kb", "schema_fields", ["kb_id"])
    op.create_index("uq_schema_fields_category_name", "schema_fields", ["category_id", "name"], unique=True)

    op.create_table(
        "prompt_templates",
        sa.Column("id", PgUUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("kb_id", PgUUID(as_uuid=True), sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("scope", sa.String(16), nullable=False, server_default="simple"),
        sa.Column("schema_template_id", PgUUID(as_uuid=True), sa.ForeignKey("schema_templates.id", ondelete="SET NULL"), nullable=True),
        sa.Column("category_ids", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_by", PgUUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_prompt_templates_kb", "prompt_templates", ["kb_id"])
    op.create_index("uq_prompt_templates_kb_name", "prompt_templates", ["kb_id", "name"], unique=True)

    op.create_table(
        "prompt_content",
        sa.Column("id", PgUUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("kb_id", PgUUID(as_uuid=True), sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("prompt_id", PgUUID(as_uuid=True), sa.ForeignKey("prompt_templates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category_id", PgUUID(as_uuid=True), sa.ForeignKey("schema_categories.id", ondelete="SET NULL"), nullable=True),
        sa.Column("system_prompt", sa.Text(), nullable=False, server_default=""),
        sa.Column("user_prompt", sa.Text(), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_prompt_content_kb", "prompt_content", ["kb_id"])
    op.create_index("uq_prompt_content_prompt_category", "prompt_content", ["prompt_id", "category_id"], unique=True)
    op.create_index(
        "uq_prompt_content_simple",
        "prompt_content",
        ["prompt_id"],
        unique=True,
        postgresql_where=sa.text("category_id IS NULL"),
    )

    op.create_table(
        "rule_groups",
        sa.Column("id", PgUUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("kb_id", PgUUID(as_uuid=True), sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_rule_groups_kb", "rule_groups", ["kb_id"])
    op.create_index("uq_rule_groups_kb_name", "rule_groups", ["kb_id", "name"], unique=True)

    op.create_table(
        "rule_group_items",
        sa.Column("id", PgUUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("kb_id", PgUUID(as_uuid=True), sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("group_id", PgUUID(as_uuid=True), sa.ForeignKey("rule_groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category_id", PgUUID(as_uuid=True), sa.ForeignKey("schema_categories.id", ondelete="SET NULL"), nullable=True),
        sa.Column("script_name", sa.String(128), nullable=False),
        sa.Column("params", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_rule_group_items_kb", "rule_group_items", ["kb_id"])
    op.create_index("idx_rule_group_items_group", "rule_group_items", ["kb_id", "group_id"])

    op.create_table(
        "kb_scripts",
        sa.Column("id", PgUUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("kb_id", PgUUID(as_uuid=True), sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("folder", sa.String(16), nullable=False, server_default="post"),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("code", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_by", PgUUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_kb_scripts_kb", "kb_scripts", ["kb_id"])
    op.create_index("uq_kb_scripts_folder_name", "kb_scripts", ["kb_id", "folder", "name"], unique=True)

    for table, prefix in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
        _create_policies(table, prefix)


def downgrade() -> None:
    for table, prefix in reversed(TABLES):
        _drop_policies(table, prefix)
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")
    for table in (
        "kb_scripts",
        "rule_group_items",
        "rule_groups",
        "prompt_content",
        "prompt_templates",
        "schema_fields",
        "schema_categories",
        "schema_templates",
    ):
        op.drop_table(table)
