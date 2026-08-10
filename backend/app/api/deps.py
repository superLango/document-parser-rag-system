"""通用依赖：鉴权、限流、分页、RBAC 与 KB 上下文。"""

import uuid
from typing import Awaitable, Callable

from fastapi import Depends, Query
from fastapi.security import HTTPBearer
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings
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
from app.models.rbac import ROLE_SUPER_ADMIN
from app.models.user import User
from app.services.rbac_service import get_user_permissions, get_user_roles

logger = get_logger(__name__)

bearer_scheme = HTTPBearer(auto_error=False)
limiter = Limiter(key_func=get_remote_address)

# 分级限流
AUTH_LIMIT = settings.AUTH_LIMIT
UPLOAD_LIMIT = "10/minute"
AI_LIMIT = "20/minute"
DEFAULT_LIMIT = "60/minute"


async def get_current_user(
    token: str = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    if token is None or token.credentials is None:
        raise AuthException(
            code=ErrorCode.AUTH_TOKEN_INVALID, message="未提供访问令牌"
        )
    payload = verify_token(token.credentials)
    username: str | None = payload.get("sub")
    if username is None:
        raise AuthException(
            code=ErrorCode.AUTH_TOKEN_INVALID, message="令牌载荷缺少用户信息"
        )
    stmt = select(User).where(User.username == username, User.deleted_at.is_(None))
    user = (await db.execute(stmt)).scalar_one_or_none()
    if user is None:
        raise AuthException(
            code=ErrorCode.AUTH_TOKEN_INVALID, message="令牌对应的用户不存在"
        )
    return user


async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    if not current_user.is_active:
        raise AuthException(
            code=ErrorCode.AUTH_PERMISSION_DENIED, message="用户已被禁用"
        )
    return current_user


async def require_superuser(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """超管判定：兼容 is_superuser 字段与 super_admin 系统角色。"""
    if current_user.is_superuser:
        return current_user
    roles = await get_user_roles(db, current_user.id)
    if any(role.code == ROLE_SUPER_ADMIN for role in roles):
        return current_user
    raise PermissionException(
        code=ErrorCode.AUTH_PERMISSION_DENIED, message="需要超级管理员权限"
    )


def require_permission(*permission_codes: str) -> Callable[..., Awaitable[User]]:
    """权限点依赖：要求当前用户具备任一指定权限点。"""
    invalid = [c for c in permission_codes if not c]
    if invalid:
        raise ValueError("权限点编码不能为空")

    async def _check(
        current_user: User = Depends(get_current_active_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        if not permission_codes:
            return current_user
        perms = await get_user_permissions(db, current_user.id)
        if not any(code in perms for code in permission_codes):
            raise PermissionException(
                code=ErrorCode.AUTH_PERMISSION_DENIED,
                message=f"缺少权限：{', '.join(permission_codes)}",
            )
        return current_user

    return _check


def get_pagination_params(
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数，1-100"),
) -> dict[str, int]:
    return {"page": page, "page_size": page_size}


# ============================================================
# 知识库上下文（权限基础设施，KB 主流程迁移后启用）
# ============================================================
class KBContext:
    def __init__(
        self,
        kb_id: uuid.UUID,
        kb: KnowledgeBase,
        role: str,
        config: dict,
        user: User,
    ) -> None:
        self.kb_id = kb_id
        self.kb = kb
        self.role = role
        self.config = config
        self.user = user

    def has_role(self, *roles: str) -> bool:
        return self.role in roles


async def activate_rls(db: AsyncSession, kb_id: uuid.UUID) -> None:
    await db.execute(
        text("SELECT set_config('app.current_kb', :kb_id, true)"),
        {"kb_id": str(kb_id)},
    )


async def get_kb_context(
    kb_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> KBContext:
    kb = (
        await db.execute(
            select(KnowledgeBase).where(KnowledgeBase.id == kb_id)
        )
    ).scalar_one_or_none()
    if kb is None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_KB_NOT_FOUND, message=f"知识库 {kb_id} 不存在"
        )
    if not kb.is_active:
        raise BusinessException(
            code=ErrorCode.BUSINESS_KB_INACTIVE, message=f"知识库「{kb.name}」已停用"
        )
    if current_user.is_superuser:
        role = ROLE_OWNER
    else:
        role = (
            await db.execute(
                select(KbMember.role).where(
                    KbMember.kb_id == kb_id, KbMember.user_id == current_user.id
                )
            )
        ).scalar_one_or_none()
        if role is None:
            raise PermissionException(
                code=ErrorCode.AUTH_PERMISSION_DENIED,
                message=f"无权访问知识库「{kb.name}」",
            )
    await activate_rls(db, kb_id)
    return KBContext(
        kb_id=kb_id,
        kb=kb,
        role=role,
        config=kb.config if isinstance(kb.config, dict) else {},
        user=current_user,
    )


def require_role(*allowed_roles: str) -> Callable[..., Awaitable[KBContext]]:
    if allowed_roles:
        invalid = [r for r in allowed_roles if r not in ALL_ROLES]
        if invalid:
            raise ValueError(f"非法角色: {invalid}，合法角色为 {list(ALL_ROLES)}")

    async def _check_role(kb_ctx: KBContext = Depends(get_kb_context)) -> KBContext:
        if allowed_roles and not kb_ctx.has_role(*allowed_roles):
            raise PermissionException(
                code=ErrorCode.AUTH_PERMISSION_DENIED,
                message=f"需要 {', '.join(allowed_roles)} 角色权限",
            )
        return kb_ctx

    return _check_role
