"""RBAC ORM 模型：系统角色、权限点、角色权限矩阵、用户角色。"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

# ---------------- 系统角色常量 ----------------
ROLE_SUPER_ADMIN = "super_admin"
ROLE_ADMIN = "admin"
ROLE_MEMBER = "member"
ROLE_PENDING = "pending"

SYSTEM_ROLES = frozenset({ROLE_SUPER_ADMIN, ROLE_ADMIN, ROLE_MEMBER, ROLE_PENDING})

SYSTEM_ROLE_INFO: dict[str, tuple[str, str, int]] = {
    ROLE_SUPER_ADMIN: ("超级管理员", "系统全量权限，唯一且不可删除", 10),
    ROLE_ADMIN: ("管理员", "用户/角色/审计等日常管理权限", 20),
    ROLE_MEMBER: ("普通成员", "平台使用者，权限由资源 ACL 约束", 30),
    ROLE_PENDING: ("待审批", "仅能访问个人中心与审批相关页面", 40),
}

# ---------------- 权限点目录 ----------------
# (code, name, resource_type, description)
PERMISSION_CATALOG: list[tuple[str, str, str, str]] = [
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

PERMISSION_CODES = frozenset(code for code, _, _, _ in PERMISSION_CATALOG)

ROLE_PERMISSION_MATRIX: dict[str, list[str]] = {
    ROLE_SUPER_ADMIN: sorted(PERMISSION_CODES),
    ROLE_ADMIN: [
        "system.stats",
        "user.view",
        "user.create",
        "user.update",
        "user.reset_password",
        "user.manage",
        "role.view",
        "audit.view",
    ],
    ROLE_MEMBER: [],
    ROLE_PENDING: [],
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), onupdate=utcnow, nullable=True)


class Permission(Base):
    __tablename__ = "permissions"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class RolePermission(Base):
    __tablename__ = "role_permissions"
    __table_args__ = (
        UniqueConstraint("role_id", "permission_id", name="uq_role_permissions_role_perm"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    role_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE"), index=True, nullable=False
    )
    permission_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("permissions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class UserRole(Base):
    __tablename__ = "user_roles"
    __table_args__ = (
        UniqueConstraint("user_id", "role_id", "scope", name="uq_user_roles_user_role_scope"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE"), index=True, nullable=False
    )
    scope: Mapped[str] = mapped_column(String(16), default="system", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
