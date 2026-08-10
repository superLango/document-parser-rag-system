"""知识库资源级 ACL 端点（P1）。"""

import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_pagination_params, require_not_pending
from app.core.database import get_db
from app.core.response import paginated, success
from app.middleware.audit_log import audit_action
from app.models.user import User
from app.schemas.kb import (
    KbCreate,
    KbExternalUpdate,
    KbInviteCreate,
    KbMemberRoleUpdate,
    KbTransferRequest,
    KbUpdate,
)
from app.schemas.workspace import KbGroupGrant
from app.services import kb_service, workspace_service

router = APIRouter(prefix="/kb", tags=["知识库"])


@router.get("")
async def list_kbs(
    keyword: str | None = Query(None),
    pagination: dict = Depends(get_pagination_params),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> dict:
    items, total = await kb_service.list_visible_kbs(
        db,
        current_user,
        keyword,
        pagination["page"],
        pagination["page_size"],
    )
    return paginated(items, total, pagination["page"], pagination["page_size"])


@router.post("")
@audit_action(action="kb.create", resource_type="kb")
async def create_kb(
    body: KbCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> dict:
    kb, invited, failed = await kb_service.create_kb_with_members(
        db, current_user, body
    )
    data = await kb_service.get_kb(db, current_user, kb.id)
    data["invited"] = invited
    data["failed_invites"] = failed
    return success(data=data)


@router.get("/invitations/mine")
async def my_invitations(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> dict:
    return success(data=await kb_service.my_invitations(db, current_user))


@router.post("/invitations/{token}/accept")
@audit_action(action="kb.invite_accept", resource_type="kb")
async def accept_invitation(
    token: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> dict:
    return success(data=await kb_service.accept_invitation(db, current_user, token))


@router.get("/{kb_id}/overview")
async def get_kb_overview(
    kb_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> dict:
    return success(data=await kb_service.get_kb_overview(db, current_user, kb_id))


@router.get("/{kb_id}/external")
async def get_kb_external(
    kb_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> dict:
    return success(data=await kb_service.get_kb_external(db, current_user, kb_id))


@router.put("/{kb_id}/external")
@audit_action(action="kb.external_update", resource_type="kb")
async def update_kb_external(
    kb_id: uuid.UUID,
    body: KbExternalUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> dict:
    return success(
        data=await kb_service.update_kb_external(
            db, current_user, kb_id, body.enabled, body.regenerate
        )
    )


@router.get("/{kb_id}")
async def get_kb(
    kb_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> dict:
    return success(data=await kb_service.get_kb(db, current_user, kb_id))


@router.put("/{kb_id}")
@audit_action(action="kb.update", resource_type="kb")
async def update_kb(
    kb_id: uuid.UUID,
    body: KbUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> dict:
    await kb_service.update_kb(db, current_user, kb_id, body)
    return success(data=await kb_service.get_kb(db, current_user, kb_id))


@router.delete("/{kb_id}")
@audit_action(action="kb.delete", resource_type="kb")
async def delete_kb(
    kb_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> dict:
    await kb_service.delete_kb(db, current_user, kb_id)
    return success(message="知识库已删除")


@router.get("/{kb_id}/members")
async def list_members(
    kb_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> dict:
    return success(data=await kb_service.list_members(db, current_user, kb_id))


@router.post("/{kb_id}/invitations")
@audit_action(action="kb.invite", resource_type="kb")
async def invite_member(
    kb_id: uuid.UUID,
    body: KbInviteCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> dict:
    invitation = await kb_service.invite_member(
        db,
        current_user,
        kb_id,
        body.username,
        body.role,
        body.expires_at,
    )
    return success(
        data={
            "id": str(invitation.id),
            "token": invitation.token,
            "role": invitation.role,
            "expires_at": invitation.expires_at.isoformat() if invitation.expires_at else None,
        },
        message=f"邀请已发送给 {body.username}",
    )


@router.delete("/{kb_id}/invitations/{invitation_id}")
@audit_action(action="kb.invite_revoke", resource_type="kb")
async def revoke_invitation(
    kb_id: uuid.UUID,
    invitation_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> dict:
    await kb_service.revoke_invitation(db, current_user, kb_id, invitation_id)
    return success(message="邀请已撤销")


@router.get("/{kb_id}/groups")
async def list_kb_groups(
    kb_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> dict:
    return success(data=await workspace_service.list_kb_groups(db, current_user, kb_id))


@router.post("/{kb_id}/groups")
@audit_action(action="kb.group_grant", resource_type="kb")
async def grant_kb_to_group(
    kb_id: uuid.UUID,
    body: KbGroupGrant,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> dict:
    await workspace_service.grant_kb_to_group(
        db, current_user, kb_id, body.group_id, body.role
    )
    return success(message="群组授权已更新")


@router.delete("/{kb_id}/groups/{group_id}")
@audit_action(action="kb.group_revoke", resource_type="kb")
async def revoke_kb_from_group(
    kb_id: uuid.UUID,
    group_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> dict:
    await workspace_service.revoke_kb_from_group(db, current_user, kb_id, group_id)
    return success(message="群组授权已撤销")


@router.put("/{kb_id}/members/{user_id}")
@audit_action(action="kb.member_role", resource_type="kb")
async def update_member_role(
    kb_id: uuid.UUID,
    user_id: uuid.UUID,
    body: KbMemberRoleUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> dict:
    await kb_service.update_member_role(db, current_user, kb_id, user_id, body.role)
    return success(message="成员角色已更新")


@router.delete("/{kb_id}/members/{user_id}")
@audit_action(action="kb.member_remove", resource_type="kb")
async def remove_member(
    kb_id: uuid.UUID,
    user_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> dict:
    await kb_service.remove_member(db, current_user, kb_id, user_id)
    return success(message="成员已移除")


@router.post("/{kb_id}/transfer")
@audit_action(action="kb.transfer", resource_type="kb")
async def transfer_ownership(
    kb_id: uuid.UUID,
    body: KbTransferRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> dict:
    await kb_service.transfer_ownership(db, current_user, kb_id, body.target_user_id)
    return success(message="所有权已转移")
