"""014_rule_item_script_binding: rule_group_items 对齐原项目（script_id/stage）。

原项目规则项绑定脚本（script_id）并区分阶段（post/validation）；
移除自由填写 script_name 列（数据由脚本表解析）。
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PgUUID

from alembic import op

revision = "014_rule_item_script_binding"
down_revision = "013_extraction_rulegroup_fix"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "rule_group_items",
        sa.Column("script_id", PgUUID(as_uuid=True), sa.ForeignKey("kb_scripts.id", ondelete="SET NULL"), nullable=True),
    )
    op.add_column(
        "rule_group_items",
        sa.Column("stage", sa.String(16), nullable=False, server_default="post"),
    )
    op.add_column(
        "rule_group_items",
        sa.Column("category_name", sa.String(128), nullable=False, server_default=""),
    )
    op.drop_column("rule_group_items", "script_name")
    op.create_index("idx_rule_group_items_script", "rule_group_items", ["kb_id", "script_id"])


def downgrade() -> None:
    op.drop_index("idx_rule_group_items_script", table_name="rule_group_items")
    op.add_column(
        "rule_group_items",
        sa.Column("script_name", sa.String(128), nullable=False, server_default=""),
    )
    op.drop_column("rule_group_items", "category_name")
    op.drop_column("rule_group_items", "stage")
    op.drop_column("rule_group_items", "script_id")
