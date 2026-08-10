"""角色与权限管理端点（P0）。"""

import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.core.database import get_db
from app.core.response import success
from app.middleware.audit_log import audit_action
from app.models.rbac import Permission, Role, RolePermission
from app.models.user import User
from app.schemas.rbac import (
    PermissionOut,
    RoleCreate,
    RolePermissionsUpdate,
    RoleUpdate,
)
from app.services import rbac_service

router = APIRouter(prefix="/roles", tags=["角色管理"])


def _role_dict(role: Role, permission_count: int | None = None) -> dict:
    data = {
        "id": str(role.id),
        "code": role.code,
        "name": role.name,
        "description": role.description,
        "is_system": role.is_system,
        "sort_order": role.sort_order,
        "created_at": role.created_at.isoformat() if role.created_at else None,
    }
    if permission_count is not None:
        data["permission_count"] = permission_count
    return data


@router.get("")
async def list_roles(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("role.view")),
) -> dict:
    roles = await rbac_service.list_roles(db)
    counts = dict(
        (
            await db.execute(
                select(RolePermission.role_id, func.count()).group_by(RolePermission.role_id)
            )
        ).all()
    )
    return success(
        data=[
            _role_dict(role, permission_count=counts.get(role.id, 0))
            for role in roles
        ]
    )


@router.get("/permissions")
async def list_permissions(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("role.view")),
) -> dict:
    permissions = await rbac_service.list_permissions(db)
    return success(data=[PermissionOut.model_validate(p).model_dump() for p in permissions])


@router.get("/{role_id}")
async def get_role(
    role_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("role.view")),
) -> dict:
    role = await rbac_service.get_role(db, role_id)
    perm_codes = await rbac_service.get_role_permission_codes(db, role.id)
    return success(data={**_role_dict(role), "permissions": sorted(perm_codes)})


@router.get("/{role_id}/permissions")
async def get_role_permissions(
    role_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("role.view")),
) -> dict:
    codes = await rbac_service.get_role_permission_codes(db, role_id)
    return success(data=sorted(codes))


@router.post("")
@audit_action(action="role.create", resource_type="role")
async def create_role(
    body: RoleCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("role.manage")),
) -> dict:
    role = await rbac_service.create_role(db, current_user, body)
    return success(data=_role_dict(role))


@router.put("/{role_id}")
@audit_action(action="role.update", resource_type="role")
async def update_role(
    role_id: uuid.UUID,
    body: RoleUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("role.manage")),
) -> dict:
    role = await rbac_service.update_role(db, current_user, role_id, body)
    return success(data=_role_dict(role))


@router.put("/{role_id}/permissions")
@audit_action(action="role.set_permissions", resource_type="role")
async def set_role_permissions(
    role_id: uuid.UUID,
    body: RolePermissionsUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("role.manage")),
) -> dict:
    codes = await rbac_service.set_role_permissions(
        db, current_user, role_id, body.permission_codes
    )
    return success(data=sorted(codes))


@router.delete("/{role_id}")
@audit_action(action="role.delete", resource_type="role")
async def delete_role(
    role_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("role.manage")),
) -> dict:
    await rbac_service.delete_role(db, current_user, role_id)
    return success(message="角色已删除")
