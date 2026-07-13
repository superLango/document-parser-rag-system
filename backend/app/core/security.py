"""安全与鉴权核心模块。

本模块提供 JWT 鉴权与密码加密所需的全部底层能力，包括：

- ``create_access_token``：基于 ``settings.SECRET_KEY`` 与 ``settings.ALGORITHM``
  签发 JWT，支持自定义过期时间。
- ``verify_token``：解码并校验 JWT，失败时抛出 `AuthException`。
- ``hash_password`` / ``verify_password``：基于 passlib bcrypt 的密码哈希与校验。
- ``authenticate_user``：按用户名查询数据库并校验密码，返回用户对象或 None。

使用方式：
    from app.core.security import create_access_token, authenticate_user

    token = create_access_token({"sub": user.username})
    user = await authenticate_user(db, username, password)

注意：
    生产环境下 ``settings.SECRET_KEY`` 必须替换为高熵随机值，切勿使用默认值。
    bcrypt 哈希计算较慢，是预期的安全开销，请避免在高频路径中重复调用。
"""

from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt as _bcrypt
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AuthException, ErrorCode
from app.core.logging import get_logger
from app.models.user import User

logger = get_logger(__name__)


def create_access_token(
    data: dict[str, Any], expires_delta: timedelta | None = None
) -> str:
    """创建 JWT 访问令牌。

    将传入的 ``data`` 拷贝后注入 ``exp``（过期时间）声明，再使用
    ``settings.SECRET_KEY`` 与 ``settings.ALGORITHM`` 进行签名。

    Args:
        data: 需要写入 JWT 载荷的自定义声明，例如 ``{"sub": "alice"}``。
            注意：``exp`` 会被本函数覆盖。
        expires_delta: 自定义过期时长。为 None 时使用
            ``settings.ACCESS_TOKEN_EXPIRE_MINUTES`` 作为默认过期时长。

    Returns:
        str: 签名后的 JWT 字符串。
    """
    to_encode = data.copy()
    if expires_delta is not None:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )
    to_encode.update({"exp": expire})
    return jwt.encode(
        to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM
    )


def verify_token(token: str) -> dict[str, Any]:
    """解码并校验 JWT。

    校验签名与过期时间，失败时抛出 `AuthException` 并携带对应的错误码，
    便于上层统一转换为符合 API 契约的响应体。

    Args:
        token: 待校验的 JWT 字符串。

    Returns:
        dict[str, Any]: 解码后的 JWT 载荷字典。

    Raises:
        AuthException: token 过期时使用 ``AUTH_TOKEN_EXPIRED``，
            其他无效场景使用 ``AUTH_TOKEN_INVALID``。
    """
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        return payload
    except JWTError as exc:
        # jose 在 token 过期时抛出的错误信息包含 "expire"
        if "expire" in str(exc).lower():
            logger.warning("JWT 已过期", error=str(exc))
            raise AuthException(
                code=ErrorCode.AUTH_TOKEN_EXPIRED,
                message="令牌已过期，请重新登录",
            )
        logger.warning("JWT 校验失败", error=str(exc))
        raise AuthException(
            code=ErrorCode.AUTH_TOKEN_INVALID,
            message="无效的访问令牌",
        )


def hash_password(password: str) -> str:
    """使用 bcrypt 对明文密码进行哈希。

    passlib 内部会自动生成盐值并嵌入哈希结果，因此无需单独存储盐。

    Args:
        password: 明文密码。

    Returns:
        str: bcrypt 哈希字符串，可直接持久化到数据库。
    """
    return _bcrypt.hashpw(
        password.encode("utf-8"), _bcrypt.gensalt()
    ).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """校验明文密码与已存储的哈希是否匹配。

    Args:
        plain: 用户提交的明文密码。
        hashed: 数据库中存储的哈希字符串。

    Returns:
        bool: 匹配返回 True，否则返回 False。
    """
    return _bcrypt.checkpw(
        plain.encode("utf-8"), hashed.encode("utf-8")
    )


async def authenticate_user(
    db: AsyncSession, username: str, password: str
) -> User | None:
    """按用户名查询用户并校验密码。

    流程：
        1. 通过 ``username`` 查询 users 表。
        2. 若用户不存在则返回 None。
        3. 调用 ``verify_password`` 校验密码，匹配则返回用户对象，
           否则返回 None。

    Args:
        db: 异步数据库会话。
        username: 用户名。
        password: 明文密码。

    Returns:
        User | None: 认证成功返回 User 实例，失败返回 None。
    """
    stmt = select(User).where(User.username == username)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if user is None:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user
