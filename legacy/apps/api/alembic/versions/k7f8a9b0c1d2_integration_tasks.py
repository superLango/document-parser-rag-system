"""integration tasks

Revision ID: k7f8a9b0c1d2
Revises: j6e7f8a9b0c1
Create Date: 2026-11-10

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "k7f8a9b0c1d2"
down_revision: Union[str, None] = "j6e7f8a9b0c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "integration_tasks",
        sa.Column("task_id", sa.String(length=36), primary_key=True),
        sa.Column(
            "kb_id",
            sa.String(length=32),
            sa.ForeignKey("knowledge_bases.id"),
            nullable=False,
        ),
        sa.Column(
            "document_id",
            sa.String(length=32),
            sa.ForeignKey("documents.id"),
            nullable=True,
        ),
        sa.Column("prompt_id", sa.String(length=36), nullable=True),
        sa.Column("schema_template_id", sa.String(length=36), nullable=True),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("ocr_status", sa.String(length=16), nullable=False),
        sa.Column("ocr_progress", sa.Integer(), nullable=False),
        sa.Column("extract_status", sa.String(length=16), nullable=False),
        sa.Column("extract_progress", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("result_version", sa.Integer(), nullable=True),
        sa.Column(
            "created_by",
            sa.String(length=32),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_integration_tasks_kb_id", "integration_tasks", ["kb_id"])
    op.create_index(
        "ix_integration_tasks_document_id", "integration_tasks", ["document_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_integration_tasks_document_id", table_name="integration_tasks")
    op.drop_index("ix_integration_tasks_kb_id", table_name="integration_tasks")
    op.drop_table("integration_tasks")
