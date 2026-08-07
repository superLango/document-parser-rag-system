"""016: Schema 类别新增 rerank_top_k / max_tokens

Revision ID: 016_category_rerank_max_tokens
Revises: 015_rule_groups
Create Date: 2026-08-06

变更：
- schema_configs 表新增：rerank_top_k（类别级重排序 top_n，覆盖全局）、
  max_tokens（类别级 LLM 最大输出 token，覆盖全局）。均可选，未填用全局。
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "016_category_rerank_max_tokens"
down_revision = "015_rule_groups"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("schema_configs", sa.Column("rerank_top_k", sa.Integer(), nullable=True))
    op.add_column("schema_configs", sa.Column("max_tokens", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("schema_configs", "max_tokens")
    op.drop_column("schema_configs", "rerank_top_k")