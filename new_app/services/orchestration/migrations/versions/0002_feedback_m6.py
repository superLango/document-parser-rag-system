"""feedback M6 fields and promotions audit

Revision ID: 0002_feedback_m6
Revises: 0001_initial
Create Date: 2026-11-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_feedback_m6"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("feedback", sa.Column("dedupe_key", sa.String(length=64), nullable=True))
    op.add_column("feedback", sa.Column("messages", sa.JSON(), nullable=True))
    op.add_column("feedback", sa.Column("triage", sa.JSON(), nullable=True))
    op.add_column("feedback", sa.Column("proposal", sa.JSON(), nullable=True))
    op.add_column("feedback", sa.Column("verification", sa.JSON(), nullable=True))
    op.add_column("feedback", sa.Column("candidate", sa.JSON(), nullable=True))
    op.add_column(
        "feedback",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_feedback_dedupe_key", "feedback", ["dedupe_key"], unique=True
    )

    op.create_table(
        "promotions",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("feedback_id", sa.String(length=64), nullable=False),
        sa.Column("recipe_id", sa.String(length=128), nullable=False),
        sa.Column("from_version", sa.String(length=32), nullable=False),
        sa.Column("to_version", sa.String(length=32), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("actor", sa.String(length=128), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["feedback_id"], ["feedback.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_promotions_feedback_id", "promotions", ["feedback_id"])


def downgrade() -> None:
    op.drop_index("ix_promotions_feedback_id", table_name="promotions")
    op.drop_table("promotions")
    op.drop_index("ix_feedback_dedupe_key", table_name="feedback")
    op.drop_column("feedback", "updated_at")
    op.drop_column("feedback", "candidate")
    op.drop_column("feedback", "verification")
    op.drop_column("feedback", "proposal")
    op.drop_column("feedback", "triage")
    op.drop_column("feedback", "messages")
    op.drop_column("feedback", "dedupe_key")
