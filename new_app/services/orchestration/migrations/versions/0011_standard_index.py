"""standard index

Revision ID: 0011_standard_index
Revises: 0010_run_progress
Create Date: 2026-11-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_standard_index"
down_revision: str | None = "0010_run_progress"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "standard_index",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("document_id", sa.String(length=64), nullable=False),
        sa.Column("standard_no", sa.String(length=64), nullable=True),
        sa.Column("edition", sa.String(length=8), nullable=True),
        sa.Column("title", sa.String(length=256), nullable=True),
        sa.Column("source_kind", sa.String(length=16), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("categories", sa.JSON(), nullable=True),
        sa.Column("grades", sa.JSON(), nullable=True),
        sa.Column("latest_run_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["document_id"], ["documents.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", name="uq_standard_index_document"),
    )
    op.create_index(
        "ix_standard_index_document_id", "standard_index", ["document_id"]
    )
    op.create_index(
        "ix_standard_index_standard_no", "standard_index", ["standard_no"]
    )


def downgrade() -> None:
    op.drop_index("ix_standard_index_standard_no", table_name="standard_index")
    op.drop_index("ix_standard_index_document_id", table_name="standard_index")
    op.drop_table("standard_index")
