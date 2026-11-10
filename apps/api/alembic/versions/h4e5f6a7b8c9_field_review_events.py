"""field review events

Revision ID: h4e5f6a7b8c9
Revises: g3d4e5f6a7b8
Create Date: 2026-10-29

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'h4e5f6a7b8c9'
down_revision: Union[str, None] = 'g3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'field_review_events',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('document_id', sa.String(length=32), nullable=False),
        sa.Column('job_id', sa.String(length=32), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('field_path', sa.String(length=255), nullable=False),
        sa.Column('action', sa.String(length=16), nullable=False),
        sa.Column('old_value', sa.JSON(), nullable=False),
        sa.Column('new_value', sa.JSON(), nullable=True),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('reviewer', sa.String(length=32), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_field_review_events_document_id'),
        'field_review_events',
        ['document_id'],
        unique=False,
    )
    op.create_index(
        op.f('ix_field_review_events_job_id'),
        'field_review_events',
        ['job_id'],
        unique=False,
    )
    op.create_index(
        op.f('ix_field_review_events_reviewer'),
        'field_review_events',
        ['reviewer'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_field_review_events_reviewer'), table_name='field_review_events')
    op.drop_index(op.f('ix_field_review_events_job_id'), table_name='field_review_events')
    op.drop_index(op.f('ix_field_review_events_document_id'), table_name='field_review_events')
    op.drop_table('field_review_events')
