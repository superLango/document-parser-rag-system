"""finding rule id and message

Revision ID: 0003_finding_rule
Revises: 0002_feedback_m6
Create Date: 2026-11-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_finding_rule"
down_revision: str | None = "0002_feedback_m6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("findings", sa.Column("message", sa.Text(), nullable=True))
    op.add_column(
        "findings",
        sa.Column("rule_id", sa.String(length=64), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("findings", "rule_id")
    op.drop_column("findings", "message")
