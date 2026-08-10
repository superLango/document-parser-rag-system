"""P2 端点：工作空间、群组（部门）。"""

import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_pagination_params, require_not_pending
from app.core.database import get_db
from app.core.response import paginated, success
from app.middleware.audit_log import audit_action
from app.models.user import User
from app.schemas.workspace import (
    GroupCreate,
    GroupMemberAdd,
    GroupUpdate,
    WorkspaceCreate,
    WorkspaceMemberAdd,
    WorkspaceMemberRoleUpdate,
    WorkspaceTransferRequest,
    WorkspaceUpdate,
)
from app.services import workspace_service

router = APIRouter(prefix="/workspaces", tags=["工作空间"])


@router.get("")
async def list_workspaces(
    keyword: str | None = Query(None),
    pagination: dict = Depends(get_pagination_params),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> dict:
    items, total = await workspace_service.list_visible_workspaces(
        db, current_user, keyword, pagination["page"], pagination["page_size"]
    )
    return paginated(items, total, pagination["page"], pagination["page_size"])


@router.post("")
@audit_action(action="workspace.create", resource_type="workspace")
async def create_workspace(
    body: WorkspaceCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> dict:
    ws = await workspace_service.create_workspace(db, current_user, body)
    return success(data=await workspace_service.get_workspace(db, current_user, ws.id))


@router.get("/{workspace_id}")
async def get_workspace(
    workspace_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> dict:
    return success(data=await workspace_service.get_workspace(db, current_user, workspace_id))


@router.put("/{workspace_id}")
@audit_action(action="workspace.update", resource_type="workspace")
async def update_workspace(
    workspace_id: uuid.UUID,
    body: WorkspaceUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> dict:
    await workspace_service.update_workspace(db, current_user, workspace_id, body)
    return success(data=await workspace_service.get_workspace(db, current_user, workspace_id))


@router.delete("/{workspace_id}")
@audit_action(action="workspace.delete", resource_type="workspace")
async def delete_workspace(
    workspace_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> dict:
    await workspace_service.delete_workspace(db, current_user, workspace_id)
    return success(message="工作空间已删除")


# ---------- 成员 ----------
@router.get("/{workspace_id}/members")
async def list_members(
    workspace_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> dict:
    return success(data=await workspace_service.list_ws_members(db, current_user, workspace_id))


@router.post("/{workspace_id}/members")
@audit_action(action="workspace.member_add", resource_type="workspace")
async def add_member(
    workspace_id: uuid.UUID,
    body: WorkspaceMemberAdd,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> dict:
    member = await workspace_service.add_ws_member(
        db, current_user, workspace_id, body.username, body.role
    )
    return success(
        data={"id": str(member.id), "user_id": str(member.user_id), "role": member.role},
        message=f"成员已添加：{body.username}",
    )


@router.put("/{workspace_id}/members/{user_id}")
@audit_action(action="workspace.member_role", resource_type="workspace")
async def update_member_role(
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    body: WorkspaceMemberRoleUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> dict:
    await workspace_service.update_ws_member_role(
        db, current_user, workspace_id, user_id, body.role
    )
    return success(message="成员角色已更新")


@router.delete("/{workspace_id}/members/{user_id}")
@audit_action(action="workspace.member_remove", resource_type="workspace")
async def remove_member(
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> dict:
    await workspace_service.remove_ws_member(db, current_user, workspace_id, user_id)
    return success(message="成员已移除")


@router.post("/{workspace_id}/transfer")
@audit_action(action="workspace.transfer", resource_type="workspace")
async def transfer_ownership(
    workspace_id: uuid.UUID,
    body: WorkspaceTransferRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> dict:
    await workspace_service.transfer_ws_ownership(
        db, current_user, workspace_id, body.target_user_id
    )
    return success(message="所有权已转移")


# ---------- 群组（部门） ----------
@router.get("/{workspace_id}/groups")
async def list_groups(
    workspace_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> dict:
    return success(data=await workspace_service.list_groups(db, current_user, workspace_id))


@router.post("/{workspace_id}/groups")
@audit_action(action="workspace.group_create", resource_type="workspace")
async def create_group(
    workspace_id: uuid.UUID,
    body: GroupCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> dict:
    group = await workspace_service.create_group(db, current_user, workspace_id, body)
    return success(
        data={
            "id": str(group.id),
            "workspace_id": str(group.workspace_id),
            "name": group.name,
            "code": group.code,
            "description": group.description,
            "member_count": 0,
        }
    )


@router.put("/{workspace_id}/groups/{group_id}")
@audit_action(action="workspace.group_update", resource_type="workspace")
async def update_group(
    workspace_id: uuid.UUID,
    group_id: uuid.UUID,
    body: GroupUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> dict:
    group = await workspace_service.update_group(db, current_user, workspace_id, group_id, body)
    return success(data={"id": str(group.id), "name": group.name, "description": group.description})


@router.delete("/{workspace_id}/groups/{group_id}")
@audit_action(action="workspace.group_delete", resource_type="workspace")
async def delete_group(
    workspace_id: uuid.UUID,
    group_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> dict:
    await workspace_service.delete_group(db, current_user, workspace_id, group_id)
    return success(message="群组已删除")


@router.get("/{workspace_id}/groups/{group_id}/members")
async def list_group_members(
    workspace_id: uuid.UUID,
    group_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> dict:
    return success(
        data=await workspace_service.list_group_members(
            db, current_user, workspace_id, group_id
        )
    )


@router.post("/{workspace_id}/groups/{group_id}/members")
@audit_action(action="workspace.group_member_add", resource_type="workspace")
async def add_group_member(
    workspace_id: uuid.UUID,
    group_id: uuid.UUID,
    body: GroupMemberAdd,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> dict:
    await workspace_service.add_group_member(
        db, current_user, workspace_id, group_id, body.username
    )
    return success(message=f"群组成员已添加：{body.username}")


@router.delete("/{workspace_id}/groups/{group_id}/members/{user_id}")
@audit_action(action="workspace.group_member_remove", resource_type="workspace")
async def remove_group_member(
    workspace_id: uuid.UUID,
    group_id: uuid.UUID,
    user_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> dict:
    await workspace_service.remove_group_member(
        db, current_user, workspace_id, group_id, user_id
    )
    return success(message="群组成员已移除")
