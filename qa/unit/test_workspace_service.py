"""L1 单元测试：工作空间、群组并集授权、API Key（M13/M14/M15）。"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.core.exceptions import BusinessException, PermissionException, ValidationException
from app.core.security import hash_password
from app.models.api_key import ApiKey
from app.models.user import User
from app.models.workspace import GroupMember, Workspace, WorkspaceMember
from app.schemas.kb import KbCreate
from app.schemas.workspace import GroupCreate, WorkspaceCreate
from app.services import kb_service, rbac_service, workspace_service


async def _user(db, prefix: str, is_superuser: bool = False) -> User:
    user = User(
        username=f"{prefix}_{uuid.uuid4().hex[:8]}",
        hashed_password=hash_password("Test@1234"),
        is_superuser=is_superuser,
    )
    db.add(user)
    await db.flush()
    await rbac_service.ensure_user_default_role(db, user, is_superuser=is_superuser)
    await db.commit()
    await db.refresh(user)
    return user


async def _ws(db, owner: User, code: str | None = None) -> Workspace:
    return await workspace_service.create_workspace(
        db,
        owner,
        WorkspaceCreate(
            name="单测工作空间",
            code=code or f"ws_{uuid.uuid4().hex[:6]}",
            description="unit",
        ),
    )


async def _kb(db, owner: User) -> object:
    return await kb_service.create_kb(
        db,
        owner,
        KbCreate(name=f"kb_{uuid.uuid4().hex[:6]}", domain_code="general"),
    )


async def _group(db, owner: User, ws: Workspace, code: str | None = None) -> object:
    return await workspace_service.create_group(
        db,
        owner,
        ws.id,
        GroupCreate(
            name="研发组",
            code=code or f"grp_{uuid.uuid4().hex[:6]}",
        ),
    )


async def test_create_workspace_owner_member(db_session):
    owner = await _user(db_session, "ws_owner")
    ws = await _ws(db_session, owner)
    member = (
        await db_session.execute(
            select(WorkspaceMember).where(WorkspaceMember.workspace_id == ws.id)
        )
    ).scalars().first()
    assert member is not None
    assert member.role == "owner"
    assert member.status == "active"


async def test_workspace_visibility_scope(db_session):
    owner = await _user(db_session, "ws_vis_owner")
    other = await _user(db_session, "ws_vis_other")
    await _ws(db_session, owner)
    items, total = await workspace_service.list_visible_workspaces(db_session, other, None, 1, 20)
    assert total == 0
    items2, total2 = await workspace_service.list_visible_workspaces(db_session, owner, None, 1, 20)
    assert total2 == 1
    assert items2[0]["my_role"] == "owner"


async def test_workspace_member_add_guards(db_session):
    owner = await _user(db_session, "ws_add_owner")
    target = await _user(db_session, "ws_add_target")
    ws = await _ws(db_session, owner)
    with pytest.raises(ValidationException):
        await workspace_service.add_ws_member(db_session, owner, ws.id, target.username, "owner")
    member = await workspace_service.add_ws_member(db_session, owner, ws.id, target.username, "editor")
    assert member.role == "editor"
    with pytest.raises(ValidationException):
        await workspace_service.add_ws_member(db_session, owner, ws.id, target.username, "viewer")
    with pytest.raises(ValidationException):
        await workspace_service.add_ws_member(db_session, owner, ws.id, owner.username, "viewer")
    with pytest.raises(BusinessException):
        await workspace_service.add_ws_member(db_session, owner, ws.id, "ghost_user_zzz", "viewer")


async def test_workspace_role_and_remove_guards(db_session):
    owner = await _user(db_session, "ws_rm_owner")
    admin_user = await _user(db_session, "ws_rm_admin")
    viewer = await _user(db_session, "ws_rm_viewer")
    ws = await _ws(db_session, owner)
    await workspace_service.add_ws_member(db_session, owner, ws.id, admin_user.username, "admin")
    await workspace_service.add_ws_member(db_session, owner, ws.id, viewer.username, "viewer")
    with pytest.raises(ValidationException):
        await workspace_service.update_ws_member_role(db_session, owner, ws.id, owner.id, "admin")
    with pytest.raises(ValidationException):
        await workspace_service.update_ws_member_role(db_session, owner, ws.id, viewer.id, "owner")
    with pytest.raises(ValidationException):
        await workspace_service.remove_ws_member(db_session, owner, ws.id, owner.id)
    # viewer 可自助退出
    await workspace_service.remove_ws_member(db_session, viewer, ws.id, viewer.id)
    assert await workspace_service._get_ws_member(db_session, ws.id, viewer.id) is None
    # editor 不能管理
    editor = await _user(db_session, "ws_rm_editor")
    await workspace_service.add_ws_member(db_session, owner, ws.id, editor.username, "editor")
    with pytest.raises(PermissionException):
        await workspace_service.remove_ws_member(db_session, editor, ws.id, admin_user.id)


async def test_workspace_transfer_guards(db_session):
    owner = await _user(db_session, "ws_tr_owner")
    admin_user = await _user(db_session, "ws_tr_admin")
    stranger = await _user(db_session, "ws_tr_stranger")
    ws = await _ws(db_session, owner)
    await workspace_service.add_ws_member(db_session, owner, ws.id, admin_user.username, "admin")
    with pytest.raises(PermissionException):
        await workspace_service.transfer_ws_ownership(db_session, admin_user, ws.id, admin_user.id)
    with pytest.raises(BusinessException):
        await workspace_service.transfer_ws_ownership(db_session, owner, ws.id, stranger.id)
    await workspace_service.transfer_ws_ownership(db_session, owner, ws.id, admin_user.id)
    assert (await workspace_service._get_ws_member(db_session, ws.id, admin_user.id)).role == "owner"
    assert (await workspace_service._get_ws_member(db_session, ws.id, owner.id)).role == "admin"


async def test_group_create_duplicate_code(db_session):
    owner = await _user(db_session, "ws_grp_owner")
    ws = await _ws(db_session, owner)
    code = f"dup_{uuid.uuid4().hex[:6]}"
    await _group(db_session, owner, ws, code)
    with pytest.raises(ValidationException):
        await _group(db_session, owner, ws, code)


async def test_group_member_add_duplicate(db_session):
    owner = await _user(db_session, "ws_gm_owner")
    member = await _user(db_session, "ws_gm_member")
    ws = await _ws(db_session, owner)
    group = await _group(db_session, owner, ws)
    await workspace_service.add_group_member(db_session, owner, ws.id, group.id, member.username)
    with pytest.raises(ValidationException):
        await workspace_service.add_group_member(db_session, owner, ws.id, group.id, member.username)
    with pytest.raises(BusinessException):
        await workspace_service.add_group_member(db_session, owner, ws.id, group.id, "ghost_user_zzz")


async def test_effective_kb_role_union(db_session):
    """M14：直接 viewer + 群组 editor = editor（并集取最高）。"""
    owner = await _user(db_session, "kb_union_owner")
    viewer = await _user(db_session, "kb_union_viewer")
    ws = await _ws(db_session, owner)
    group = await _group(db_session, owner, ws)
    kb = await _kb(db_session, owner)
    # 直接成员 viewer
    inv = await kb_service.invite_member(db_session, owner, kb.id, viewer.username, "viewer", None)
    await kb_service.accept_invitation(db_session, viewer, inv.token)
    # 群组授权 editor + 群组成员
    await workspace_service.add_group_member(db_session, owner, ws.id, group.id, viewer.username)
    await workspace_service.grant_kb_to_group(db_session, owner, kb.id, group.id, "editor")
    role = await workspace_service.effective_kb_role(db_session, viewer.id, kb.id)
    assert role == "editor"
    # 撤销群组授权后回落到 viewer
    await workspace_service.revoke_kb_from_group(db_session, owner, kb.id, group.id)
    role2 = await workspace_service.effective_kb_role(db_session, viewer.id, kb.id)
    assert role2 == "viewer"


async def test_effective_kb_role_group_only(db_session):
    owner = await _user(db_session, "kb_union2_owner")
    member = await _user(db_session, "kb_union2_member")
    ws = await _ws(db_session, owner)
    group = await _group(db_session, owner, ws)
    kb = await _kb(db_session, owner)
    await workspace_service.add_group_member(db_session, owner, ws.id, group.id, member.username)
    await workspace_service.grant_kb_to_group(db_session, owner, kb.id, group.id, "admin")
    role = await workspace_service.effective_kb_role(db_session, member.id, kb.id)
    assert role == "admin"


async def test_grant_kb_to_group_requires_manage(db_session):
    owner = await _user(db_session, "kb_gr_owner")
    viewer = await _user(db_session, "kb_gr_viewer")
    ws = await _ws(db_session, owner)
    group = await _group(db_session, owner, ws)
    kb = await _kb(db_session, owner)
    inv = await kb_service.invite_member(db_session, owner, kb.id, viewer.username, "viewer", None)
    await kb_service.accept_invitation(db_session, viewer, inv.token)
    with pytest.raises(PermissionException):
        await workspace_service.grant_kb_to_group(db_session, viewer, kb.id, group.id, "viewer")
    with pytest.raises(BusinessException):
        await workspace_service.grant_kb_to_group(
            db_session, owner, kb.id, uuid.uuid4(), "viewer"
        )


async def test_api_key_lifecycle(db_session):
    user = await _user(db_session, "apikey_user")
    data, secret = await workspace_service.create_api_key(
        db_session, user, "CI", ["user.view"], None
    )
    assert secret.startswith("hd_")
    assert len(secret) >= 40
    row = (
        await db_session.execute(
            select(ApiKey).where(ApiKey.id == uuid.UUID(data["id"]))
        )
    ).scalar_one()
    assert row.key_hash != secret
    assert workspace_service.hash_api_key(secret) == row.key_hash
    result = await workspace_service.authenticate_api_key(db_session, secret)
    assert result is not None
    auth_user, scopes = result
    assert auth_user.id == user.id
    assert scopes == ["user.view"]
    assert await workspace_service.authenticate_api_key(db_session, "hd_wrong") is None
    await workspace_service.revoke_api_key(db_session, user, row.id)
    assert await workspace_service.authenticate_api_key(db_session, secret) is None


async def test_api_key_expired_rejected(db_session):
    user = await _user(db_session, "apikey_exp")
    _, secret = await workspace_service.create_api_key(
        db_session,
        user,
        "短效",
        [],
        datetime.now(timezone.utc) - timedelta(hours=1),
    )
    assert await workspace_service.authenticate_api_key(db_session, secret) is None
