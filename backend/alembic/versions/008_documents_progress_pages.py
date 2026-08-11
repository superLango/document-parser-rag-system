"""008_documents_progress_pages: documents 增加按页进度字段（progress_page/progress_total）。"""

from alembic import op
import sqlalchemy as sa

revision = "008_documents_progress_pages"
down_revision = "007_documents_pages_cleanup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("progress_page", sa.Integer(), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column("progress_total", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("documents", "progress_total")
    op.drop_column("documents", "progress_page")
