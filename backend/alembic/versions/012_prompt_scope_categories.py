"""012: Prompt 模板作用域 / Schema 关联 / 类别子表

Revision ID: 012_prompt_scope_categories
Revises: 011_prompt_template_paired
Create Date: 2026-08-05

变更：
- kb_prompt_templates 表新增：scope, schema_template_id
- 新建 kb_prompt_categories 子表（scope=schema 时按类别存 user_prompt）
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision = "012_prompt_scope_categories"
down_revision = "011_prompt_template_paired"
branch_labels = None
depends_on = None


def _enable_rls(table: str) -> None:
    """为指定表启用 RLS + kb_isolation 策略。"""
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY kb_isolation ON {table}
        FOR ALL
        USING (kb_id::text = current_setting('app.current_kb', true))
        WITH CHECK (kb_id::text = current_setting('app.current_kb', true))
        """
    )


def upgrade() -> None:
    # ---------- kb_prompt_templates 新增列 ----------
    op.add_column("kb_prompt_templates", sa.Column("scope", sa.String(10), nullable=False, server_default="simple"))
    op.add_column(
        "kb_prompt_templates",
        sa.Column("schema_template_id", UUID(as_uuid=True), sa.ForeignKey("schema_templates.id", ondelete="CASCADE"), nullable=True, index=True),
    )

    # ---------- kb_prompt_categories 子表 ----------
    op.create_table(
        "kb_prompt_categories",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("kb_id", UUID(as_uuid=True), sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("prompt_template_id", UUID(as_uuid=True), sa.ForeignKey("kb_prompt_templates.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("category_id", UUID(as_uuid=True), sa.ForeignKey("schema_configs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("user_prompt", sa.Text, nullable=False, server_default=""),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default=sa.text("0")),
        comment="Prompt 模板类别子表（RLS 按 kb_id）",
    )
    _enable_rls("kb_prompt_categories")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS kb_isolation ON kb_prompt_categories")
    op.execute("ALTER TABLE kb_prompt_categories DISABLE ROW LEVEL SECURITY")
    op.drop_table("kb_prompt_categories")

    op.drop_column("kb_prompt_templates", "schema_template_id")
    op.drop_column("kb_prompt_templates", "scope")