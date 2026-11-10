"""persist document result indexes

Revision ID: g3d4e5f6a7b8
Revises: f2c3d4e5a6b7
Create Date: 2026-10-28 10:30:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'g3d4e5f6a7b8'
down_revision: Union[str, None] = 'f2c3d4e5a6b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'documents',
        sa.Column('results_job_id', sa.String(length=32), nullable=True),
    )
    op.add_column(
        'documents',
        sa.Column('results_synced_at', sa.DateTime(), nullable=True),
    )

    op.create_table(
        'document_items',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('document_id', sa.String(length=32), nullable=False),
        sa.Column('job_id', sa.String(length=32), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('item_index', sa.Integer(), nullable=False),
        sa.Column('item_raw', sa.String(length=255), nullable=False),
        sa.Column('item_canonical', sa.String(length=255), nullable=True),
        sa.Column('item_family', sa.String(length=64), nullable=False),
        sa.Column('facets', sa.JSON(), nullable=False),
        sa.Column('properties', sa.JSON(), nullable=False),
        sa.Column('property_matches', sa.JSON(), nullable=False),
        sa.Column('business_code', sa.String(length=64), nullable=True),
        sa.Column('business_name', sa.String(length=255), nullable=True),
        sa.Column('business_category_code', sa.String(length=64), nullable=True),
        sa.Column('business_category_name', sa.String(length=255), nullable=True),
        sa.Column('match_type', sa.String(length=32), nullable=True),
        sa.Column('method_standard', sa.String(length=255), nullable=True),
        sa.Column('method_code', sa.String(length=64), nullable=True),
        sa.Column('method_name', sa.String(length=255), nullable=True),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'document_id', 'job_id', 'item_index', name='uq_document_item'
        ),
    )
    op.create_index(
        op.f('ix_document_items_document_id'), 'document_items', ['document_id']
    )
    op.create_index(
        op.f('ix_document_items_job_id'), 'document_items', ['job_id']
    )

    op.create_table(
        'document_records',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('document_id', sa.String(length=32), nullable=False),
        sa.Column('job_id', sa.String(length=32), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('record_id', sa.String(length=255), nullable=False),
        sa.Column('source_table_id', sa.String(length=64), nullable=True),
        sa.Column('grade', sa.String(length=128), nullable=True),
        sa.Column('grade_level', sa.String(length=64), nullable=True),
        sa.Column('condition', sa.String(length=255), nullable=True),
        sa.Column('facets', sa.JSON(), nullable=False),
        sa.Column('properties', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'document_id', 'job_id', 'record_id', name='uq_document_record'
        ),
    )
    op.create_index(
        op.f('ix_document_records_document_id'), 'document_records', ['document_id']
    )
    op.create_index(
        op.f('ix_document_records_job_id'), 'document_records', ['job_id']
    )

    op.create_table(
        'document_clauses',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('document_id', sa.String(length=32), nullable=False),
        sa.Column('job_id', sa.String(length=32), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('clause_id', sa.String(length=255), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=True),
        sa.Column('page_no', sa.Integer(), nullable=True),
        sa.Column('kind', sa.String(length=64), nullable=False),
        sa.Column('fields', sa.JSON(), nullable=False),
        sa.Column('applies_to', sa.JSON(), nullable=False),
        sa.Column('evidence', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'document_id', 'job_id', 'clause_id', name='uq_document_clause'
        ),
    )
    op.create_index(
        op.f('ix_document_clauses_document_id'), 'document_clauses', ['document_id']
    )
    op.create_index(
        op.f('ix_document_clauses_job_id'), 'document_clauses', ['job_id']
    )

    op.create_table(
        'evidence_index',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('document_id', sa.String(length=32), nullable=False),
        sa.Column('job_id', sa.String(length=32), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('evidence_id', sa.String(length=255), nullable=False),
        sa.Column('page_no', sa.Integer(), nullable=False),
        sa.Column('table_id', sa.String(length=64), nullable=True),
        sa.Column('row', sa.Integer(), nullable=True),
        sa.Column('col', sa.Integer(), nullable=True),
        sa.Column('quote_text', sa.Text(), nullable=False),
        sa.Column('bbox', sa.JSON(), nullable=True),
        sa.Column('artifact_uri', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'document_id', 'job_id', 'evidence_id', name='uq_evidence_index'
        ),
    )
    op.create_index(
        op.f('ix_evidence_index_document_id'), 'evidence_index', ['document_id']
    )
    op.create_index(
        op.f('ix_evidence_index_job_id'), 'evidence_index', ['job_id']
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_evidence_index_job_id'), table_name='evidence_index')
    op.drop_index(op.f('ix_evidence_index_document_id'), table_name='evidence_index')
    op.drop_table('evidence_index')
    op.drop_index(op.f('ix_document_clauses_job_id'), table_name='document_clauses')
    op.drop_index(
        op.f('ix_document_clauses_document_id'), table_name='document_clauses'
    )
    op.drop_table('document_clauses')
    op.drop_index(op.f('ix_document_records_job_id'), table_name='document_records')
    op.drop_index(
        op.f('ix_document_records_document_id'), table_name='document_records'
    )
    op.drop_table('document_records')
    op.drop_index(op.f('ix_document_items_job_id'), table_name='document_items')
    op.drop_index(
        op.f('ix_document_items_document_id'), table_name='document_items'
    )
    op.drop_table('document_items')

    with op.batch_alter_table('documents') as batch:
        batch.drop_column('results_synced_at')
        batch.drop_column('results_job_id')
