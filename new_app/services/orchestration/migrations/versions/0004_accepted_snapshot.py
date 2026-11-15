"""accepted snapshots

Revision ID: 0004_accepted_snapshot
Revises: 0003_finding_rule
Create Date: 2026-11-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_accepted_snapshot"
down_revision: str | None = "0003_finding_rule"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "accepted_snapshots",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "document_id",
            sa.String(length=64),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("document_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("run_id", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("feedback_id", sa.String(length=64), nullable=True),
        sa.Column("records", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("records_digest", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("accepted_tables", sa.JSON(), nullable=False),
        sa.Column("accepted_fields", sa.JSON(), nullable=False),
        sa.Column("field_digests", sa.JSON(), nullable=False),
        sa.Column("actor", sa.String(length=128), nullable=False, server_default="operator"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("document_id", "records_digest", name="uq_snapshot_doc_digest"),
    )
    op.create_index(
        "ix_accepted_snapshots_document_id", "accepted_snapshots", ["document_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_accepted_snapshots_document_id", table_name="accepted_snapshots")
    op.drop_table("accepted_snapshots")
