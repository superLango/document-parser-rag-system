"""document review status and versions

Revision ID: c3a9d5e7f1b2
Revises: 541ff3a3dca6
Create Date: 2026-10-27 23:30:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c3a9d5e7f1b2'
down_revision: Union[str, None] = '541ff3a3dca6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'documents',
        sa.Column('review_status', sa.String(length=16), nullable=False, server_default='draft'),
    )
    op.add_column(
        'documents',
        sa.Column('review_version', sa.Integer(), nullable=False, server_default='1'),
    )
    op.add_column(
        'documents',
        sa.Column('confirmed_job_id', sa.String(length=32), nullable=True),
    )
    op.add_column(
        'documents',
        sa.Column('confirmed_by', sa.String(length=32), nullable=True),
    )
    op.add_column(
        'documents',
        sa.Column('confirmed_at', sa.DateTime(), nullable=True),
    )
    op.add_column(
        'document_tasks',
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
    )


def downgrade() -> None:
    with op.batch_alter_table('document_tasks') as batch:
        batch.drop_column('version')
    with op.batch_alter_table('documents') as batch:
        batch.drop_column('confirmed_at')
        batch.drop_column('confirmed_by')
        batch.drop_column('confirmed_job_id')
        batch.drop_column('review_version')
        batch.drop_column('review_status')
