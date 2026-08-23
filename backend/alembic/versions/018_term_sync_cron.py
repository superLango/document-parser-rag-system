"""018_term_sync_cron: 术语集按 cron 表达式定时同步。

- term_bases 新增 sync_cron（5 段 cron）/ sync_next_run_at / sync_status / sync_last_error；
- 不修改存量 sync_enabled（由用户自行配置）；
- RLS 沿用既有策略，无需变更。
"""

import sqlalchemy as sa
from alembic import op

revision = "018_term_sync_cron"
down_revision = "017_category_special_req"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("term_bases", sa.Column("sync_cron", sa.String(64), nullable=False, server_default=""))
    op.add_column("term_bases", sa.Column("sync_next_run_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "term_bases",
        sa.Column("sync_status", sa.String(16), nullable=False, server_default="idle"),
    )
    op.add_column("term_bases", sa.Column("sync_last_error", sa.Text(), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("term_bases", "sync_last_error")
    op.drop_column("term_bases", "sync_status")
    op.drop_column("term_bases", "sync_next_run_at")
    op.drop_column("term_bases", "sync_cron")
