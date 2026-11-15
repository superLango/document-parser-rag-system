"""run repair loop fields

Revision ID: 0009_run_repair
Revises: 0008_run_idem_audit
Create Date: 2026-11-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_run_repair"
down_revision: str | None = "0008_run_idem_audit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("repair_of", sa.String(64), nullable=True))
    op.add_column(
        "runs",
        sa.Column("repair_attempt", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("runs", sa.Column("recipe_override", sa.JSON(), nullable=True))
    op.create_index("ix_runs_repair_of", "runs", ["repair_of"])


def downgrade() -> None:
    op.drop_index("ix_runs_repair_of", table_name="runs")
    op.drop_column("runs", "recipe_override")
    op.drop_column("runs", "repair_attempt")
    op.drop_column("runs", "repair_of")
