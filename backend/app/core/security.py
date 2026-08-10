"""JWT 与密码哈希核心能力。"""

from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt as _bcrypt
from jose import JWTError, jwt
from jose.exceptions import JWSError
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
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta
        if expires_delta is not None
        else timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def verify_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError as exc:
        if "expire" in str(exc).lower():
            raise AuthException(
                code=ErrorCode.AUTH_TOKEN_EXPIRED, message="令牌已过期，请重新登录"
            )
        raise AuthException(
            code=ErrorCode.AUTH_TOKEN_INVALID, message="无效的访问令牌"
        )
    except JWSError:
        raise AuthException(
            code=ErrorCode.AUTH_TOKEN_INVALID, message="无效的访问令牌"
        )


def create_refresh_token(data: dict[str, Any]) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def verify_refresh_token(token: str) -> dict[str, Any]:
    payload = verify_token(token)
    if payload.get("type") != "refresh":
        raise AuthException(
            code=ErrorCode.AUTH_TOKEN_INVALID, message="无效的刷新令牌"
        )
    return payload


def hash_password(password: str) -> str:
    return _bcrypt.hashpw(password.encode("utf-8"), _bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


async def authenticate_user(
    db: AsyncSession, username: str, password: str
) -> User | None:
    stmt = select(User).where(
        User.username == username, User.deleted_at.is_(None)
    )
    user = (await db.execute(stmt)).scalar_one_or_none()
    if user is None:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user
