"""Schema 模板：schema_templates 新表 + schema_configs 类别级配置列。

Revision ID: 006_schema_templates
Revises: 005_datasets
Create Date: 2026-08-04

新增表：
- schema_templates：Schema 模板容器（三层结构顶层，RLS 按 kb_id）

修改表：
- schema_configs 新增类别级配置列：template_id / node_type / return_type /
  extraction_strategy / query_mode / fixed_query / confidence_threshold / top_k / datasets
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision = "006_schema_templates"
down_revision = "005_datasets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---------- schema_templates 表 ----------
    op.create_table(
        "schema_templates",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("kb_id", UUID(as_uuid=True), sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        comment="Schema 模板表（RLS 按 kb_id）",
    )

    # ---------- schema_configs 新增类别级配置列 ----------
    op.add_column(
        "schema_configs",
        sa.Column(
            "template_id",
            UUID(as_uuid=True),
            sa.ForeignKey("schema_templates.id", ondelete="CASCADE"),
            nullable=True,
            index=True,
        ),
    )
    op.add_column(
        "schema_configs",
        sa.Column("node_type", sa.String(20), nullable=False, server_default="category"),
    )
    op.add_column(
        "schema_configs",
        sa.Column("return_type", sa.String(10), nullable=False, server_default="array"),
    )
    op.add_column(
        "schema_configs",
        sa.Column("extraction_strategy", sa.String(10), nullable=False, server_default="auto"),
    )
    op.add_column(
        "schema_configs",
        sa.Column("query_mode", sa.String(10), nullable=False, server_default="fixed"),
    )
    op.add_column(
        "schema_configs",
        sa.Column("fixed_query", sa.String(500), nullable=True),
    )
    op.add_column(
        "schema_configs",
        sa.Column("confidence_threshold", sa.Float, nullable=True),
    )
    op.add_column(
        "schema_configs",
        sa.Column("top_k", sa.Integer, nullable=True),
    )
    op.add_column(
        "schema_configs",
        sa.Column("datasets", sa.JSON, nullable=False, server_default=sa.text("'[]'::json")),
    )

    # ---------- schema_templates 启用 RLS ----------
    op.execute("ALTER TABLE schema_templates ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY kb_isolation ON schema_templates
        FOR ALL
        USING (kb_id::text = current_setting('app.current_kb', true))
        WITH CHECK (kb_id::text = current_setting('app.current_kb', true))
        """
    )


def downgrade() -> None:
    for col in (
        "template_id",
        "node_type",
        "return_type",
        "extraction_strategy",
        "query_mode",
        "fixed_query",
        "confidence_threshold",
        "top_k",
        "datasets",
    ):
        op.drop_column("schema_configs", col)

    op.execute("DROP POLICY IF EXISTS kb_isolation ON schema_templates")
    op.execute("ALTER TABLE schema_templates DISABLE ROW LEVEL SECURITY")
    op.drop_table("schema_templates")