"""013_extraction_rulegroup_fix: rule_groups 补充 schema_template_id/description。

对齐原项目：规则组绑定 Schema 模板（一个模板至多一个规则组）。
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PgUUID

from alembic import op

revision = "013_extraction_rulegroup_fix"
down_revision = "012_extraction_config"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "rule_groups",
        sa.Column("schema_template_id", PgUUID(as_uuid=True), sa.ForeignKey("schema_templates.id", ondelete="SET NULL"), nullable=True),
    )
    op.add_column(
        "rule_groups",
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
    )
    op.create_index("idx_rule_groups_template", "rule_groups", ["kb_id", "schema_template_id"])


def downgrade() -> None:
    op.drop_index("idx_rule_groups_template", table_name="rule_groups")
    op.drop_column("rule_groups", "description")
    op.drop_column("rule_groups", "schema_template_id")
