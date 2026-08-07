"""014: 自定义处理脚本表 kb_scripts（类似 magic-api 脚本即接口）

Revision ID: 014_extraction_scripts
Revises: 013_unified_rules
Create Date: 2026-08-05

变更：
- 新建 kb_scripts：按目录（pre/post/validation）管理用户自定义处理脚本，
  存储脚本源码、自定义参数定义、启用与排序，RLS 按 kb_id 隔离。
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

# revision identifiers, used by Alembic.
revision = "014_extraction_scripts"
down_revision = "013_unified_rules"
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
    op.create_table(
        "kb_scripts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("kb_id", UUID(as_uuid=True), sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("folder", sa.String(20), nullable=False, server_default="post"),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("code", sa.Text, nullable=False, server_default=""),
        sa.Column("params_schema", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("kb_id", "folder", "name", name="uq_kb_scripts_kb_folder_name"),
        comment="自定义处理脚本表（RLS 按 kb_id）",
    )
    _enable_rls("kb_scripts")


def downgrade() -> None:
    _disable_rls("kb_scripts")
    op.drop_table("kb_scripts")