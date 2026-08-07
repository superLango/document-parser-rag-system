"""术语集功能：term_bases 新表 + terms 新字段。

Revision ID: 004_term_bases
Revises: 003_phase2_rls
Create Date: 2026-08-03

新增表：
- term_bases：术语集表（管理专业术语集合，RLS 按 kb_id）

修改表：
- terms +term_base_id：关联术语集（外键，可为空，CASCADE 删除）
- terms +aliases：术语别称列表（JSON 字段）
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision = "004_term_bases"
down_revision = "003_phase2_rls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---------- term_bases 表 ----------
    op.create_table(
        "term_bases",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("kb_id", UUID(as_uuid=True), sa.ForeignKey("knowledge_bases.id"), nullable=False, index=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        comment="术语集表（RLS 按 kb_id）",
    )

    # ---------- terms 表新增字段 ----------
    op.add_column(
        "terms",
        sa.Column(
            "term_base_id",
            UUID(as_uuid=True),
            sa.ForeignKey("term_bases.id", ondelete="CASCADE"),
            nullable=True,
            index=True,
        ),
    )
    op.add_column(
        "terms",
        sa.Column("aliases", sa.JSON, nullable=True, comment="术语别称列表"),
    )

    # ---------- term_bases 启用 RLS ----------
    op.execute("ALTER TABLE term_bases ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY kb_isolation ON term_bases
        FOR ALL USING (kb_id::text = current_setting('app.current_kb', true))
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS kb_isolation ON term_bases")
    op.drop_column("terms", "aliases")
    op.drop_constraint("terms_term_base_id_fkey", "terms", type_="foreignkey")
    op.drop_column("terms", "term_base_id")
    op.drop_table("term_bases")
