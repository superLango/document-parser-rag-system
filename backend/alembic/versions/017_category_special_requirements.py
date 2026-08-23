"""017_category_special_requirements: schema_categories 术语类别特殊要求。

- schema_categories 新增 special_requirements JSONB（默认 {}）：
  按展开类别名（如「室温拉伸」）映射特殊要求文本，供 Prompt ${special_requirement} 组装；
- 仅加列，不涉及 RLS 变更（沿用 012 既有策略）。
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "017_category_special_req"
down_revision = "016_extraction_result"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "schema_categories",
        sa.Column("special_requirements", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    )


def downgrade() -> None:
    op.drop_column("schema_categories", "special_requirements")
