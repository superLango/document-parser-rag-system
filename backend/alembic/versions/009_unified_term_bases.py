"""009: 统一术语集 - term_bases 添加数据源支持，terms 添加 extras

Revision ID: 009_unified_term_bases
Revises: 008_schema_config_rls
Create Date: 2026-08-04

变更：
- term_bases 表：添加 source_type, source_config, columns, column_aliases, sync_enabled, last_synced_at 字段
- terms 表：添加 extras 字段用于存储动态列数据
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON, BOOLEAN, VARCHAR, TIMESTAMP

# revision identifiers
revision = "009_unified_term_bases"
down_revision = "008_schema_config_rls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # term_bases 新增字段
    op.add_column("term_bases", sa.Column("source_type", VARCHAR(20), nullable=False, server_default="manual"))
    op.add_column("term_bases", sa.Column("source_config", JSON, nullable=False, server_default=sa.text("'{}'::json")))
    op.add_column("term_bases", sa.Column("columns", JSON, nullable=False, server_default=sa.text("'[]'::json")))
    op.add_column("term_bases", sa.Column("column_aliases", JSON, nullable=False, server_default=sa.text("'{}'::json")))
    op.add_column("term_bases", sa.Column("sync_enabled", BOOLEAN, nullable=False, server_default=sa.text("false")))
    op.add_column("term_bases", sa.Column("last_synced_at", TIMESTAMP(timezone=True), nullable=True))
    op.create_index("ix_term_bases_source_type", "term_bases", ["source_type"])

    # terms 新增 extras 字段
    op.add_column("terms", sa.Column("extras", JSON, nullable=False, server_default=sa.text("'{}'::json")))


def downgrade() -> None:
    op.drop_index("ix_term_bases_source_type", table_name="term_bases")
    op.drop_column("term_bases", "last_synced_at")
    op.drop_column("term_bases", "sync_enabled")
    op.drop_column("term_bases", "column_aliases")
    op.drop_column("term_bases", "columns")
    op.drop_column("term_bases", "source_config")
    op.drop_column("term_bases", "source_type")
    op.drop_column("terms", "extras")
