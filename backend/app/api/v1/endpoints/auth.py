"""认证端点模块（阶段 1.1 扩展）。

提供用户认证与账户自助接口：
- POST /auth/login          登录（含失败计数与账户锁定）
- GET  /auth/me             当前用户信息
- POST /auth/register       注册（开放注册，默认普通用户）
- POST /auth/change-password 修改密码（需旧密码）
- POST /auth/reset-password  重置密码（携带重置令牌）

所有响应遵循统一响应体格式（见 app.core.response.success）。
"""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.exceptions import AuthException, BusinessException, ErrorCode
from app.core.logging import get_logger
from app.core.password_policy import validate_password
from app.core.response import success
from app.api.deps import AUTH_LIMIT, limiter
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_password,
    verify_refresh_token,
    verify_token,
)
from app.middleware.audit_log import audit_action
from app.models.password_reset import PasswordHistory, PasswordResetToken
from app.models.user import User
from app.schemas.user import (
    PasswordChangeRequest,
    PasswordResetRequest,
    ProfileUpdate,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    """登录请求体。"""

    username: str
    password: str


async def get_current_user_from_header(
    authorization: str | None = None,
) -> str:
    """从 Authorization 头解析当前登录用户名。

    期望请求头格式：``Authorization: Bearer <token>``。
    缺失或无效时抛出 ``AuthException``（HTTP 401）。

    Args:
        authorization: Authorization 请求头的原始值。

    Returns:
        str: 从 JWT ``sub`` 声明中提取的用户名。

    Raises:
        AuthException: 未提供令牌、格式错误或令牌无效。
    """
    if not authorization:
        raise AuthException(
            code=ErrorCode.AUTH_TOKEN_INVALID,
            message="未提供认证令牌",
        )
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise AuthException(
            code=ErrorCode.AUTH_TOKEN_INVALID,
            message="无效的认证令牌格式",
        )
    token = parts[1]
    payload = verify_token(token)
    username: str | None = payload.get("sub")
    if not username:
        raise AuthException(
            code=ErrorCode.AUTH_TOKEN_INVALID,
            message="令牌中缺少用户信息",
        )
    return username


@router.post("/login")
@limiter.limit(AUTH_LIMIT)
@audit_action(action="auth.login", resource_type="user", capture_body=False)
async def login(
    body: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """用户登录接口。

    校验用户名与密码，成功后签发 JWT 访问令牌。
    生产级安全策略：
    - 账户锁定校验（locked_until 未过期则拒绝）
    - 失败计数（达到 LOGIN_MAX_FAILURES 后锁定 LOGIN_LOCK_MINUTES 分钟）
    - 成功后清零失败计数并记录 last_login_at / last_login_ip

    Args:
        body: 登录请求体（用户名 + 密码）。
        request: 请求对象（取客户端 IP）。
        db: 异步数据库会话（依赖注入）。

    Returns:
        dict: 统一响应体，``data`` 字段为 ``TokenResponse``。

    Raises:
        AuthException: 用户名或密码错误时返回 HTTP 401。
        BusinessException: 账户被锁定时返回 HTTP 400。
    """
    stmt = select(User).where(User.username == body.username, User.deleted_at.is_(None))
    user = (await db.execute(stmt)).scalar_one_or_none()

    now = datetime.now(timezone.utc)

    # 账户锁定校验
    if user is not None and user.locked_until is not None:
        if user.locked_until > now:
            remaining = int((user.locked_until - now).total_seconds() // 60)
            raise BusinessException(
                code=ErrorCode.BUSINESS_USER_LOCKED,
                message=f"账户已锁定，请在 {remaining} 分钟后重试",
            )
        # 锁定期过，解锁但保留失败计数（下次失败重新锁定）
        user.locked_until = None

    # 校验用户存在 + 密码正确 + 已启用
    auth_ok = (
        user is not None
        and user.is_active
        and verify_password(body.password, user.hashed_password)
    )

    if not auth_ok:
        # 失败计数
        if user is not None:
            user.failed_login_count = (user.failed_login_count or 0) + 1
            if user.failed_login_count >= settings.LOGIN_MAX_FAILURES:
                user.locked_until = now + timedelta(minutes=settings.LOGIN_LOCK_MINUTES)
                user.failed_login_count = 0
                logger.warning(
                    "账户因多次登录失败被锁定",
                    username=body.username,
                    lock_minutes=settings.LOGIN_LOCK_MINUTES,
                )
            await db.commit()
        raise AuthException(
            code=ErrorCode.AUTH_TOKEN_INVALID,
            message="用户名或密码错误",
        )

    # 登录成功：清零失败计数，记录登录信息
    client_ip = request.client.host if request.client else None
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now
    user.last_login_ip = client_ip
    await db.commit()

    access_token = create_access_token(data={"sub": user.username})
    refresh_token = create_refresh_token(data={"sub": user.username})
    token_data = TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )
    return success(data=token_data.model_dump())


@router.post("/refresh")
@limiter.limit(AUTH_LIMIT)
async def refresh_token(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """刷新访问令牌（P2-7 refresh token 机制）。

    客户端在 access token 过期后，携带 refresh token 调用本端点静默换取
    新的 access token，避免用户重新登录。refresh token 有效期默认 7 天。

    Args:
        request: 请求对象（从 Authorization 头读取 refresh token）。
        db: 异步数据库会话。

    Returns:
        dict: 统一响应体，``data`` 字段为新的 ``TokenResponse``。

    Raises:
        AuthException: refresh token 无效或过期。
    """
    authorization = request.headers.get("authorization")
    if not authorization:
        raise AuthException(
            code=ErrorCode.AUTH_TOKEN_INVALID,
            message="未提供刷新令牌",
        )
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise AuthException(
            code=ErrorCode.AUTH_TOKEN_INVALID,
            message="无效的令牌格式",
        )
    payload = verify_refresh_token(parts[1])
    username: str | None = payload.get("sub")
    if not username:
        raise AuthException(
            code=ErrorCode.AUTH_TOKEN_INVALID,
            message="令牌中缺少用户信息",
        )

    # 校验用户仍存在且启用
    user = (
        await db.execute(
            select(User).where(User.username == username, User.deleted_at.is_(None))
        )
    ).scalar_one_or_none()
    if user is None or not user.is_active:
        raise AuthException(
            code=ErrorCode.AUTH_TOKEN_INVALID,
            message="用户不存在或已禁用",
        )

    new_access_token = create_access_token(data={"sub": user.username})
    token_data = TokenResponse(
        access_token=new_access_token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )
    return success(data=token_data.model_dump())


@router.get("/me")
async def get_me(
    authorization: str | None = Header(None),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取当前登录用户信息。

    Args:
        authorization: Authorization 请求头（由 get_current_user_from_header 解析）。
        db: 异步数据库会话（依赖注入）。

    Returns:
        dict: 统一响应体，``data`` 字段为 ``UserResponse``。

    Raises:
        AuthException: 用户不存在时返回 HTTP 401。
    """
    username = await get_current_user_from_header(authorization)
    stmt = select(User).where(User.username == username, User.deleted_at.is_(None))
    user = (await db.execute(stmt)).scalar_one_or_none()
    if user is None:
        raise AuthException(
            code=ErrorCode.AUTH_TOKEN_INVALID,
            message="用户不存在",
        )
    user_data = UserResponse.model_validate(user)
    return success(data=user_data.model_dump())


@router.put("/profile")
@audit_action(action="auth.update_profile", resource_type="user", capture_body=False)
async def update_profile(
    body: ProfileUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """更新个人资料（用户自助，无需旧密码）。

    可更新 email / full_name / phone / department / avatar。
    """
    authorization = request.headers.get("authorization")
    username = await get_current_user_from_header(authorization)
    user = (
        await db.execute(
            select(User).where(User.username == username, User.deleted_at.is_(None))
        )
    ).scalar_one_or_none()
    if user is None:
        raise AuthException(code=ErrorCode.AUTH_TOKEN_INVALID, message="用户不存在")

    if body.email is not None:
        user.email = body.email
    if body.full_name is not None:
        user.full_name = body.full_name
    if body.phone is not None:
        user.phone = body.phone
    if body.department is not None:
        user.department = body.department
    if body.avatar is not None:
        user.avatar = body.avatar
    await db.commit()
    await db.refresh(user)
    return success(data=UserResponse.model_validate(user).model_dump())


@router.post("/register")
@limiter.limit(AUTH_LIMIT)
@audit_action(action="auth.register", resource_type="user")
async def register(
    body: RegisterRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """用户注册（开放注册，默认普通用户）。

    校验用户名唯一性与密码强度。注册后可直接登录。
    生产环境可通过禁用本端点或加邀请码限制注册。
    """
    # 唯一性校验
    exists = await db.execute(
        select(User).where(
            User.username == body.username, User.deleted_at.is_(None)
        )
    )
    if exists.scalar_one_or_none() is not None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_USER_EXISTS,
            message=f"用户名已存在：{body.username}",
        )

    validate_password(body.password, hashed_history=[])

    user = User(
        username=body.username,
        email=body.email,
        hashed_password=hash_password(body.password),
        is_active=True,
        is_superuser=False,
        full_name=body.full_name,
    )
    db.add(user)
    await db.flush()
    db.add(PasswordHistory(user_id=user.id, hashed_password=user.hashed_password))
    await db.commit()
    await db.refresh(user)

    return success(data=UserResponse.model_validate(user).model_dump())


@router.post("/change-password")
@audit_action(action="auth.change_password", resource_type="user", capture_body=False)
async def change_password(
    body: PasswordChangeRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """修改密码（需提供旧密码）。

    流程：
    1. 从 Authorization 头解析当前用户。
    2. 校验旧密码。
    3. 校验新密码强度 + 历史（禁止复用最近 N 个旧密码）。
    4. 更新密码并记录历史。
    """
    authorization = request.headers.get("authorization")
    username = await get_current_user_from_header(authorization)
    user = (
        await db.execute(
            select(User).where(User.username == username, User.deleted_at.is_(None))
        )
    ).scalar_one_or_none()
    if user is None:
        raise AuthException(code=ErrorCode.AUTH_TOKEN_INVALID, message="用户不存在")

    if not verify_password(body.old_password, user.hashed_password):
        raise AuthException(code=ErrorCode.AUTH_TOKEN_INVALID, message="旧密码错误")

    # 历史密码
    hist_rows = await db.execute(
        select(PasswordHistory.hashed_password)
        .where(PasswordHistory.user_id == user.id)
        .order_by(PasswordHistory.created_at.desc())
        .limit(settings.PASSWORD_HISTORY_SIZE)
    )
    history = [r[0] for r in hist_rows.all()]
    validate_password(
        body.new_password, hashed_history=history, current_hashed=user.hashed_password
    )

    user.hashed_password = hash_password(body.new_password)
    user.password_changed_at = datetime.now(timezone.utc)
    db.add(PasswordHistory(user_id=user.id, hashed_password=user.hashed_password))

    # 清理旧历史
    all_hist = await db.execute(
        select(PasswordHistory)
        .where(PasswordHistory.user_id == user.id)
        .order_by(PasswordHistory.created_at.desc())
    )
    all_rows = all_hist.scalars().all()
    for old in all_hist.scalars().all()[settings.PASSWORD_HISTORY_SIZE:]:
        await db.delete(old)

    await db.commit()
    return success(message="密码修改成功")


@router.post("/reset-password")
@audit_action(action="auth.reset_password", resource_type="user", capture_body=False)
async def reset_password(
    body: PasswordResetRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """重置密码（携带重置令牌，无需旧密码）。

    令牌由超管通过 ``POST /users/{user_id}/reset-password`` 或线下分发，
    一次性使用，过期失效。
    """
    now = datetime.now(timezone.utc)
    token_row = (
        await db.execute(
            select(PasswordResetToken).where(PasswordResetToken.token == body.token)
        )
    ).scalar_one_or_none()

    if (
        token_row is None
        or token_row.used
        or token_row.expires_at < now
    ):
        raise BusinessException(
            code=ErrorCode.BUSINESS_RESET_TOKEN_INVALID,
            message="重置令牌无效或已过期",
        )

    user = await db.get(User, token_row.user_id)
    if user is None or user.deleted_at is not None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_USER_NOT_FOUND,
            message="用户不存在",
        )

    # 历史校验
    hist_rows = await db.execute(
        select(PasswordHistory.hashed_password)
        .where(PasswordHistory.user_id == user.id)
        .order_by(PasswordHistory.created_at.desc())
        .limit(settings.PASSWORD_HISTORY_SIZE)
    )
    history = [r[0] for r in hist_rows.all()]
    validate_password(
        body.new_password, hashed_history=history, current_hashed=user.hashed_password
    )

    user.hashed_password = hash_password(body.new_password)
    user.password_changed_at = now
    user.failed_login_count = 0
    user.locked_until = None
    token_row.used = True
    db.add(PasswordHistory(user_id=user.id, hashed_password=user.hashed_password))

    await db.commit()
    return success(message="密码已重置")
