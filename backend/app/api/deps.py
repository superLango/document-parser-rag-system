"""FastAPI 通用依赖模块。

本模块集中定义被各路由复用的依赖项，包括：

- ``get_current_user``：从 HTTP Bearer token 中解析当前用户。
- ``get_current_active_user``：在 ``get_current_user`` 基础上校验 ``is_active``。
- ``limiter``：基于 slowapi 的全局限流器实例，按客户端 IP 进行限流。
- ``get_pagination_params``：统一解析分页查询参数。

使用方式：
    from app.api.deps import get_current_active_user, limiter

    @router.get("/me", dependencies=[Depends(get_current_active_user)])
    @limiter.limit("10/minute")
    async def me(request: Request): ...
"""

from fastapi import Depends, Query
from fastapi.security import HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.database import get_db
from app.core.exceptions import AuthException, ErrorCode
from app.core.logging import get_logger
from app.core.security import verify_token
from app.models.user import User

logger = get_logger(__name__)

# HTTPBearer 依赖：从 Authorization: Bearer <token> 头中提取 token
# auto_error=False 由我们自行处理错误，避免泄露框架默认错误结构
bearer_scheme = HTTPBearer(auto_error=False)

# 全局限流器实例：按客户端远程 IP 作为限流 key
limiter = Limiter(key_func=get_remote_address)


async def get_current_user(
    token: str = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """解析 Bearer token 并返回当前用户。

    处理流程：
        1. 从 Authorization 头提取 Bearer token。
        2. 调用 ``verify_token`` 解码并校验 JWT。
        3. 从载荷中取出 ``sub``（用户名）查询数据库。
        4. 用户不存在则抛出 `AuthException`。

    Args:
        token: HTTPBearer 自动提取的凭据对象。
        db: 异步数据库会话。

    Returns:
        User: 当前请求对应的用户对象。

    Raises:
        AuthException: 未携带 token、token 无效或用户不存在。
    """
    # 未携带 Authorization 头或非 Bearer 方案
    if token is None or token.credentials is None:
        raise AuthException(
            code=ErrorCode.AUTH_TOKEN_INVALID,
            message="未提供访问令牌",
        )

    payload = verify_token(token.credentials)
    # JWT 的 sub 声明存放用户名
    username: str | None = payload.get("sub")
    if username is None:
        raise AuthException(
            code=ErrorCode.AUTH_TOKEN_INVALID,
            message="令牌载荷缺少用户信息",
        )

    stmt = select(User).where(User.username == username)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if user is None:
        logger.warning("令牌对应的用户不存在", username=username)
        raise AuthException(
            code=ErrorCode.AUTH_TOKEN_INVALID,
            message="令牌对应的用户不存在",
        )
    return user


async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """校验当前用户是否处于启用状态。

    在 ``get_current_user`` 之上叠加一层 ``is_active`` 检查，
    用于需要排除已停用账号的接口。

    Args:
        current_user: 由 ``get_current_user`` 注入的用户对象。

    Returns:
        User: 已激活的用户对象。

    Raises:
        AuthException: 用户被禁用时抛出，使用 ``AUTH_PERMISSION_DENIED`` 错误码。
    """
    if not current_user.is_active:
        raise AuthException(
            code=ErrorCode.AUTH_PERMISSION_DENIED,
            message="用户已被禁用",
        )
    return current_user


def get_pagination_params(
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数，1-100"),
) -> dict[str, int]:
    """解析分页查询参数。

    通过 FastAPI 的 ``Query`` 约束 page 与 page_size 的取值范围，
    统一返回字典以供业务层使用，与 `PaginationParams` 保持字段一致。

    Args:
        page: 页码，最小为 1。
        page_size: 每页条数，范围 1-100。

    Returns:
        dict[str, int]: 包含 ``page`` 与 ``page_size`` 的字典。
    """
    return {"page": page, "page_size": page_size}
