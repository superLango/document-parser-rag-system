"""013: 统一规则表 kb_rules（合并抽取规则 + 验证规则）

Revision ID: 013_unified_rules
Revises: 012_prompt_scope_categories
Create Date: 2026-08-05

变更：
- 新建 kb_rules：统一规则表，用 stage（post/validation）区分后处理与校验，
  支持类别/字段级作用域绑定（scope）。
- 数据迁移：kb_extraction_rules → kb_rules(stage=post)，
  kb_validation_rules → kb_rules(stage=validation)。
- 废弃并删除 kb_extraction_rules / kb_validation_rules 两张旧表。
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

# revision identifiers, used by Alembic.
revision = "013_unified_rules"
down_revision = "012_prompt_scope_categories"
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
    # ---------- 新建 kb_rules 表 ----------
    op.create_table(
        "kb_rules",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("kb_id", UUID(as_uuid=True), sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("stage", sa.String(20), nullable=False, server_default="post"),
        sa.Column("rule_key", sa.String(64), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("scope", JSONB, nullable=False, server_default=sa.text("'{\"type\": \"global\"}'::jsonb")),
        sa.Column("params", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("kb_id", "stage", "rule_key", "scope", name="uq_kb_rules_kb_stage_key_scope"),
        comment="统一规则表（RLS 按 kb_id）",
    )
    _enable_rls("kb_rules")

    # ---------- 数据迁移：后处理规则 ----------
    op.execute(
        """
        INSERT INTO kb_rules (id, kb_id, stage, rule_key, name, description,
                              enabled, sort_order, scope, params, created_at, updated_at)
        SELECT id, kb_id, 'post', rule_key, name, description,
               enabled, sort_order, '{"type": "global"}'::json, params, created_at, updated_at
        FROM kb_extraction_rules
        """
    )
    # ---------- 数据迁移：验证规则 ----------
    op.execute(
        """
        INSERT INTO kb_rules (id, kb_id, stage, rule_key, name, description,
                              enabled, sort_order, scope, params, created_at, updated_at)
        SELECT id, kb_id, 'validation', rule_key, name, description,
               enabled, sort_order, '{"type": "global"}'::json, config, created_at, updated_at
        FROM kb_validation_rules
        """
    )

    # ---------- 废弃旧表 ----------
    _disable_rls("kb_validation_rules")
    op.drop_table("kb_validation_rules")
    _disable_rls("kb_extraction_rules")
    op.drop_table("kb_extraction_rules")


def downgrade() -> None:
    # 重建旧两张表并回迁数据
    op.create_table(
        "kb_extraction_rules",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("kb_id", UUID(as_uuid=True), sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("stage", sa.String(10), nullable=False, server_default="post"),
        sa.Column("rule_key", sa.String(64), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("params", sa.JSON, nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("kb_id", "rule_key", name="uq_kb_extraction_rules_kb_key"),
    )
    op.create_table(
        "kb_validation_rules",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("kb_id", UUID(as_uuid=True), sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("rule_key", sa.String(64), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("config", sa.JSON, nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("kb_id", "rule_key", name="uq_kb_validation_rules_kb_key"),
    )
    op.execute(
        """
        INSERT INTO kb_extraction_rules (id, kb_id, stage, rule_key, name, description,
                                         enabled, sort_order, params, created_at, updated_at)
        SELECT id, kb_id, stage, rule_key, name, description,
               enabled, sort_order, params, created_at, updated_at
        FROM kb_rules WHERE stage = 'post'
        """
    )
    op.execute(
        """
        INSERT INTO kb_validation_rules (id, kb_id, rule_key, name, description,
                                         enabled, sort_order, config, created_at, updated_at)
        SELECT id, kb_id, rule_key, name, description,
               enabled, sort_order, params, created_at, updated_at
        FROM kb_rules WHERE stage = 'validation'
        """
    )
    _disable_rls("kb_rules")
    op.drop_table("kb_rules")
    _enable_rls("kb_extraction_rules")
    _enable_rls("kb_validation_rules")