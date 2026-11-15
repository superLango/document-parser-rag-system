"""shadow documents, batches and results

Revision ID: 0005_shadow
Revises: 0004_accepted_snapshot
Create Date: 2026-11-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_shadow"
down_revision: str | None = "0004_accepted_snapshot"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "shadow_documents",
        sa.Column(
            "document_id",
            sa.String(length=64),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("added_by", sa.String(length=128), nullable=False, server_default="operator"),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "shadow_batches",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("recipe_id", sa.String(length=128), nullable=False),
        sa.Column("from_version", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("candidate_version", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("feedback_id", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("required_documents", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("completed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("actor", sa.String(length=128), nullable=False, server_default="operator"),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_shadow_batches_recipe_id", "shadow_batches", ["recipe_id"])
    op.create_index("ix_shadow_batches_status", "shadow_batches", ["status"])
    op.create_index("ix_shadow_batches_feedback_id", "shadow_batches", ["feedback_id"])
    op.create_table(
        "shadow_results",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "batch_id",
            sa.String(length=64),
            sa.ForeignKey("shadow_batches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("document_id", sa.String(length=64), nullable=False),
        sa.Column("stable_run_id", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("shadow_run_id", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("passed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("batch_id", "document_id", name="uq_shadow_batch_document"),
    )
    op.create_index("ix_shadow_results_batch_id", "shadow_results", ["batch_id"])
    op.create_index("ix_shadow_results_document_id", "shadow_results", ["document_id"])
    op.alter_column(
        "promotions",
        "feedback_id",
        existing_type=sa.String(length=64),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "promotions",
        "feedback_id",
        existing_type=sa.String(length=64),
        nullable=False,
    )
    op.drop_index("ix_shadow_results_document_id", table_name="shadow_results")
    op.drop_index("ix_shadow_results_batch_id", table_name="shadow_results")
    op.drop_table("shadow_results")
    op.drop_index("ix_shadow_batches_feedback_id", table_name="shadow_batches")
    op.drop_index("ix_shadow_batches_status", table_name="shadow_batches")
    op.drop_index("ix_shadow_batches_recipe_id", table_name="shadow_batches")
    op.drop_table("shadow_batches")
    op.drop_table("shadow_documents")
