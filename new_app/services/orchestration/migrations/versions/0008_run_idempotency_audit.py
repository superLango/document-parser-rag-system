"""run idempotency key and audit events

Revision ID: 0008_run_idem_audit
Revises: 0007_shadow_deadline
Create Date: 2026-11-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_run_idem_audit"
down_revision: str | None = "0007_shadow_deadline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("idempotency_key", sa.String(64), nullable=True))
    op.create_index(
        "ix_runs_idempotency_key", "runs", ["idempotency_key"], unique=True
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("type", sa.String(64), nullable=False),
        sa.Column("subject_type", sa.String(64), nullable=False),
        sa.Column("subject_id", sa.String(128), nullable=False),
        sa.Column("actor", sa.String(128), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_events_type", "audit_events", ["type"])
    op.create_index("ix_audit_events_subject_id", "audit_events", ["subject_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_events_subject_id", table_name="audit_events")
    op.drop_index("ix_audit_events_type", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index("ix_runs_idempotency_key", table_name="runs")
    op.drop_column("runs", "idempotency_key")
