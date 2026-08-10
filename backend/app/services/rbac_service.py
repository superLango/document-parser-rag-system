"""RBAC 服务：种子数据、角色管理、权限矩阵、用户角色分配。"""

import uuid

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationException
from app.core.logging import get_logger
from app.models.rbac import (
    PERMISSION_CATALOG,
    PERMISSION_CODES,
    ROLE_PERMISSION_MATRIX,
    ROLE_SUPER_ADMIN,
    SYSTEM_ROLE_INFO,
    SYSTEM_ROLES,
    Permission,
    Role,
    RolePermission,
    UserRole,
)
from app.models.user import User

logger = get_logger(__name__)


async def _get_role_by_code(db: AsyncSession, code: str) -> Role | None:
    return (
        await db.execute(select(Role).where(Role.code == code))
    ).scalar_one_or_none()


async def _get_permission_by_code(db: AsyncSession, code: str) -> Permission | None:
    return (
        await db.execute(select(Permission).where(Permission.code == code))
    ).scalar_one_or_none()


async def ensure_rbac_seed(db: AsyncSession) -> None:
    """幂等初始化系统角色/权限点/矩阵，并回填存量用户角色。"""
    changed = False
    for code, (name, desc, sort) in SYSTEM_ROLE_INFO.items():
        if await _get_role_by_code(db, code) is None:
            db.add(
                Role(
                    code=code,
                    name=name,
                    description=desc,
                    is_system=True,
                    sort_order=sort,
                )
            )
            changed = True
    for code, name, resource_type, desc in PERMISSION_CATALOG:
        if await _get_permission_by_code(db, code) is None:
            db.add(Permission(code=code, name=name, resource_type=resource_type, description=desc))
            changed = True
    if changed:
        await db.flush()

    for role_code, perm_codes in ROLE_PERMISSION_MATRIX.items():
        role = await _get_role_by_code(db, role_code)
        if role is None:
            continue
        for perm_code in perm_codes:
            perm = await _get_permission_by_code(db, perm_code)
            if perm is None:
                continue
            exists = (
                await db.execute(
                    select(RolePermission).where(
                        RolePermission.role_id == role.id,
                        RolePermission.permission_id == perm.id,
                    )
                )
            ).scalar_one_or_none()
            if exists is None:
                db.add(RolePermission(role_id=role.id, permission_id=perm.id))
                changed = True

    # 回填：is_superuser -> super_admin，其余 -> member
    users = (
        await db.execute(select(User).where(User.deleted_at.is_(None)))
    ).scalars().all()
    for user in users:
        await ensure_user_default_role(db, user)

    if changed:
        await db.commit()
    logger.info("RBAC 种子数据已就绪")


async def ensure_user_default_role(
    db: AsyncSession, user: User, *, is_superuser: bool | None = None
) -> None:
    """确保用户至少有一个系统角色；无角色时按超管标志回填。"""
    role_code = (
        ROLE_SUPER_ADMIN
        if (user.is_superuser if is_superuser is None else is_superuser)
        else "member"
    )
    role = await _get_role_by_code(db, role_code)
    if role is None:
        if role_code in SYSTEM_ROLE_INFO:
            name, desc, sort = SYSTEM_ROLE_INFO[role_code]
            role = Role(code=role_code, name=name, description=desc, is_system=True, sort_order=sort)
            db.add(role)
            await db.flush()
    exists = (
        await db.execute(
            select(UserRole).where(
                UserRole.user_id == user.id,
                UserRole.role_id == role.id,
                UserRole.scope == "system",
            )
        )
    ).scalar_one_or_none()
    if exists is None:
        db.add(UserRole(user_id=user.id, role_id=role.id, scope="system"))


async def get_user_roles(db: AsyncSession, user_id: uuid.UUID) -> list[Role]:
    stmt = (
        select(Role)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user_id, UserRole.scope == "system")
        .order_by(Role.sort_order, Role.created_at)
    )
    return list((await db.execute(stmt)).scalars().all())


async def get_users_roles(
    db: AsyncSession, user_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[Role]]:
    if not user_ids:
        return {}
    rows = (
        await db.execute(
            select(Role, UserRole.user_id)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id.in_(user_ids), UserRole.scope == "system")
            .order_by(Role.sort_order, Role.created_at)
        )
    ).all()
    result: dict[uuid.UUID, list[Role]] = {uid: [] for uid in user_ids}
    for role, uid in rows:
        result.setdefault(uid, []).append(role)
    return result


async def get_user_permissions(db: AsyncSession, user_id: uuid.UUID) -> set[str]:
    roles = await get_user_roles(db, user_id)
    if any(r.code == ROLE_SUPER_ADMIN for r in roles):
        return set(PERMISSION_CODES)
    if not roles:
        return set()
    stmt = (
        select(Permission.code)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .join(UserRole, UserRole.role_id == RolePermission.role_id)
        .where(UserRole.user_id == user_id, UserRole.scope == "system")
        .distinct()
    )
    return set((await db.execute(stmt)).scalars().all())


async def list_roles(db: AsyncSession) -> list[Role]:
    return list(
        (await db.execute(select(Role).order_by(Role.sort_order, Role.created_at))).scalars().all()
    )


async def get_role(db: AsyncSession, role_id: uuid.UUID) -> Role:
    role = await db.get(Role, role_id)
    if role is None:
        from app.core.exceptions import BusinessException, ErrorCode

        raise BusinessException(code=ErrorCode.BUSINESS_NOT_FOUND, message=f"角色 {role_id} 不存在")
    return role


async def list_permissions(db: AsyncSession) -> list[Permission]:
    return list(
        (await db.execute(select(Permission).order_by(Permission.resource_type, Permission.code))).scalars().all()
    )


async def create_role(db: AsyncSession, operator: User | None, data) -> Role:
    if data.code in SYSTEM_ROLES:
        raise ValidationException(message=f"角色编码 {data.code} 为系统保留编码")
    if await _get_role_by_code(db, data.code) is not None:
        raise ValidationException(message=f"角色编码已存在：{data.code}")
    max_sort = (
        await db.execute(select(func.max(Role.sort_order)))
    ).scalar_one()
    role = Role(
        code=data.code,
        name=data.name,
        description=data.description,
        is_system=False,
        sort_order=(max_sort or 100) + 10,
    )
    db.add(role)
    await db.commit()
    await db.refresh(role)
    logger.info(
        "自定义角色已创建",
        role_code=role.code,
        operator=str(getattr(operator, "id", "system")),
    )
    return role


async def update_role(db: AsyncSession, operator: User | None, role_id: uuid.UUID, data) -> Role:
    role = await get_role(db, role_id)
    if role.is_system:
        raise ValidationException(message="系统角色不允许修改")
    name = getattr(data, "name", None)
    description = getattr(data, "description", None)
    if name is not None:
        role.name = name
    if description is not None:
        role.description = description
    await db.commit()
    await db.refresh(role)
    logger.info(
        "自定义角色已更新",
        role_code=role.code,
        operator=str(getattr(operator, "id", "system")),
    )
    return role


async def delete_role(db: AsyncSession, operator: User | None, role_id: uuid.UUID) -> None:
    role = await get_role(db, role_id)
    if role.is_system:
        raise ValidationException(message="系统角色不允许删除")
    await db.delete(role)
    await db.commit()
    logger.info(
        "自定义角色已删除",
        role_code=role.code,
        operator=str(getattr(operator, "id", "system")),
    )


async def get_role_permission_codes(db: AsyncSession, role_id: uuid.UUID) -> set[str]:
    await get_role(db, role_id)
    stmt = (
        select(Permission.code)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .where(RolePermission.role_id == role_id)
    )
    return set((await db.execute(stmt)).scalars().all())


async def set_role_permissions(
    db: AsyncSession, operator: User | None, role_id: uuid.UUID, permission_codes: list[str]
) -> set[str]:
    role = await get_role(db, role_id)
    if role.is_system:
        raise ValidationException(message="系统角色权限矩阵不允许修改")
    codes = list(dict.fromkeys(permission_codes))
    invalid = [c for c in codes if c not in PERMISSION_CODES]
    if invalid:
        raise ValidationException(message=f"非法权限点：{', '.join(invalid)}")
    existing = (
        await db.execute(select(RolePermission).where(RolePermission.role_id == role_id))
    ).scalars().all()
    for row in existing:
        await db.delete(row)
    await db.flush()
    for code in codes:
        perm = await _get_permission_by_code(db, code)
        if perm is not None:
            db.add(RolePermission(role_id=role_id, permission_id=perm.id))
    await db.commit()
    logger.info(
        "角色权限矩阵已更新",
        role_code=role.code,
        permission_count=len(codes),
        operator=str(getattr(operator, "id", "system")),
    )
    return set(codes)


async def _count_super_admin_users(db: AsyncSession) -> int:
    role = await _get_role_by_code(db, ROLE_SUPER_ADMIN)
    if role is None:
        return 0
    return (
        await db.execute(
            select(func.count())
            .select_from(UserRole)
            .where(UserRole.role_id == role.id, UserRole.scope == "system")
        )
    ).scalar_one()


async def assign_user_roles(
    db: AsyncSession, operator: User, user: User, role_codes: list[str]
) -> list[Role]:
    codes = list(dict.fromkeys(role_codes))
    if not codes:
        raise ValidationException(message="至少需要分配一个角色")
    if ROLE_SUPER_ADMIN in codes and not operator.is_superuser:
        raise ValidationException(message="仅超级管理员可分配超级管理员角色")

    roles: list[Role] = []
    for code in codes:
        role = await _get_role_by_code(db, code)
        if role is None:
            raise ValidationException(message=f"角色不存在：{code}")
        roles.append(role)

    # 行级咨询锁：同一用户的并发分配串行执行，避免 user_roles 唯一约束竞态
    lock_key = user.id.int & 0x7FFFFFFFFFFFFFFF
    await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})

    current_codes = {r.code for r in await get_user_roles(db, user.id)}
    has_super = ROLE_SUPER_ADMIN in current_codes
    will_have_super = ROLE_SUPER_ADMIN in codes
    if has_super and not will_have_super:
        if user.id == operator.id:
            raise ValidationException(message="不能移除自身超级管理员角色")
        if await _count_super_admin_users(db) <= 1:
            raise ValidationException(message="系统必须保留至少一名超级管理员")

    old_rows = (
        await db.execute(
            select(UserRole).where(UserRole.user_id == user.id, UserRole.scope == "system")
        )
    ).scalars().all()
    for row in old_rows:
        await db.delete(row)
    await db.flush()
    for role in roles:
        db.add(UserRole(user_id=user.id, role_id=role.id, scope="system"))
    user.is_superuser = will_have_super
    await db.commit()
    await db.refresh(user)
    logger.info(
        "用户角色已分配",
        user_id=str(user.id),
        role_codes=codes,
        operator=str(getattr(operator, "id", "system")),
    )
    return roles
