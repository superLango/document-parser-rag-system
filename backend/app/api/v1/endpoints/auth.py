"""认证端点模块。

提供用户登录与当前用户信息查询接口：
- POST /auth/login：校验用户名密码并签发 JWT
- GET /auth/me：根据令牌返回当前用户信息

所有响应遵循统一响应体格式（见 app.core.response.success）。
"""

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import AuthException, ErrorCode
from app.core.response import success
from app.core.security import authenticate_user, create_access_token, verify_token
from app.models.user import User
from app.schemas.user import TokenResponse, UserResponse

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    """登录请求体。"""

    username: str
    password: str


async def get_current_user(
    authorization: str | None = Header(default=None),
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
async def login(
    body: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """用户登录接口。

    校验用户名与密码，成功后签发 JWT 访问令牌。

    Args:
        body: 登录请求体（用户名 + 密码）。
        db: 异步数据库会话（依赖注入）。

    Returns:
        dict: 统一响应体，``data`` 字段为 ``TokenResponse``。

    Raises:
        AuthException: 用户名或密码错误时返回 HTTP 401。
    """
    user = await authenticate_user(db, body.username, body.password)
    if user is None:
        raise AuthException(
            code=ErrorCode.AUTH_TOKEN_INVALID,
            message="用户名或密码错误",
        )
    # 签发 JWT，sub 声明存放用户名
    access_token = create_access_token(data={"sub": user.username})
    token_data = TokenResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=60 * 1440,
    )
    return success(data=token_data.model_dump())


@router.get("/me")
async def get_me(
    current_user: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取当前登录用户信息。

    Args:
        current_user: 当前用户名（由 get_current_user 依赖注入）。
        db: 异步数据库会话（依赖注入）。

    Returns:
        dict: 统一响应体，``data`` 字段为 ``UserResponse``。

    Raises:
        AuthException: 用户不存在时返回 HTTP 401。
    """
    stmt = select(User).where(User.username == current_user)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if user is None:
        raise AuthException(
            code=ErrorCode.AUTH_TOKEN_INVALID,
            message="用户不存在",
        )
    user_data = UserResponse.model_validate(user)
    return success(data=user_data.model_dump())
