"""010: Schema 类别新增名称来源与 Query 术语集配置

Revision ID: 010_schema_category_name_query
Revises: 009_unified_term_bases
Create Date: 2026-08-05

变更：
- schema_configs 表新增：name_source, name_term_base_id, name_term_field, query_sources
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON, VARCHAR, UUID

# revision identifiers
revision = "010_schema_category_name_query"
down_revision = "009_unified_term_bases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("schema_configs", sa.Column("name_source", VARCHAR(10), nullable=False, server_default="manual"))
    op.add_column("schema_configs", sa.Column("name_term_base_id", UUID(as_uuid=True), nullable=True))
    op.add_column("schema_configs", sa.Column("name_term_field", VARCHAR(100), nullable=True))
    op.add_column("schema_configs", sa.Column("query_sources", JSON, nullable=False, server_default=sa.text("'[]'::json")))


def downgrade() -> None:
    op.drop_column("schema_configs", "query_sources")
    op.drop_column("schema_configs", "name_term_field")
    op.drop_column("schema_configs", "name_term_base_id")
    op.drop_column("schema_configs", "name_source")