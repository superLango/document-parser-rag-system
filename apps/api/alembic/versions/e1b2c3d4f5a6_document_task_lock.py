"""document task lock for confirmed versions

Revision ID: e1b2c3d4f5a6
Revises: c3a9d5e7f1b2
Create Date: 2026-10-27 23:55:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e1b2c3d4f5a6'
down_revision: Union[str, None] = 'c3a9d5e7f1b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'document_tasks',
        sa.Column('locked', sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    with op.batch_alter_table('document_tasks') as batch:
        batch.drop_column('locked')
