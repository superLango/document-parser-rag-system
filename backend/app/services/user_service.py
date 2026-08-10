"""用户管理服务（超管维度）。"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import BusinessException, ErrorCode, ValidationException
from app.core.logging import get_logger
from app.core.password_policy import validate_password
from app.core.security import hash_password
from app.models.password import PasswordHistory
from app.models.user import User
from app.services import rbac_service
from app.services.auth_service import get_password_history, trim_password_history

logger = get_logger(__name__)


async def list_users(
    db: AsyncSession,
    keyword: str | None,
    is_active: bool | None,
    page: int,
    page_size: int,
) -> tuple[list[User], int]:
    base = select(User).where(User.deleted_at.is_(None))
    count_base = select(func.count()).select_from(User).where(User.deleted_at.is_(None))
    if keyword:
        like = f"%{keyword}%"
        cond = or_(
            User.username.ilike(like),
            User.email.ilike(like),
            User.full_name.ilike(like),
        )
        base = base.where(cond)
        count_base = count_base.where(cond)
    if is_active is not None:
        base = base.where(User.is_active == is_active)
        count_base = count_base.where(User.is_active == is_active)
    total = (await db.execute(count_base)).scalar_one()
    users = (
        await db.execute(
            base.order_by(User.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()
    return list(users), total


async def search_users(
    db: AsyncSession, keyword: str, limit: int
) -> list[User]:
    """内部成员选择器：模糊搜索启用中的用户（供 KB 成员添加使用）。"""
    like = f"%{keyword}%"
    stmt = (
        select(User)
        .where(
            User.deleted_at.is_(None),
            User.is_active.is_(True),
            or_(
                User.username.ilike(like),
                User.full_name.ilike(like),
                User.email.ilike(like),
                User.department.ilike(like),
            ),
        )
        .order_by(User.username)
        .limit(limit)
    )
    return list((await db.execute(stmt)).scalars().all())


async def get_user(db: AsyncSession, user_id: uuid.UUID) -> User:
    user = await db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_USER_NOT_FOUND, message=f"用户 {user_id} 不存在"
        )
    return user


async def create_user(db: AsyncSession, operator: User, data) -> User:
    # 历史隐患复测点：email 为空时不得把「email IS NULL」当作冲突条件
    conds = [User.username == data.username]
    if data.email:
        conds.append(User.email == data.email)
    exists = await db.execute(
        select(User).where(or_(*conds), User.deleted_at.is_(None))
    )
    if exists.scalar_one_or_none() is not None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_USER_EXISTS,
            message=f"用户名或邮箱已存在：{data.username}",
        )
    validate_password(data.password, hashed_history=[])
    user = User(
        username=data.username,
        email=data.email,
        hashed_password=hash_password(data.password),
        is_active=True,
        is_superuser=data.is_superuser,
        full_name=data.full_name,
        phone=data.phone,
        department=data.department,
    )
    try:
        db.add(user)
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise BusinessException(
            code=ErrorCode.BUSINESS_USER_EXISTS,
            message=f"用户名或邮箱已存在：{data.username}",
        )
    db.add(PasswordHistory(user_id=user.id, hashed_password=user.hashed_password))
    role_codes = list(data.role_codes or [])
    if not role_codes:
        role_codes = ["super_admin" if data.is_superuser else "member"]
    await rbac_service.assign_user_roles(db, operator, user, role_codes)
    await db.refresh(user)
    logger.info("用户已创建", user_id=str(user.id), operator=str(operator.id))
    return user


async def update_user(
    db: AsyncSession, operator: User, user_id: uuid.UUID, data
) -> User:
    user = await get_user(db, user_id)
    if data.email is not None:
        user.email = data.email
    if data.full_name is not None:
        user.full_name = data.full_name
    if data.phone is not None:
        user.phone = data.phone
    if data.department is not None:
        user.department = data.department
    if data.notes is not None:
        user.notes = data.notes
    if data.is_active is not None:
        user.is_active = data.is_active
    if data.is_superuser is not None:
        if user.id == operator.id and not data.is_superuser:
            raise ValidationException(message="不能取消自身的超级管理员权限")
        user.is_superuser = data.is_superuser
    if data.role_codes is not None:
        await rbac_service.assign_user_roles(db, operator, user, data.role_codes)
    else:
        await db.commit()
        await db.refresh(user)
    return user


async def toggle_active(
    db: AsyncSession, operator: User, user_id: uuid.UUID, is_active: bool
) -> User:
    user = await get_user(db, user_id)
    if user.id == operator.id:
        raise ValidationException(message="不能禁用当前登录账户")
    user.is_active = is_active
    await db.commit()
    await db.refresh(user)
    return user


async def toggle_superuser(
    db: AsyncSession, operator: User, user_id: uuid.UUID, is_superuser: bool
) -> User:
    user = await get_user(db, user_id)
    if user.id == operator.id:
        raise ValidationException(message="不能修改自身的超级管理员权限")
    # 角色与超管标志保持同步
    role_codes = ["super_admin"] if is_superuser else ["member"]
    await rbac_service.assign_user_roles(db, operator, user, role_codes)
    await db.refresh(user)
    return user


async def admin_reset_password(
    db: AsyncSession, user_id: uuid.UUID, new_password: str
) -> None:
    user = await get_user(db, user_id)
    history = await get_password_history(
        db, user.id, limit=settings.PASSWORD_HISTORY_SIZE
    )
    validate_password(new_password, history, current_hashed=user.hashed_password)
    user.hashed_password = hash_password(new_password)
    user.password_changed_at = datetime.now(timezone.utc)
    user.failed_login_count = 0
    user.locked_until = None
    db.add(PasswordHistory(user_id=user.id, hashed_password=user.hashed_password))
    await trim_password_history(db, user.id)
    await db.commit()


async def delete_user(db: AsyncSession, operator: User, user_id: uuid.UUID) -> None:
    user = await get_user(db, user_id)
    if user.id == operator.id:
        raise ValidationException(message="不能删除当前登录账户")
    # 不允许删除最后一名超级管理员
    if user.is_superuser:
        from app.services.rbac_service import _count_super_admin_users

        if await _count_super_admin_users(db) <= 1:
            raise ValidationException(message="系统必须保留至少一名超级管理员")
    user.deleted_at = datetime.now(timezone.utc)
    user.is_active = False
    await db.commit()
