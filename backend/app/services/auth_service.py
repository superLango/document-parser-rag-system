"""认证与账户自助服务。"""

from datetime import datetime, timedelta, timezone

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AuthException, BusinessException, ErrorCode
from app.core.logging import get_logger
from app.core.password_policy import validate_password
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_password,
)
from app.models.password import PasswordHistory, PasswordResetToken
from app.models.user import User
from app.services import rbac_service
from app.schemas.user import TokenResponse

logger = get_logger(__name__)


async def get_password_history(
    db: AsyncSession, user_id, limit: int | None = None
) -> list[str]:
    stmt = (
        select(PasswordHistory.hashed_password)
        .where(PasswordHistory.user_id == user_id)
        .order_by(PasswordHistory.created_at.desc())
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    rows = await db.execute(stmt)
    return [r[0] for r in rows.all()]


async def trim_password_history(db: AsyncSession, user_id) -> None:
    """仅保留最近 N 条密码历史。"""
    keep = settings.PASSWORD_HISTORY_SIZE
    rows = (
        await db.execute(
            select(PasswordHistory)
            .where(PasswordHistory.user_id == user_id)
            .order_by(PasswordHistory.created_at.desc())
        )
    ).scalars().all()
    for old in rows[keep:]:
        await db.delete(old)


def _token_response(access_token: str, refresh_token: str | None = None) -> dict:
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    ).model_dump()


async def login(
    db: AsyncSession, request: Request, username: str, password: str
) -> dict:
    user = (
        await db.execute(
            select(User).where(User.username == username, User.deleted_at.is_(None))
        )
    ).scalar_one_or_none()

    now = datetime.now(timezone.utc)

    if user is not None and user.locked_until is not None:
        if user.locked_until > now:
            remaining = max(1, int((user.locked_until - now).total_seconds() // 60))
            raise BusinessException(
                code=ErrorCode.BUSINESS_USER_LOCKED,
                message=f"账户已锁定，请在 {remaining} 分钟后重试",
            )
        user.locked_until = None

    auth_ok = (
        user is not None
        and user.is_active
        and verify_password(password, user.hashed_password)
    )

    if not auth_ok:
        if user is not None:
            user.failed_login_count = (user.failed_login_count or 0) + 1
            if user.failed_login_count >= settings.LOGIN_MAX_FAILURES:
                user.locked_until = now + timedelta(minutes=settings.LOGIN_LOCK_MINUTES)
                user.failed_login_count = 0
                logger.warning(
                    "账户因多次登录失败被锁定",
                    username=username,
                    lock_minutes=settings.LOGIN_LOCK_MINUTES,
                )
            await db.commit()
        raise AuthException(
            code=ErrorCode.AUTH_TOKEN_INVALID, message="用户名或密码错误"
        )

    client_ip = request.client.host if request.client else None
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now
    user.last_login_ip = client_ip
    await db.commit()

    return _token_response(
        create_access_token(data={"sub": user.username}),
        create_refresh_token(data={"sub": user.username}),
    )


async def refresh_access_token(db: AsyncSession, refresh_token_str: str) -> dict:
    from app.core.security import verify_refresh_token

    payload = verify_refresh_token(refresh_token_str)
    username: str | None = payload.get("sub")
    if not username:
        raise AuthException(
            code=ErrorCode.AUTH_TOKEN_INVALID, message="令牌中缺少用户信息"
        )
    user = (
        await db.execute(
            select(User).where(User.username == username, User.deleted_at.is_(None))
        )
    ).scalar_one_or_none()
    if user is None or not user.is_active:
        raise AuthException(
            code=ErrorCode.AUTH_TOKEN_INVALID, message="用户不存在或已禁用"
        )
    return _token_response(create_access_token(data={"sub": user.username}))


async def register(
    db: AsyncSession, username: str, password: str, email: str | None, full_name: str | None
) -> User:
    if not settings.ALLOW_REGISTRATION:
        raise BusinessException(
            code=ErrorCode.VALIDATION_ERROR, message="系统已关闭自助注册"
        )
    exists = await db.execute(
        select(User).where(User.username == username, User.deleted_at.is_(None))
    )
    if exists.scalar_one_or_none() is not None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_USER_EXISTS, message=f"用户名已存在：{username}"
        )
    validate_password(password, hashed_history=[])
    user = User(
        username=username,
        email=email,
        hashed_password=hash_password(password),
        is_active=True,
        is_superuser=False,
        full_name=full_name,
    )
    try:
        db.add(user)
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise BusinessException(
            code=ErrorCode.BUSINESS_USER_EXISTS, message=f"用户名已存在：{username}"
        )
    db.add(PasswordHistory(user_id=user.id, hashed_password=user.hashed_password))
    await rbac_service.ensure_user_default_role(
        db,
        user,
        role_code="pending" if settings.REGISTRATION_DEFAULT_PENDING else None,
    )
    await db.commit()
    await db.refresh(user)
    return user


async def update_profile(db: AsyncSession, user: User, data) -> User:
    if data.email is not None:
        user.email = data.email
    if data.full_name is not None:
        user.full_name = data.full_name
    if data.phone is not None:
        user.phone = data.phone
    if data.department is not None:
        user.department = data.department
    if data.avatar is not None:
        user.avatar = data.avatar
    await db.commit()
    await db.refresh(user)
    return user


async def change_password(
    db: AsyncSession, user: User, old_password: str, new_password: str
) -> None:
    if not verify_password(old_password, user.hashed_password):
        raise AuthException(code=ErrorCode.AUTH_TOKEN_INVALID, message="旧密码错误")
    history = await get_password_history(
        db, user.id, limit=settings.PASSWORD_HISTORY_SIZE
    )
    validate_password(new_password, history, current_hashed=user.hashed_password)

    user.hashed_password = hash_password(new_password)
    user.password_changed_at = datetime.now(timezone.utc)
    db.add(PasswordHistory(user_id=user.id, hashed_password=user.hashed_password))
    await trim_password_history(db, user.id)
    await db.commit()


async def reset_password_with_token(
    db: AsyncSession, token_str: str, new_password: str
) -> None:
    now = datetime.now(timezone.utc)
    token_row = (
        await db.execute(
            select(PasswordResetToken).where(PasswordResetToken.token == token_str)
        )
    ).scalar_one_or_none()
    if token_row is None or token_row.used or token_row.expires_at < now:
        raise BusinessException(
            code=ErrorCode.BUSINESS_RESET_TOKEN_INVALID, message="重置令牌无效或已过期"
        )
    user = await db.get(User, token_row.user_id)
    if user is None or user.deleted_at is not None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_USER_NOT_FOUND, message="用户不存在"
        )
    history = await get_password_history(
        db, user.id, limit=settings.PASSWORD_HISTORY_SIZE
    )
    validate_password(new_password, history, current_hashed=user.hashed_password)

    user.hashed_password = hash_password(new_password)
    user.password_changed_at = now
    user.failed_login_count = 0
    user.locked_until = None
    token_row.used = True
    db.add(PasswordHistory(user_id=user.id, hashed_password=user.hashed_password))
    await trim_password_history(db, user.id)
    await db.commit()


async def create_reset_token(db: AsyncSession, user_id, token: str) -> None:
    """生成一次性密码重置令牌（供后续邮件流程使用）。"""
    db.add(
        PasswordResetToken(
            user_id=user_id,
            token=token,
            expires_at=datetime.now(timezone.utc)
            + timedelta(minutes=settings.RESET_TOKEN_EXPIRE_MINUTES),
        )
    )
    await db.commit()
