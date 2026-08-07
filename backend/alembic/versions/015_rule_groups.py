"""015: 规则组表 kb_rule_groups / kb_rule_group_items

Revision ID: 015_rule_groups
Revises: 014_extraction_scripts
Create Date: 2026-08-06

变更：
- 新建 kb_rule_groups：规则组（一个 Schema 模板对应一个规则组）。
- 新建 kb_rule_group_items：规则组内类别下的规则项，引用 kb_scripts 脚本，
  stage 仅标记归属（post/validation），sort_order 在同类别内跨 stage 统一排序
  （后处理与校验可交叉）。
- 两表均启用 RLS（kb_id 隔离）。
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision = "015_rule_groups"
down_revision = "014_extraction_scripts"
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


def _disable_rls(table: str) -> None:
    op.execute(f"DROP POLICY IF EXISTS kb_isolation ON {table}")
    op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")


def upgrade() -> None:
    # ---------- kb_rule_groups ----------
    op.create_table(
        "kb_rule_groups",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("kb_id", UUID(as_uuid=True), sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("name", sa.String(100), nullable=True),
        sa.Column("schema_template_id", UUID(as_uuid=True), sa.ForeignKey("schema_templates.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("kb_id", "schema_template_id", name="uq_kb_rule_groups_kb_template"),
        comment="规则组表（RLS 按 kb_id）",
    )
    _enable_rls("kb_rule_groups")

    # ---------- kb_rule_group_items ----------
    op.create_table(
        "kb_rule_group_items",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("kb_id", UUID(as_uuid=True), sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("rule_group_id", UUID(as_uuid=True), sa.ForeignKey("kb_rule_groups.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("category_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("category_name", sa.String(100), nullable=False),
        sa.Column("script_id", UUID(as_uuid=True), sa.ForeignKey("kb_scripts.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("stage", sa.String(20), nullable=False, server_default="post"),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("rule_group_id", "category_id", "script_id", "stage", name="uq_kb_rule_group_items_g_cat_script_stage"),
        comment="规则组类别规则项表（RLS 按 kb_id）",
    )
    _enable_rls("kb_rule_group_items")


def downgrade() -> None:
    _disable_rls("kb_rule_group_items")
    op.drop_table("kb_rule_group_items")
    _disable_rls("kb_rule_groups")
    op.drop_table("kb_rule_groups")