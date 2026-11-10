"""workspaces, members, invitations and workspace-scoped keys

Revision ID: i5f6a7b8c9d0
Revises: h4e5f6a7b8c9
Create Date: 2026-10-31

"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "i5f6a7b8c9d0"
down_revision: Union[str, None] = "h4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def upgrade() -> None:
    op.create_table(
        "workspaces",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("owner_id", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_workspaces_owner_id"), "workspaces", ["owner_id"], unique=False
    )

    op.create_table(
        "workspace_members",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "user_id", name="uq_workspace_member"),
    )
    op.create_index(
        op.f("ix_workspace_members_workspace_id"),
        "workspace_members",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_workspace_members_user_id"),
        "workspace_members",
        ["user_id"],
        unique=False,
    )

    op.create_table(
        "invitations",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("invited_by", sa.String(length=32), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("note", sa.String(length=255), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(), nullable=True),
        sa.Column("accepted_by", sa.String(length=32), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.ForeignKeyConstraint(["invited_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["accepted_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_invitations_workspace_id"),
        "invitations",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_invitations_invited_by"),
        "invitations",
        ["invited_by"],
        unique=False,
    )
    op.create_index(
        op.f("ix_invitations_token_hash"),
        "invitations",
        ["token_hash"],
        unique=True,
    )

    op.add_column(
        "knowledge_bases",
        sa.Column("workspace_id", sa.String(length=32), nullable=True),
    )
    op.create_index(
        op.f("ix_knowledge_bases_workspace_id"),
        "knowledge_bases",
        ["workspace_id"],
        unique=False,
    )
    op.add_column(
        "api_keys",
        sa.Column("workspace_id", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "api_keys",
        sa.Column("kb_ids", sa.Text(), nullable=False, server_default=""),
    )
    op.create_index(
        op.f("ix_api_keys_workspace_id"), "api_keys", ["workspace_id"], unique=False
    )
    op.add_column(
        "audit_logs",
        sa.Column(
            "workspace_id",
            sa.String(length=32),
            nullable=False,
            server_default="",
        ),
    )
    op.create_index(
        op.f("ix_audit_logs_workspace_id"),
        "audit_logs",
        ["workspace_id"],
        unique=False,
    )

    bind = op.get_bind()
    users = bind.execute(
        sa.text("SELECT id, username, display_name FROM users")
    ).mappings().all()
    default_workspace: dict[str, str] = {}
    for user in users:
        workspace_id = uuid.uuid4().hex
        default_workspace[user["id"]] = workspace_id
        name = f"默认工作空间 {user['display_name'] or user['username']}"[:128]
        bind.execute(
            sa.text(
                "INSERT INTO workspaces "
                "(id, name, description, owner_id, created_at, deleted_at) "
                "VALUES (:id, :name, '', :owner_id, :created_at, NULL)"
            ),
            {
                "id": workspace_id,
                "name": name,
                "owner_id": user["id"],
                "created_at": _now(),
            },
        )
        bind.execute(
            sa.text(
                "INSERT INTO workspace_members "
                "(id, workspace_id, user_id, role, created_at) "
                "VALUES (:id, :workspace_id, :user_id, 'owner', :created_at)"
            ),
            {
                "id": uuid.uuid4().hex,
                "workspace_id": workspace_id,
                "user_id": user["id"],
                "created_at": _now(),
            },
        )

    for kb in bind.execute(
        sa.text("SELECT id, owner_id FROM knowledge_bases")
    ).mappings().all():
        workspace_id = default_workspace.get(kb["owner_id"])
        if workspace_id:
            bind.execute(
                sa.text(
                    "UPDATE knowledge_bases SET workspace_id = :workspace_id "
                    "WHERE id = :id"
                ),
                {"workspace_id": workspace_id, "id": kb["id"]},
            )

    existing_members = {
        (row["workspace_id"], row["user_id"])
        for row in bind.execute(
            sa.text("SELECT workspace_id, user_id FROM workspace_members")
        ).mappings()
    }
    for member in bind.execute(
        sa.text("SELECT kb_id, user_id FROM knowledge_base_members")
    ).mappings().all():
        kb = bind.execute(
            sa.text(
                "SELECT workspace_id FROM knowledge_bases WHERE id = :id"
            ),
            {"id": member["kb_id"]},
        ).mappings().first()
        if not kb or not kb["workspace_id"]:
            continue
        key = (kb["workspace_id"], member["user_id"])
        if key in existing_members:
            continue
        existing_members.add(key)
        bind.execute(
            sa.text(
                "INSERT INTO workspace_members "
                "(id, workspace_id, user_id, role, created_at) "
                "VALUES (:id, :workspace_id, :user_id, 'member', :created_at)"
            ),
            {
                "id": uuid.uuid4().hex,
                "workspace_id": kb["workspace_id"],
                "user_id": member["user_id"],
                "created_at": _now(),
            },
        )

    for key in bind.execute(
        sa.text("SELECT id, created_by FROM api_keys")
    ).mappings().all():
        workspace_id = default_workspace.get(key["created_by"])
        if workspace_id:
            bind.execute(
                sa.text(
                    "UPDATE api_keys SET workspace_id = :workspace_id, "
                    "kb_ids = '' WHERE id = :id"
                ),
                {"workspace_id": workspace_id, "id": key["id"]},
            )

    with op.batch_alter_table("knowledge_bases") as batch:
        batch.alter_column(
            "workspace_id", existing_type=sa.String(length=32), nullable=False
        )
    with op.batch_alter_table("api_keys") as batch:
        batch.alter_column(
            "workspace_id", existing_type=sa.String(length=32), nullable=False
        )


def downgrade() -> None:
    op.drop_index(op.f("ix_audit_logs_workspace_id"), table_name="audit_logs")
    op.drop_index(op.f("ix_api_keys_workspace_id"), table_name="api_keys")
    op.drop_index(
        op.f("ix_knowledge_bases_workspace_id"), table_name="knowledge_bases"
    )
    with op.batch_alter_table("api_keys") as batch:
        batch.drop_column("kb_ids")
        batch.drop_column("workspace_id")
    with op.batch_alter_table("knowledge_bases") as batch:
        batch.drop_column("workspace_id")
    with op.batch_alter_table("audit_logs") as batch:
        batch.drop_column("workspace_id")

    op.drop_index(op.f("ix_invitations_token_hash"), table_name="invitations")
    op.drop_index(op.f("ix_invitations_invited_by"), table_name="invitations")
    op.drop_index(op.f("ix_invitations_workspace_id"), table_name="invitations")
    op.drop_table("invitations")
    op.drop_index(
        op.f("ix_workspace_members_user_id"), table_name="workspace_members"
    )
    op.drop_index(
        op.f("ix_workspace_members_workspace_id"), table_name="workspace_members"
    )
    op.drop_table("workspace_members")
    op.drop_index(op.f("ix_workspaces_owner_id"), table_name="workspaces")
    op.drop_table("workspaces")
