"""007_documents_pages_cleanup: documents 增加 pages_cleaned_at（U14）。"""

from alembic import op
import sqlalchemy as sa

revision = "007_documents_pages_cleanup"
down_revision = "006_fix_rls_empty_user"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("pages_cleaned_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("documents", "pages_cleaned_at")
