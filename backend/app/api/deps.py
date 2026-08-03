"""FastAPI 通用依赖模块。

本模块集中定义被各路由复用的依赖项，包括：

- ``get_current_user``：从 HTTP Bearer token 中解析当前用户。
- ``get_current_active_user``：在 ``get_current_user`` 基础上校验 ``is_active``。
- ``limiter``：基于 slowapi 的全局限流器实例，按客户端 IP 进行限流。
- ``get_pagination_params``：统一解析分页查询参数。
- ``KBContext`` / ``get_kb_context``：知识库上下文依赖，解析 ``kb_id`` 路径参数、
  校验成员身份（或超管）、激活 PostgreSQL RLS（``SET LOCAL app.current_kb``），
  返回携带 ``(kb_id, kb, role, config)`` 的上下文对象。
- ``require_role``：角色守卫依赖工厂，用于端点级权限校验。

使用方式：
    from app.api.deps import get_current_active_user, get_kb_context, require_role

    @router.get("/kbs/{kb_id}/documents")
    async def list_docs(kb_ctx: KBContext = Depends(get_kb_context)): ...

    @router.delete("/kbs/{kb_id}")
    async def delete_kb(kb_ctx: KBContext = Depends(require_role("owner"))): ...
"""

import uuid
from typing import Awaitable, Callable

from fastapi import Depends, Query
from fastapi.security import HTTPBearer
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.database import get_db
from app.core.exceptions import (
    AuthException,
    BusinessException,
    ErrorCode,
    PermissionException,
)
from app.core.logging import get_logger
from app.core.security import verify_token
from app.models.knowledge_base import (
    ALL_ROLES,
    KnowledgeBase,
    KbMember,
    ROLE_OWNER,
)
from app.models.user import User

logger = get_logger(__name__)

# HTTPBearer 依赖：从 Authorization: Bearer <token> 头中提取 token
# auto_error=False 由我们自行处理错误，避免泄露框架默认错误结构
bearer_scheme = HTTPBearer(auto_error=False)

# 全局限流器实例：按客户端远程 IP 作为限流 key
limiter = Limiter(key_func=get_remote_address)

# ============================================================
# 分级限流策略（阶段 3 - API 安全硬化）
# ============================================================
# 按端点敏感度与资源消耗分级，避免单一限流策略导致关键操作被普通流量挤占。
# 各端点通过 ``@limiter.limit(<策略>)`` 套用，需传入 ``request: Request`` 参数。
#
# 设计原则：
# - auth_limiter：登录/注册等认证端点，严格防爆破（5/分钟）
# - upload_limiter：文件上传/批量操作，防资源耗尽（10/分钟）
# - ai_limiter：LLM 抽取/问答等高成本 AI 调用，防滥用（20/分钟）
# - default_limiter：通用读端点（60/分钟）
AUTH_LIMIT = "5/minute"
UPLOAD_LIMIT = "10/minute"
AI_LIMIT = "20/minute"
DEFAULT_LIMIT = "60/minute"


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


async def require_superuser(
    current_user: User = Depends(get_current_active_user),
) -> User:
    """超管守卫依赖：非超管抛出 PermissionException（403）。

    用于全局跨 KB 端点（如全局仪表盘），避免普通用户查看其他 KB 的数据。
    与 KB 内 ``require_role`` 区分：后者校验 KB 成员角色，本依赖校验系统级超管。
    """
    if not current_user.is_superuser:
        raise PermissionException(
            code=ErrorCode.AUTH_PERMISSION_DENIED,
            message="需要超级管理员权限",
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


# ============================================================
# 知识库上下文（KBContext）依赖注入
# ============================================================
# 设计要点（见方案 §9.1 / §A.6）：
# 1. 所有 KB 内 API 路径形如 /kbs/{kb_id}/...，FastAPI 自动将 {kb_id} 路径参数
#    注入到 get_kb_context 的 kb_id 形参（类型 uuid.UUID，无需 Depends）。
# 2. 必须显式加入成员才能访问（决策 #4），superuser 可跨 KB 访问（决策 #6）。
# 3. 通过 set_config('app.current_kb', kb_id, true) 激活 PostgreSQL RLS：
#    - 业务表策略：kb_id::text = current_setting('app.current_kb', true)
#    - 基础三表策略：kb_id IS NULL OR kb_id::text = current_setting(...)
#    - set_config 第三个参数 true 等价于 SET LOCAL，仅在当前事务生效
#    - 参数化绑定，避免 SQL 注入；kb_id 必为 uuid.UUID（FastAPI 类型转换保证）
# 4. 当前若以 PostgreSQL 超级用户连接，RLS 被 FORCE 后 table owner 受约束、
#    但 superuser 仍绕过；故应用层 KBContext 仍是隔离兜底（方案 §0 迁移脚本注释）。


class KBContext:
    """知识库请求上下文。

    由 ``get_kb_context`` 依赖构造，贯穿单个 KB 内请求的全生命周期，承载：
    - 当前 KB 的 ORM 对象与配置 JSON
    - 当前用户在该 KB 中的角色（owner/admin/editor/viewer）
    - 已激活 RLS 的数据库会话（后续查询自动按 kb_id 过滤）

    Attributes:
        kb_id: 知识库唯一标识。
        kb: 知识库 ORM 对象（KnowledgeBase）。
        role: 当前用户在该 KB 中的角色；超管访问时为 ``owner``。
        config: 该 KB 的全流程配置 JSON（OCR/向量/抽取/问答/字典）。
        user: 当前已认证用户。
    """

    def __init__(
        self,
        kb_id: uuid.UUID,
        kb: KnowledgeBase,
        role: str,
        config: dict,
        user: User,
    ) -> None:
        self.kb_id: uuid.UUID = kb_id
        self.kb: KnowledgeBase = kb
        self.role: str = role
        self.config: dict = config
        self.user: User = user

    def has_role(self, *roles: str) -> bool:
        """判断当前角色是否在允许列表中。"""
        return self.role in roles


async def get_kb_context(
    kb_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> KBContext:
    """解析 kb_id 路径参数并构造知识库上下文。

    处理流程：
        1. 查询知识库是否存在；不存在抛出 ``BUSINESS_KB_NOT_FOUND``。
        2. 校验知识库启用状态；停用抛出 ``BUSINESS_KB_INACTIVE``。
        3. 校验成员身份：查询 ``kb_members`` 获取角色；非成员且非超管抛出
           ``AUTH_PERMISSION_DENIED``。超管（``is_superuser``）跨 KB 访问，
           角色按 ``owner`` 处理。
        4. 激活 RLS：执行 ``SELECT set_config('app.current_kb', :kb_id, true)``
           使当前事务后续所有查询受 RLS 策略约束。
        5. 返回 ``KBContext``。

    Args:
        kb_id: 由路径 ``/kbs/{kb_id}/...`` 自动注入的知识库 ID。
        current_user: 当前已认证且启用的用户。
        db: 异步数据库会话。

    Returns:
        KBContext: 知识库上下文对象。

    Raises:
        BusinessException: 知识库不存在（30006）或已停用（30007）。
        PermissionException: 非成员访问（20003）。
    """
    # 1. 查询知识库（不经过 RLS：knowledge_bases 表未启用 RLS，全局可见）
    kb_stmt = select(KnowledgeBase).where(KnowledgeBase.id == kb_id)
    kb_result = await db.execute(kb_stmt)
    kb: KnowledgeBase | None = kb_result.scalar_one_or_none()

    if kb is None:
        logger.warning("知识库不存在", kb_id=str(kb_id), user_id=str(current_user.id))
        raise BusinessException(
            code=ErrorCode.BUSINESS_KB_NOT_FOUND,
            message=f"知识库 {kb_id} 不存在",
        )

    # 2. 校验启用状态
    if not kb.is_active:
        logger.warning(
            "知识库已停用", kb_id=str(kb_id), kb_name=kb.name, user_id=str(current_user.id)
        )
        raise BusinessException(
            code=ErrorCode.BUSINESS_KB_INACTIVE,
            message=f"知识库「{kb.name}」已停用",
        )

    # 3. 校验成员身份（超管绕过成员校验，角色按 owner 处理）
    if current_user.is_superuser:
        role: str = ROLE_OWNER
        logger.debug(
            "超管访问知识库", kb_id=str(kb_id), user_id=str(current_user.id)
        )
    else:
        member_stmt = select(KbMember.role).where(
            KbMember.kb_id == kb_id, KbMember.user_id == current_user.id
        )
        member_result = await db.execute(member_stmt)
        role = member_result.scalar_one_or_none()
        if role is None:
            logger.warning(
                "非成员访问知识库被拒",
                kb_id=str(kb_id),
                user_id=str(current_user.id),
                username=current_user.username,
            )
            raise PermissionException(
                code=ErrorCode.AUTH_PERMISSION_DENIED,
                message=f"无权访问知识库「{kb.name}」",
            )

    # 4. 激活 PostgreSQL RLS：set_config 第三参数 true 等价于 SET LOCAL
    #    kb_id 为 uuid.UUID，str() 产出带连字符的标准格式，与 kb_id::text 对齐
    await activate_rls(db, kb_id)

    logger.debug(
        "知识库上下文已建立",
        kb_id=str(kb_id),
        kb_name=kb.name,
        role=role,
        user_id=str(current_user.id),
    )

    return KBContext(
        kb_id=kb_id,
        kb=kb,
        role=role,
        config=kb.config if isinstance(kb.config, dict) else {},
        user=current_user,
    )


async def activate_rls(db: AsyncSession, kb_id: uuid.UUID) -> None:
    """在指定数据库会话上激活 PostgreSQL RLS（``SET LOCAL app.current_kb``）。

    可复用的 RLS 激活辅助函数。``get_kb_context`` 在请求依赖中调用一次；
    长生命周期会话（如 SSE 流式生成器内独立创建的会话）需手动调用本函数，
    确保流式期间的查询仍按 ``kb_id`` 隔离。

    ``set_config`` 第三参数 ``true`` 等价于 ``SET LOCAL``，仅在当前事务生效；
    ``kb_id`` 使用 ``str(uuid)`` 带连字符格式，与 ``kb_id::text`` 对齐。

    Args:
        db: 异步数据库会话。
        kb_id: 知识库 ID。
    """
    await db.execute(
        text("SELECT set_config('app.current_kb', :kb_id, true)"),
        {"kb_id": str(kb_id)},
    )


def require_role(*allowed_roles: str) -> Callable[..., Awaitable[KBContext]]:
    """角色守卫依赖工厂。

    返回一个 FastAPI 依赖函数，先通过 ``get_kb_context`` 建立上下文，
    再校验当前角色是否在允许列表中。用于端点级权限控制。

    使用方式：
        @router.delete("/kbs/{kb_id}")
        async def delete_kb(kb_ctx: KBContext = Depends(require_role("owner"))): ...

        @router.put("/kbs/{kb_id}/config")
        async def update_config(
            kb_ctx: KBContext = Depends(require_role("owner", "admin")),
        ): ...

    Args:
        *allowed_roles: 允许访问的角色列表，取值见 ``app.models.knowledge_base.ALL_ROLES``
            （owner/admin/editor/viewer）。为空时仅要求是成员（任意角色）。

    Returns:
        依赖函数：解析并校验角色后返回 ``KBContext``。

    Raises:
        PermissionException: 当前角色不在允许列表时抛出（20003）。
        ValueError: 传入的角色不在 ``ALL_ROLES`` 中（编程错误，快速失败）。
    """
    # 校验角色合法性，避免拼写错误导致权限失效
    if allowed_roles:
        invalid = [r for r in allowed_roles if r not in ALL_ROLES]
        if invalid:
            raise ValueError(
                f"非法角色: {invalid}，合法角色为 {list(ALL_ROLES)}"
            )

    async def _check_role(kb_ctx: KBContext = Depends(get_kb_context)) -> KBContext:
        # 未指定 allowed_roles 时，任意成员均可访问（含 viewer）
        if allowed_roles and not kb_ctx.has_role(*allowed_roles):
            logger.warning(
                "角色权限不足",
                kb_id=str(kb_ctx.kb_id),
                user_id=str(kb_ctx.user.id),
                current_role=kb_ctx.role,
                required_roles=list(allowed_roles),
            )
            raise PermissionException(
                code=ErrorCode.AUTH_PERMISSION_DENIED,
                message=f"需要 {', '.join(allowed_roles)} 角色权限",
            )
        return kb_ctx

    return _check_role
