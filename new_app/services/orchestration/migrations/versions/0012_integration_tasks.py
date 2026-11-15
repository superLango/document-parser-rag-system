"""integration tasks

Revision ID: 0012_integration_tasks
Revises: 0011_standard_index
Create Date: 2026-11-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_integration_tasks"
down_revision: str | None = "0011_standard_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "integration_tasks",
        sa.Column("task_id", sa.String(length=64), nullable=False),
        sa.Column("kb_id", sa.String(length=64), nullable=True),
        sa.Column("prompt_id", sa.String(length=64), nullable=True),
        sa.Column("document_id", sa.String(length=64), nullable=False),
        sa.Column("schema_template_id", sa.String(length=64), nullable=True),
        sa.Column("filename", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["document_id"], ["documents.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("task_id"),
    )
    op.create_index(
        "ix_integration_tasks_document_id",
        "integration_tasks",
        ["document_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_integration_tasks_document_id", table_name="integration_tasks")
    op.drop_table("integration_tasks")
