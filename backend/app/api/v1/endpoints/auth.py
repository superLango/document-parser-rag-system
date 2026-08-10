"""认证端点：登录、刷新、资料、注册、改密、重置。"""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AUTH_LIMIT, get_current_active_user, limiter
from app.core.database import get_db
from app.core.exceptions import AuthException, ErrorCode
from app.core.response import success
from app.middleware.audit_log import audit_action
from app.models.user import User
from app.schemas.rbac import RoleBrief
from app.schemas.user import (
    LoginRequest,
    PasswordChangeRequest,
    PasswordResetRequest,
    ProfileUpdate,
    RegisterRequest,
    UserResponse,
)
from app.services import auth_service, rbac_service

router = APIRouter(prefix="/auth", tags=["auth"])


async def _me_payload(db: AsyncSession, user: User) -> dict:
    roles = await rbac_service.get_user_roles(db, user.id)
    permissions = await rbac_service.get_user_permissions(db, user.id)
    data = UserResponse.model_validate(user).model_dump()
    data["roles"] = [RoleBrief.model_validate(r).model_dump() for r in roles]
    data["permissions"] = sorted(permissions)
    return data


@router.post("/login")
@limiter.limit(AUTH_LIMIT)
@audit_action(action="auth.login", resource_type="user", capture_body=False)
async def login(
    body: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    return success(data=await auth_service.login(db, request, body.username, body.password))


@router.post("/refresh")
@limiter.limit(AUTH_LIMIT)
async def refresh_token(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    authorization = request.headers.get("authorization")
    if not authorization:
        raise AuthException(
            code=ErrorCode.AUTH_TOKEN_INVALID, message="未提供刷新令牌"
        )
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise AuthException(
            code=ErrorCode.AUTH_TOKEN_INVALID, message="无效的令牌格式"
        )
    return success(data=await auth_service.refresh_access_token(db, parts[1]))


@router.get("/me")
async def get_me(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    return success(data=await _me_payload(db, current_user))


@router.put("/profile")
@audit_action(action="auth.update_profile", resource_type="user", capture_body=False)
async def update_profile(
    body: ProfileUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    user = await auth_service.update_profile(db, current_user, body)
    return success(data=await _me_payload(db, user))


@router.post("/register")
@limiter.limit(AUTH_LIMIT)
@audit_action(action="auth.register", resource_type="user")
async def register(
    body: RegisterRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    user = await auth_service.register(
        db, body.username, body.password, body.email, body.full_name
    )
    return success(data=await _me_payload(db, user))


@router.post("/change-password")
@audit_action(action="auth.change_password", resource_type="user", capture_body=False)
async def change_password(
    body: PasswordChangeRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    await auth_service.change_password(
        db, current_user, body.old_password, body.new_password
    )
    return success(message="密码修改成功")


@router.post("/reset-password")
@audit_action(action="auth.reset_password", resource_type="user", capture_body=False)
async def reset_password(
    body: PasswordResetRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    await auth_service.reset_password_with_token(db, body.token, body.new_password)
    return success(message="密码已重置")
