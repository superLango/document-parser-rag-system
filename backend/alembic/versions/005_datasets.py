"""抽取数据集：kb_datasets + kb_dataset_entries 新表。

Revision ID: 005_datasets
Revises: 004_term_bases
Create Date: 2026-08-04

新增表：
- kb_datasets：数据集元数据（三表抽象化，RLS 按 kb_id）
- kb_dataset_entries：数据集条目（冗余 kb_id 便于 RLS 直接隔离）

设计要点：
- kb_datasets 直接含 kb_id 列，启用 RLS + kb_isolation 策略。
- kb_dataset_entries 直接含 kb_id 列，启用 RLS + kb_isolation 策略。
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision = "005_datasets"
down_revision = "004_term_bases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---------- kb_datasets 表 ----------
    op.create_table(
        "kb_datasets",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("kb_id", UUID(as_uuid=True), sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("role", sa.String(20), nullable=False, index=True),
        sa.Column("source_type", sa.String(20), nullable=False),
        sa.Column("source_config", sa.JSON, nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("field_defs", sa.JSON, nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("column_aliases", sa.JSON, nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("cache_policy", sa.JSON, nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("kb_id", "name", name="uq_kb_datasets_kb_name"),
        comment="数据集元数据表（RLS 按 kb_id）",
    )

    # ---------- kb_dataset_entries 表 ----------
    op.create_table(
        "kb_dataset_entries",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("dataset_id", UUID(as_uuid=True), sa.ForeignKey("kb_datasets.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("kb_id", UUID(as_uuid=True), sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("group_key", sa.String(200), nullable=False, index=True),
        sa.Column("value", sa.String(500), nullable=False),
        sa.Column("aliases", sa.JSON, nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("unit", sa.String(50), nullable=True),
        sa.Column("extras", sa.JSON, nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("dataset_id", "group_key", "value", name="uq_kb_dataset_entries_ds_group_value"),
        comment="数据集条目表（RLS 按 kb_id）",
    )

    # ---------- 启用 RLS ----------
    op.execute("ALTER TABLE kb_datasets ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY kb_isolation ON kb_datasets
        FOR ALL
        USING (kb_id::text = current_setting('app.current_kb', true))
        WITH CHECK (kb_id::text = current_setting('app.current_kb', true))
        """
    )

    op.execute("ALTER TABLE kb_dataset_entries ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY kb_isolation ON kb_dataset_entries
        FOR ALL
        USING (kb_id::text = current_setting('app.current_kb', true))
        WITH CHECK (kb_id::text = current_setting('app.current_kb', true))
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS kb_isolation ON kb_dataset_entries")
    op.execute("ALTER TABLE kb_dataset_entries DISABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS kb_isolation ON kb_datasets")
    op.execute("ALTER TABLE kb_datasets DISABLE ROW LEVEL SECURITY")

    op.drop_table("kb_dataset_entries")
    op.drop_table("kb_datasets")