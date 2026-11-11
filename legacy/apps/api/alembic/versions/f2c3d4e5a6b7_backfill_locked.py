"""backfill locked tasks for confirmed documents

Revision ID: f2c3d4e5a6b7
Revises: e1b2c3d4f5a6
Create Date: 2026-10-28 00:05:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = 'f2c3d4e5a6b7'
down_revision: Union[str, None] = 'e1b2c3d4f5a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "UPDATE document_tasks SET locked = TRUE "
        "WHERE job_id IN ("
        "SELECT confirmed_job_id FROM documents "
        "WHERE confirmed_job_id IS NOT NULL)"
    )


def downgrade() -> None:
    op.execute("UPDATE document_tasks SET locked = FALSE")
