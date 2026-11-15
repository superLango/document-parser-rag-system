"""shadow batch deadline

Revision ID: 0007_shadow_deadline
Revises: 0006_run_parser_version
Create Date: 2026-11-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_shadow_deadline"
down_revision: str | None = "0006_run_parser_version"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "shadow_batches",
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("shadow_batches", "deadline_at")
