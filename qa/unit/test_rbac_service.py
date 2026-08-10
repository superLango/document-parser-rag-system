"""L1 单元测试：RBAC 服务（种子幂等、角色保护、权限矩阵、用户角色分配）。"""

import uuid

import pytest
from sqlalchemy import func, select

from app.core.exceptions import ValidationException
from app.models.rbac import (
    PERMISSION_CODES,
    ROLE_PERMISSION_MATRIX,
    ROLE_SUPER_ADMIN,
    Permission,
    Role,
    RolePermission,
    UserRole,
)
from app.models.user import User
from app.schemas.rbac import RoleCreate
from app.services import rbac_service


async def _make_user(db, prefix: str, is_superuser: bool = False) -> User:
    username = f"{prefix}_{uuid.uuid4().hex[:8]}"
    from app.core.security import hash_password

    user = User(
        username=username,
        hashed_password=hash_password("Test@1234"),
        is_superuser=is_superuser,
    )
    db.add(user)
    await db.flush()
    await rbac_service.ensure_user_default_role(
        db, user, is_superuser=is_superuser
    )
    await db.commit()
    await db.refresh(user)
    return user


async def test_seed_idempotent(db_session):
    await rbac_service.ensure_rbac_seed(db_session)
    await rbac_service.ensure_rbac_seed(db_session)
    system_role_count = (
        await db_session.execute(
            select(func.count()).select_from(Role).where(Role.is_system.is_(True))
        )
    ).scalar_one()
    perm_count = (
        await db_session.execute(select(func.count()).select_from(Permission))
    ).scalar_one()
    super_matrix = (
        await db_session.execute(
            select(func.count())
            .select_from(RolePermission)
            .join(Role, Role.id == RolePermission.role_id)
            .where(Role.code == ROLE_SUPER_ADMIN)
        )
    ).scalar_one()
    assert system_role_count == 4
    assert perm_count == len(PERMISSION_CODES) == 11
    assert super_matrix == 11


async def test_super_admin_permissions_are_all(db_session):
    user = await _make_user(db_session, "ut_super", is_superuser=True)
    perms = await rbac_service.get_user_permissions(db_session, user.id)
    assert perms == set(PERMISSION_CODES)


async def test_member_permissions_empty(db_session):
    user = await _make_user(db_session, "ut_member")
    perms = await rbac_service.get_user_permissions(db_session, user.id)
    assert perms == set()


async def test_self_demotion_blocked(db_session):
    user = await _make_user(db_session, "ut_self_super", is_superuser=True)
    with pytest.raises(ValidationException):
        await rbac_service.assign_user_roles(
            db_session, user, user, ["member"]
        )


async def test_admin_cannot_assign_super_admin(db_session):
    admin = await _make_user(db_session, "ut_admin_operator")
    target = await _make_user(db_session, "ut_admin_target")
    with pytest.raises(ValidationException):
        await rbac_service.assign_user_roles(
            db_session, admin, target, [ROLE_SUPER_ADMIN]
        )


async def test_empty_assignment_blocked(db_session):
    user = await _make_user(db_session, "ut_empty_assign")
    with pytest.raises(ValidationException):
        await rbac_service.assign_user_roles(db_session, user, user, [])


async def test_unknown_role_blocked(db_session):
    user = await _make_user(db_session, "ut_unknown_role")
    with pytest.raises(ValidationException):
        await rbac_service.assign_user_roles(
            db_session, user, user, ["ghost_role"]
        )


async def test_system_role_code_blocked_for_custom(db_session):
    with pytest.raises(ValidationException):
        await rbac_service.create_role(
            db_session, None, RoleCreate(code="admin", name="冒名")
        )


async def test_duplicate_role_code_blocked(db_session):
    code = f"custom_{uuid.uuid4().hex[:6]}"
    await rbac_service.create_role(
        db_session, None, RoleCreate(code=code, name="自定义")
    )
    with pytest.raises(ValidationException):
        await rbac_service.create_role(
            db_session, None, RoleCreate(code=code, name="重复")
        )


async def test_system_role_immutable(db_session):
    role = await rbac_service._get_role_by_code(db_session, "admin")
    with pytest.raises(ValidationException):
        await rbac_service.update_role(db_session, None, role.id, {"name": "改名"})
    with pytest.raises(ValidationException):
        await rbac_service.set_role_permissions(
            db_session, None, role.id, ["audit.view"]
        )
    with pytest.raises(ValidationException):
        await rbac_service.delete_role(db_session, None, role.id)


async def test_set_permissions_invalid_code_blocked(db_session):
    role = await rbac_service.create_role(
        db_session, None, RoleCreate(code=f"matrix_{uuid.uuid4().hex[:6]}", name="矩阵角色")
    )
    with pytest.raises(ValidationException):
        await rbac_service.set_role_permissions(
            db_session, None, role.id, ["not.a.permission"]
        )


async def test_delete_custom_role_cascades_user_roles(db_session):
    role = await rbac_service.create_role(
        db_session, None, RoleCreate(code=f"cascade_{uuid.uuid4().hex[:6]}", name="级联角色")
    )
    user = await _make_user(db_session, "ut_cascade_user")
    role_code = role.code
    await rbac_service.assign_user_roles(db_session, user, user, [role_code])
    await rbac_service.delete_role(db_session, None, role.id)
    rows = (
        await db_session.execute(
            select(UserRole).where(UserRole.user_id == user.id)
        )
    ).scalars().all()
    assert rows == []
