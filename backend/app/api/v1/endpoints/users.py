"""用户管理端点（RBAC P0：按权限点控制）。"""

import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_pagination_params, require_permission
from app.core.database import get_db
from app.core.response import paginated, success
from app.middleware.audit_log import audit_action
from app.models.user import User
from app.schemas.rbac import RoleBrief, UserRoleAssign
from app.schemas.user import UserCreate, UserResponse, UserUpdate
from app.services import rbac_service, user_service

router = APIRouter(prefix="/users", tags=["用户管理"])


def _serialize_user(
    user: User,
    roles: list | None = None,
    permissions: list | None = None,
) -> dict:
    data = UserResponse.model_validate(user).model_dump()
    data["roles"] = [
        RoleBrief.model_validate(r).model_dump()
        for r in (roles or [])
    ]
    if permissions is not None:
        data["permissions"] = sorted(permissions)
    return data


@router.get("")
async def list_users(
    keyword: str | None = Query(None, description="按用户名/邮箱/姓名模糊搜索"),
    is_active: bool | None = Query(None, description="按启用状态过滤"),
    pagination: dict = Depends(get_pagination_params),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("user.view")),
) -> dict:
    users, total = await user_service.list_users(
        db,
        keyword,
        is_active,
        pagination["page"],
        pagination["page_size"],
    )
    roles_map = await rbac_service.get_users_roles(db, [u.id for u in users])
    items = [_serialize_user(u, roles=roles_map.get(u.id, [])) for u in users]
    return paginated(items, total, pagination["page"], pagination["page_size"])


@router.post("")
@audit_action(action="user.create", resource_type="user")
async def create_user(
    body: UserCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("user.create")),
) -> dict:
    user = await user_service.create_user(db, current_user, body)
    roles = await rbac_service.get_user_roles(db, user.id)
    return success(data=_serialize_user(user, roles=roles))


@router.get("/{user_id}")
async def get_user(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("user.view")),
) -> dict:
    user = await user_service.get_user(db, user_id)
    roles = await rbac_service.get_user_roles(db, user.id)
    return success(data=_serialize_user(user, roles=roles))


@router.put("/{user_id}")
@audit_action(action="user.update", resource_type="user")
async def update_user(
    user_id: uuid.UUID,
    body: UserUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("user.update")),
) -> dict:
    user = await user_service.update_user(db, current_user, user_id, body)
    roles = await rbac_service.get_user_roles(db, user.id)
    return success(data=_serialize_user(user, roles=roles))


@router.put("/{user_id}/roles")
@audit_action(action="user.assign_roles", resource_type="user")
async def assign_user_roles(
    user_id: uuid.UUID,
    body: UserRoleAssign,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("user.manage")),
) -> dict:
    user = await user_service.get_user(db, user_id)
    roles = await rbac_service.assign_user_roles(db, current_user, user, body.role_codes)
    return success(
        data={
            "id": str(user.id),
            "roles": [RoleBrief.model_validate(r).model_dump() for r in roles],
        }
    )


@router.patch("/{user_id}/active")
@audit_action(action="user.toggle_active", resource_type="user")
async def toggle_active(
    user_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("user.manage")),
) -> dict:
    body = await request.json()
    user = await user_service.toggle_active(
        db, current_user, user_id, bool(body.get("is_active", True))
    )
    return success(data={"id": str(user.id), "is_active": user.is_active})


@router.patch("/{user_id}/superuser")
@audit_action(action="user.toggle_superuser", resource_type="user")
async def toggle_superuser(
    user_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("user.manage")),
) -> dict:
    body = await request.json()
    user = await user_service.toggle_superuser(
        db, current_user, user_id, bool(body.get("is_superuser", False))
    )
    return success(data={"id": str(user.id), "is_superuser": user.is_superuser})


@router.post("/{user_id}/approve")
@audit_action(action="user.approve", resource_type="user")
async def approve_user(
    user_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("user.manage")),
) -> dict:
    user = await user_service.get_user(db, user_id)
    roles = await rbac_service.assign_user_roles(
        db, current_user, user, ["member"]
    )
    return success(
        data={
            "id": str(user.id),
            "roles": [RoleBrief.model_validate(r).model_dump() for r in roles],
        },
        message="用户已审批通过",
    )


@router.post("/{user_id}/reset-password")
@audit_action(action="user.reset_password", resource_type="user")
async def admin_reset_password(
    user_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("user.reset_password")),
) -> dict:
    body = await request.json()
    new_password = body.get("new_password")
    if not new_password:
        from app.core.exceptions import ValidationException

        raise ValidationException(message="必须提供 new_password")
    await user_service.admin_reset_password(db, user_id, new_password)
    return success(message="密码已重置")


@router.delete("/{user_id}")
@audit_action(action="user.delete", resource_type="user")
async def delete_user(
    user_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("user.delete")),
) -> dict:
    await user_service.delete_user(db, current_user, user_id)
    return success(message="用户已删除")
