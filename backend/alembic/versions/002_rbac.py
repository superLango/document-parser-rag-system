"""002_rbac: RBAC 角色/权限点/矩阵/用户角色表与种子数据。

- roles / permissions / role_permissions / user_roles
- 内置系统角色与权限目录种子
- 存量用户按 is_superuser 回填 super_admin / member
"""

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "002_rbac"
down_revision = "001_initial_auth"
branch_labels = None
depends_on = None

SYSTEM_ROLE_INFO = {
    "super_admin": ("超级管理员", "系统全量权限，唯一且不可删除", 10),
    "admin": ("管理员", "用户/角色/审计等日常管理权限", 20),
    "member": ("普通成员", "平台使用者，权限由资源 ACL 约束", 30),
    "pending": ("待审批", "仅能访问个人中心与审批相关页面", 40),
}

PERMISSION_CATALOG = [
    ("system.stats", "系统统计", "system", "查看工作台系统统计与趋势"),
    ("user.view", "查看用户", "user", "查看用户列表与详情"),
    ("user.create", "创建用户", "user", "创建新用户"),
    ("user.update", "更新用户", "user", "更新用户资料与角色"),
    ("user.delete", "删除用户", "user", "软删除用户"),
    ("user.reset_password", "重置密码", "user", "管理员重置用户密码"),
    ("user.manage", "用户状态管理", "user", "启停用户、切换超管、分配角色"),
    ("role.view", "查看角色", "role", "查看角色与权限矩阵"),
    ("role.manage", "管理角色", "role", "创建/编辑/删除自定义角色并维护权限矩阵"),
    ("audit.view", "查看审计", "audit", "查看审计日志与统计"),
    ("audit.export", "导出审计", "audit", "导出审计日志"),
]

ROLE_PERMISSION_MATRIX = {
    "super_admin": [c for c, _, _, _ in PERMISSION_CATALOG],
    "admin": [
        "system.stats",
        "user.view",
        "user.create",
        "user.update",
        "user.reset_password",
        "user.manage",
        "role.view",
        "audit.view",
    ],
    "member": [],
    "pending": [],
}


def _rid(code: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"hansondoc:role:{code}"))


def _pid(code: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"hansondoc:perm:{code}"))


def upgrade() -> None:
    op.create_table(
        "roles",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True, onupdate=sa.func.now()),
    )
    op.create_index("ix_roles_code", "roles", ["code"], unique=True)

    op.create_table(
        "permissions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("resource_type", sa.String(64), nullable=True),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_permissions_code", "permissions", ["code"], unique=True)

    op.create_table(
        "role_permissions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("role_id", UUID(as_uuid=True), sa.ForeignKey("roles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("permission_id", UUID(as_uuid=True), sa.ForeignKey("permissions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("role_id", "permission_id", name="uq_role_permissions_role_perm"),
    )
    op.create_index("ix_role_permissions_role_id", "role_permissions", ["role_id"])
    op.create_index("ix_role_permissions_permission_id", "role_permissions", ["permission_id"])

    op.create_table(
        "user_roles",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role_id", UUID(as_uuid=True), sa.ForeignKey("roles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scope", sa.String(16), nullable=False, server_default="system"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "role_id", "scope", name="uq_user_roles_user_role_scope"),
    )
    op.create_index("ix_user_roles_user_id", "user_roles", ["user_id"])
    op.create_index("ix_user_roles_role_id", "user_roles", ["role_id"])

    # ---------- 种子数据 ----------
    op.bulk_insert(
        sa.table(
            "roles",
            sa.column("id", UUID(as_uuid=True)),
            sa.column("code", sa.String),
            sa.column("name", sa.String),
            sa.column("description", sa.String),
            sa.column("is_system", sa.Boolean),
            sa.column("sort_order", sa.Integer),
        ),
        [
            {
                "id": _rid(code),
                "code": code,
                "name": info[0],
                "description": info[1],
                "is_system": True,
                "sort_order": info[2],
            }
            for code, info in SYSTEM_ROLE_INFO.items()
        ],
    )
    op.bulk_insert(
        sa.table(
            "permissions",
            sa.column("id", UUID(as_uuid=True)),
            sa.column("code", sa.String),
            sa.column("name", sa.String),
            sa.column("resource_type", sa.String),
            sa.column("description", sa.String),
        ),
        [
            {
                "id": _pid(code),
                "code": code,
                "name": name,
                "resource_type": resource_type,
                "description": desc,
            }
            for code, name, resource_type, desc in PERMISSION_CATALOG
        ],
    )
    op.bulk_insert(
        sa.table(
            "role_permissions",
            sa.column("id", UUID(as_uuid=True)),
            sa.column("role_id", UUID(as_uuid=True)),
            sa.column("permission_id", UUID(as_uuid=True)),
        ),
        [
            {
                "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"hansondoc:rp:{role}:{perm}")),
                "role_id": _rid(role),
                "permission_id": _pid(perm),
            }
            for role, perms in ROLE_PERMISSION_MATRIX.items()
            for perm in perms
        ],
    )

    # 存量用户回填：is_superuser=true -> super_admin，其余 -> member
    op.execute(
        sa.text(
            """
            INSERT INTO user_roles (id, user_id, role_id, scope, created_at)
            SELECT gen_random_uuid(), u.id,
                   CASE WHEN u.is_superuser THEN CAST(:super_id AS uuid) ELSE CAST(:member_id AS uuid) END,
                   'system', now()
            FROM users u
            WHERE u.deleted_at IS NULL
            ON CONFLICT (user_id, role_id, scope) DO NOTHING
            """
        ).bindparams(
            super_id=_rid("super_admin"),
            member_id=_rid("member"),
        )
    )


def downgrade() -> None:
    op.drop_table("user_roles")
    op.drop_table("role_permissions")
    op.drop_table("permissions")
    op.drop_table("roles")
