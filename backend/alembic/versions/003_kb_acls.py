"""003_kb_acls: 知识库资源级 ACL（P1）。

- kb_members 扩展：status / invited_by / expires_at
- 新增 kb_invitations：邀请令牌与状态
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "003_kb_acls"
down_revision = "002_rbac"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "kb_members",
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
    )
    op.add_column(
        "kb_members",
        sa.Column(
            "invited_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "kb_members",
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_kb_members_status", "kb_members", ["status"])

    op.create_table(
        "kb_invitations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("token", sa.String(64), nullable=False),
        sa.Column(
            "kb_id",
            UUID(as_uuid=True),
            sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "inviter_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=False,
        ),
        sa.Column(
            "invitee_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "member_id",
            UUID(as_uuid=True),
            sa.ForeignKey("kb_members.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_kb_invitations_token", "kb_invitations", ["token"], unique=True)
    op.create_index("ix_kb_invitations_kb_id", "kb_invitations", ["kb_id"])
    op.create_index("ix_kb_invitations_invitee_id", "kb_invitations", ["invitee_id"])


def downgrade() -> None:
    op.drop_table("kb_invitations")
    op.drop_index("ix_kb_members_status", table_name="kb_members")
    op.drop_column("kb_members", "expires_at")
    op.drop_column("kb_members", "invited_by")
    op.drop_column("kb_members", "status")
