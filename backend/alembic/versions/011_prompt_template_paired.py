"""011: Prompt 模板初步改造（system / user 分级拆分）

Revision ID: 011_prompt_template_paired
Revises: 010_schema_category_name_query
Create Date: 2026-08-05

变更（已应用，用于对齐 alembic 版本链）：
- kb_prompt_templates 表：新增 system_prompt / user_prompt / usage，
  移除旧的 template_type / content（重建为 system/user 两级结构）
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "011_prompt_template_paired"
down_revision = "010_schema_category_name_query"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 兼容已应用状态：若列不存在则补充（幂等）
    cols = {r[0] for r in op.get_bind().execute(sa.text(
        "SELECT column_name FROM information_schema.columns WHERE table_name='kb_prompt_templates'"
    ))}
    if "usage" not in cols:
        op.add_column("kb_prompt_templates", sa.Column("usage", sa.String(30), nullable=False, server_default="category"))
    if "system_prompt" not in cols:
        op.add_column("kb_prompt_templates", sa.Column("system_prompt", sa.Text, nullable=False, server_default=""))
    if "user_prompt" not in cols:
        op.add_column("kb_prompt_templates", sa.Column("user_prompt", sa.Text, nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("kb_prompt_templates", "user_prompt")
    op.drop_column("kb_prompt_templates", "system_prompt")
    op.drop_column("kb_prompt_templates", "usage")