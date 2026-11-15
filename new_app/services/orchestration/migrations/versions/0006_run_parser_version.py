"""pin a parser asset version on a run

Revision ID: 0006_run_parser_version
Revises: 0005_shadow
Create Date: 2026-11-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_run_parser_version"
down_revision: str | None = "0005_shadow"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "runs",
        sa.Column("parser_version", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("runs", "parser_version")
