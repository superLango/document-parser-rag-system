"""L1 单元测试：知识库资源级 ACL、邀请、所有权转移（M10/M11/M12）。"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.core.exceptions import BusinessException, PermissionException, ValidationException
from app.core.security import hash_password
from app.models.knowledge_base import (
    INVITATION_STATUS_PENDING,
    INVITATION_STATUS_REVOKED,
    MEMBER_STATUS_ACTIVE,
    MEMBER_STATUS_INVITED,
    MEMBER_STATUS_REMOVED,
    KbInvitation,
    KbMember,
    ROLE_OWNER,
    KnowledgeBase,
)
from app.models.user import User
from app.schemas.kb import KbCreate
from app.services import kb_service, rbac_service


async def _user(db, prefix: str, is_superuser: bool = False) -> User:
    user = User(
        username=f"{prefix}_{uuid.uuid4().hex[:8]}",
        hashed_password=hash_password("Test@1234"),
        is_superuser=is_superuser,
    )
    db.add(user)
    await db.flush()
    await rbac_service.ensure_user_default_role(
        db, user, is_superuser=is_superuser
    )
    await db.commit()
    await db.refresh(user)
    return user


async def _kb(db, owner: User, name: str = "单测知识库") -> KnowledgeBase:
    return await kb_service.create_kb(
        db,
        owner,
        KbCreate(name=name, description="unit", domain_code="general"),
    )


async def _invite(
    db, inviter: User, kb_id, invitee: User, role: str = "viewer"
) -> KbInvitation:
    return await kb_service.invite_member(
        db, inviter, kb_id, invitee.username, role, None
    )


async def _accept(db, invitee: User, invitation: KbInvitation) -> None:
    await kb_service.accept_invitation(db, invitee, invitation.token)


async def test_create_kb_owner_member(db_session):
    owner = await _user(db_session, "kb_owner")
    kb = await _kb(db_session, owner)
    member = (
        await db_session.execute(
            select(KbMember).where(KbMember.kb_id == kb.id)
        )
    ).scalars().first()
    assert member is not None
    assert member.role == ROLE_OWNER
    assert member.status == MEMBER_STATUS_ACTIVE


async def test_list_visible_kbs_scope(db_session):
    owner = await _user(db_session, "kb_list_owner")
    other = await _user(db_session, "kb_list_other")
    kb = await _kb(db_session, owner)
    items, total = await kb_service.list_visible_kbs(db_session, other, None, 1, 20)
    assert total == 0
    items2, total2 = await kb_service.list_visible_kbs(db_session, owner, None, 1, 20)
    assert total2 == 1
    assert items2[0]["my_role"] == "owner"
    assert items2[0]["member_count"] == 1


async def test_get_kb_denied_for_non_member(db_session):
    owner = await _user(db_session, "kb_get_owner")
    stranger = await _user(db_session, "kb_get_stranger")
    kb = await _kb(db_session, owner)
    with pytest.raises(PermissionException):
        await kb_service.get_kb(db_session, stranger, kb.id)


async def test_update_delete_denied_for_viewer_editor(db_session):
    owner = await _user(db_session, "kb_perm_owner")
    viewer = await _user(db_session, "kb_perm_viewer")
    editor = await _user(db_session, "kb_perm_editor")
    kb = await _kb(db_session, owner)
    inv_v = await _invite(db_session, owner, kb.id, viewer, "viewer")
    inv_e = await _invite(db_session, owner, kb.id, editor, "editor")
    await _accept(db_session, viewer, inv_v)
    await _accept(db_session, editor, inv_e)
    with pytest.raises(PermissionException):
        await kb_service.update_kb(
            db_session, viewer, kb.id, KbCreate(name="x", domain_code="g")
        )
    with pytest.raises(PermissionException):
        await kb_service.delete_kb(db_session, editor, kb.id)


async def test_member_role_owner_immutable_and_editor_cannot_manage(db_session):
    owner = await _user(db_session, "kb_role_owner")
    editor = await _user(db_session, "kb_role_editor")
    member = await _user(db_session, "kb_role_member")
    kb = await _kb(db_session, owner)
    inv_e = await _invite(db_session, owner, kb.id, editor, "editor")
    inv_m = await _invite(db_session, owner, kb.id, member, "viewer")
    await _accept(db_session, editor, inv_e)
    await _accept(db_session, member, inv_m)
    with pytest.raises(ValidationException):
        await kb_service.update_member_role(
            db_session, owner, kb.id, owner.id, "admin"
        )
    with pytest.raises(PermissionException):
        await kb_service.update_member_role(
            db_session, editor, kb.id, member.id, "admin"
        )


async def test_remove_owner_blocked_and_self_leave_allowed(db_session):
    owner = await _user(db_session, "kb_rm_owner")
    viewer = await _user(db_session, "kb_rm_viewer")
    kb = await _kb(db_session, owner)
    inv = await _invite(db_session, owner, kb.id, viewer, "viewer")
    await _accept(db_session, viewer, inv)
    with pytest.raises(ValidationException):
        await kb_service.remove_member(db_session, owner, kb.id, owner.id)
    await kb_service.remove_member(db_session, viewer, kb.id, viewer.id)
    assert await kb_service._get_member(db_session, kb.id, viewer.id) is None


async def test_transfer_ownership_guards(db_session):
    owner = await _user(db_session, "kb_tr_owner")
    admin_user = await _user(db_session, "kb_tr_admin")
    stranger = await _user(db_session, "kb_tr_stranger")
    kb = await _kb(db_session, owner)
    inv = await _invite(db_session, owner, kb.id, admin_user, "admin")
    await _accept(db_session, admin_user, inv)
    with pytest.raises(PermissionException):
        await kb_service.transfer_ownership(db_session, admin_user, kb.id, admin_user.id)
    with pytest.raises(BusinessException):
        await kb_service.transfer_ownership(db_session, owner, kb.id, stranger.id)
    await kb_service.transfer_ownership(db_session, owner, kb.id, admin_user.id)
    new_owner = await kb_service._get_member(db_session, kb.id, admin_user.id)
    old_owner = await kb_service._get_member(db_session, kb.id, owner.id)
    assert new_owner.role == ROLE_OWNER
    assert old_owner.role == "admin"
    kb2 = await kb_service._get_kb(db_session, kb.id)
    assert kb2.owner_id == admin_user.id


async def test_invite_validation_rules(db_session):
    owner = await _user(db_session, "kb_inv_owner")
    target = await _user(db_session, "kb_inv_target")
    kb = await _kb(db_session, owner)
    with pytest.raises(BusinessException):
        await kb_service.invite_member(
            db_session, owner, kb.id, "ghost_user_xyz", "viewer", None
        )
    with pytest.raises(ValidationException):
        await kb_service.invite_member(
            db_session, owner, kb.id, owner.username, "viewer", None
        )
    await _invite(db_session, owner, kb.id, target, "viewer")
    with pytest.raises(ValidationException):
        await kb_service.invite_member(
            db_session, owner, kb.id, target.username, "editor", None
        )


async def test_invite_creates_pending_member_and_invitation(db_session):
    owner = await _user(db_session, "kb_inv2_owner")
    target = await _user(db_session, "kb_inv2_target")
    kb = await _kb(db_session, owner)
    invitation = await _invite(db_session, owner, kb.id, target, "editor")
    assert invitation.status == INVITATION_STATUS_PENDING
    member = (
        await db_session.execute(
            select(KbMember).where(
                KbMember.kb_id == kb.id, KbMember.user_id == target.id
            )
        )
    ).scalars().first()
    assert member is not None and member.status == MEMBER_STATUS_INVITED
    mine = await kb_service.my_invitations(db_session, target)
    assert len(mine) == 1
    assert mine[0]["role"] == "editor"
    assert mine[0]["kb_name"] == "单测知识库"


async def test_accept_invitation_wrong_user_and_expired(db_session):
    owner = await _user(db_session, "kb_ac_owner")
    invitee = await _user(db_session, "kb_ac_invitee")
    stranger = await _user(db_session, "kb_ac_stranger")
    kb = await _kb(db_session, owner)
    invitation = await kb_service.invite_member(
        db_session,
        owner,
        kb.id,
        invitee.username,
        "viewer",
        datetime.now(timezone.utc) - timedelta(hours=1),
    )
    with pytest.raises(PermissionException):
        await kb_service.accept_invitation(db_session, stranger, invitation.token)
    with pytest.raises(ValidationException):
        await kb_service.accept_invitation(db_session, invitee, invitation.token)
    assert invitation.status == INVITATION_STATUS_REVOKED
    assert await kb_service._get_member(db_session, kb.id, invitee.id) is None


async def test_accept_invitation_success_and_revoke(db_session):
    owner = await _user(db_session, "kb_ok_owner")
    invitee = await _user(db_session, "kb_ok_invitee")
    second_invitee = await _user(db_session, "kb_ok_second")
    kb = await _kb(db_session, owner)
    invitation = await _invite(db_session, owner, kb.id, invitee, "viewer")
    result = await kb_service.accept_invitation(db_session, invitee, invitation.token)
    assert result["status"] == "accepted"
    member = await kb_service._get_member(db_session, kb.id, invitee.id)
    assert member is not None and member.status == MEMBER_STATUS_ACTIVE
    second = await _invite(db_session, owner, kb.id, second_invitee, "editor")
    await kb_service.revoke_invitation(db_session, owner, kb.id, second.id)
    assert second.status == INVITATION_STATUS_REVOKED


async def test_pending_role_assignment_and_approve(db_session):
    """M12：注册默认 pending 与审批后转为 member。"""
    operator = await _user(db_session, "kb_approver", is_superuser=True)
    user = await _user(db_session, "kb_pending")
    await rbac_service.assign_user_roles(db_session, operator, user, ["pending"])
    roles = await rbac_service.get_user_roles(db_session, user.id)
    assert [r.code for r in roles] == ["pending"]
    await rbac_service.assign_user_roles(db_session, operator, user, ["member"])
    roles2 = await rbac_service.get_user_roles(db_session, user.id)
    assert [r.code for r in roles2] == ["member"]
    assert user.is_superuser is False
