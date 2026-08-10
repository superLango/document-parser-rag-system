"""P2 服务：工作空间、群组（部门）、群组并集授权、API Key。"""

import hashlib
import secrets
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessException, ErrorCode, PermissionException, ValidationException
from app.core.logging import get_logger
from app.models.knowledge_base import (
    MANAGE_ROLES,
    MEMBER_STATUS_ACTIVE,
    ROLE_OWNER,
    KbMember,
)
from app.models.api_key import ApiKey as ApiKeyModel
from app.models.user import User
from app.models.workspace import (
    WORKSPACE_MANAGE_ROLES,
    WORKSPACE_ROLE_OWNER,
    Group,
    GroupMember,
    KbGroupAccess,
    Workspace,
    WorkspaceMember,
)

logger = get_logger(__name__)

ROLE_RANK = {"owner": 4, "admin": 3, "editor": 2, "viewer": 1}


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _get_ws(db: AsyncSession, workspace_id: uuid.UUID) -> Workspace:
    ws = (
        await db.execute(
            select(Workspace).where(
                Workspace.id == workspace_id, Workspace.deleted_at.is_(None)
            )
        )
    ).scalar_one_or_none()
    if ws is None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_NOT_FOUND, message=f"工作空间 {workspace_id} 不存在"
        )
    return ws


async def _get_ws_member(
    db: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID
) -> WorkspaceMember | None:
    return (
        await db.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == user_id,
                WorkspaceMember.status == "active",
            )
        )
    ).scalar_one_or_none()


async def _require_ws_member(
    db: AsyncSession, workspace_id: uuid.UUID, user: User
) -> WorkspaceMember:
    member = await _get_ws_member(db, workspace_id, user.id)
    if member is None:
        raise PermissionException(message="您不是该工作空间成员")
    return member


async def list_visible_workspaces(
    db: AsyncSession,
    user: User,
    keyword: str | None,
    page: int,
    page_size: int,
) -> tuple[list[dict], int]:
    base = select(Workspace).where(Workspace.deleted_at.is_(None))
    count_base = select(func.count()).select_from(Workspace).where(Workspace.deleted_at.is_(None))
    if not user.is_superuser:
        sub = (
            select(WorkspaceMember.workspace_id)
            .where(
                WorkspaceMember.user_id == user.id,
                WorkspaceMember.status == "active",
            )
            .scalar_subquery()
        )
        cond = or_(Workspace.owner_id == user.id, Workspace.id.in_(sub))
        base = base.where(cond)
        count_base = count_base.where(cond)
    if keyword:
        like = f"%{keyword}%"
        base = base.where(Workspace.name.ilike(like))
        count_base = count_base.where(Workspace.name.ilike(like))
    total = (await db.execute(count_base)).scalar_one()
    workspaces = (
        await db.execute(
            base.order_by(Workspace.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()
    items = []
    for ws in workspaces:
        my_role = None
        if not user.is_superuser:
            m = await _get_ws_member(db, ws.id, user.id)
            my_role = m.role if m else None
        count = (
            await db.execute(
                select(func.count())
                .select_from(WorkspaceMember)
                .where(
                    WorkspaceMember.workspace_id == ws.id,
                    WorkspaceMember.status == "active",
                )
            )
        ).scalar_one()
        items.append(
            {
                "id": str(ws.id),
                "name": ws.name,
                "code": ws.code,
                "description": ws.description,
                "owner_id": str(ws.owner_id),
                "config": ws.config,
                "is_active": ws.is_active,
                "created_at": ws.created_at.isoformat() if ws.created_at else None,
                "my_role": my_role,
                "member_count": count,
            }
        )
    return items, total


async def create_workspace(db: AsyncSession, user: User, data) -> Workspace:
    exists = (
        await db.execute(select(Workspace).where(Workspace.code == data.code))
    ).scalar_one_or_none()
    if exists is not None:
        raise ValidationException(message=f"工作空间编码已存在：{data.code}")
    ws = Workspace(
        name=data.name,
        code=data.code,
        description=data.description,
        owner_id=user.id,
        config=data.config or {},
    )
    db.add(ws)
    await db.flush()
    db.add(
        WorkspaceMember(
            workspace_id=ws.id,
            user_id=user.id,
            role=WORKSPACE_ROLE_OWNER,
            status="active",
            invited_by=user.id,
        )
    )
    await db.commit()
    await db.refresh(ws)
    logger.info("工作空间已创建", workspace_id=str(ws.id), owner=str(user.id))
    return ws


async def get_workspace(db: AsyncSession, user: User, workspace_id: uuid.UUID) -> dict:
    ws = await _get_ws(db, workspace_id)
    if not user.is_superuser:
        await _require_ws_member(db, workspace_id, user)
    my_role = (
        (await _get_ws_member(db, workspace_id, user.id)).role
        if not user.is_superuser
        else WORKSPACE_ROLE_OWNER
    )
    count = (
        await db.execute(
            select(func.count())
            .select_from(WorkspaceMember)
            .where(WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.status == "active")
        )
    ).scalar_one()
    return {
        "id": str(ws.id),
        "name": ws.name,
        "code": ws.code,
        "description": ws.description,
        "owner_id": str(ws.owner_id),
        "config": ws.config,
        "is_active": ws.is_active,
        "created_at": ws.created_at.isoformat() if ws.created_at else None,
        "my_role": my_role,
        "member_count": count,
    }


async def update_workspace(db: AsyncSession, user: User, workspace_id: uuid.UUID, data) -> Workspace:
    ws = await _get_ws(db, workspace_id)
    if not user.is_superuser:
        member = await _require_ws_member(db, workspace_id, user)
        if member.role not in WORKSPACE_MANAGE_ROLES:
            raise PermissionException(message="需要管理员或所有者权限")
    if data.name is not None:
        ws.name = data.name
    if data.description is not None:
        ws.description = data.description
    if data.config is not None:
        ws.config = data.config
    await db.commit()
    await db.refresh(ws)
    return ws


async def delete_workspace(db: AsyncSession, user: User, workspace_id: uuid.UUID) -> None:
    ws = await _get_ws(db, workspace_id)
    if not user.is_superuser:
        member = await _require_ws_member(db, workspace_id, user)
        if member.role not in WORKSPACE_MANAGE_ROLES:
            raise PermissionException(message="需要管理员或所有者权限")
    ws.deleted_at = _now()
    ws.is_active = False
    await db.commit()


async def list_ws_members(db: AsyncSession, user: User, workspace_id: uuid.UUID) -> list[dict]:
    ws = await _get_ws(db, workspace_id)
    if not user.is_superuser:
        await _require_ws_member(db, workspace_id, user)
    rows = (
        await db.execute(
            select(WorkspaceMember, User.username, User.full_name)
            .join(User, User.id == WorkspaceMember.user_id)
            .where(WorkspaceMember.workspace_id == workspace_id)
            .order_by(WorkspaceMember.created_at)
        )
    ).all()
    return [
        {
            "id": str(m.id),
            "workspace_id": str(m.workspace_id),
            "user_id": str(m.user_id),
            "username": username,
            "full_name": full_name,
            "role": m.role,
            "status": m.status,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m, username, full_name in rows
    ]


async def add_ws_member(
    db: AsyncSession, operator: User, workspace_id: uuid.UUID, username: str, role: str
) -> WorkspaceMember:
    ws = await _get_ws(db, workspace_id)
    if not operator.is_superuser:
        member = await _require_ws_member(db, workspace_id, operator)
        if member.role not in WORKSPACE_MANAGE_ROLES:
            raise PermissionException(message="需要管理员或所有者权限")
    if role == WORKSPACE_ROLE_OWNER:
        raise ValidationException(message="不能直接添加所有者角色，请使用所有权转移")
    target = (
        await db.execute(
            select(User).where(User.username == username, User.deleted_at.is_(None))
        )
    ).scalar_one_or_none()
    if target is None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_USER_NOT_FOUND, message=f"用户不存在：{username}"
        )
    if target.id == operator.id:
        raise ValidationException(message="不能添加自己（你已是成员/所有者）")
    existing = (
        await db.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == target.id,
                WorkspaceMember.status != "removed",
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ValidationException(message=f"用户 {username} 已是该工作空间成员")
    member = WorkspaceMember(
        workspace_id=workspace_id,
        user_id=target.id,
        role=role,
        status="active",
        invited_by=operator.id,
    )
    db.add(member)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise ValidationException(message=f"用户 {username} 已在该工作空间中")
    await db.refresh(member)
    return member


async def update_ws_member_role(
    db: AsyncSession, operator: User, workspace_id: uuid.UUID, target_user_id: uuid.UUID, role: str
) -> None:
    ws = await _get_ws(db, workspace_id)
    if not operator.is_superuser:
        operator_member = await _require_ws_member(db, workspace_id, operator)
        if operator_member.role not in WORKSPACE_MANAGE_ROLES:
            raise PermissionException(message="需要管理员或所有者权限")
    if role == WORKSPACE_ROLE_OWNER:
        raise ValidationException(message="所有者角色不可直接修改，请使用所有权转移")
    target = await _get_ws_member(db, workspace_id, target_user_id)
    if target is None:
        raise BusinessException(message="目标用户不是有效成员")
    if target.role == WORKSPACE_ROLE_OWNER:
        raise ValidationException(message="不能修改所有者角色")
    target.role = role
    await db.commit()


async def remove_ws_member(
    db: AsyncSession, operator: User, workspace_id: uuid.UUID, target_user_id: uuid.UUID
) -> None:
    ws = await _get_ws(db, workspace_id)
    if not operator.is_superuser:
        operator_member = await _require_ws_member(db, workspace_id, operator)
        if operator_member.role not in WORKSPACE_MANAGE_ROLES and operator.id != target_user_id:
            raise PermissionException(message="需要管理员或所有者权限")
    target = await _get_ws_member(db, workspace_id, target_user_id)
    if target is None:
        raise BusinessException(message="目标用户不是有效成员")
    if target.role == WORKSPACE_ROLE_OWNER:
        raise ValidationException(message="不能移除所有者")
    target.status = "removed"
    await db.commit()


async def transfer_ws_ownership(
    db: AsyncSession, operator: User, workspace_id: uuid.UUID, target_user_id: uuid.UUID
) -> None:
    ws = await _get_ws(db, workspace_id)
    if not operator.is_superuser:
        operator_member = await _require_ws_member(db, workspace_id, operator)
        if operator_member.role != WORKSPACE_ROLE_OWNER:
            raise PermissionException(message="仅所有者可转移工作空间")
    target = await _get_ws_member(db, workspace_id, target_user_id)
    if target is None:
        raise BusinessException(message="目标用户不是有效成员")
    old_owner = await _get_ws_member(db, workspace_id, ws.owner_id)
    if old_owner is not None:
        old_owner.role = "admin"
    target.role = WORKSPACE_ROLE_OWNER
    ws.owner_id = target_user_id
    await db.commit()


# ---------------- 群组 ----------------
async def _get_group(db: AsyncSession, group_id: uuid.UUID) -> Group:
    group = (
        await db.execute(
            select(Group).where(Group.id == group_id, Group.deleted_at.is_(None))
        )
    ).scalar_one_or_none()
    if group is None:
        raise BusinessException(message=f"群组 {group_id} 不存在")
    return group


async def _require_group_manage(
    db: AsyncSession, operator: User, workspace_id: uuid.UUID
) -> None:
    ws = await _get_ws(db, workspace_id)
    if not operator.is_superuser:
        member = await _require_ws_member(db, workspace_id, operator)
        if member.role not in WORKSPACE_MANAGE_ROLES:
            raise PermissionException(message="需要管理员或所有者权限")


async def list_groups(db: AsyncSession, user: User, workspace_id: uuid.UUID) -> list[dict]:
    ws = await _get_ws(db, workspace_id)
    if not user.is_superuser:
        await _require_ws_member(db, workspace_id, user)
    groups = (
        await db.execute(
            select(Group)
            .where(Group.workspace_id == workspace_id, Group.deleted_at.is_(None))
            .order_by(Group.created_at)
        )
    ).scalars().all()
    items = []
    for group in groups:
        count = (
            await db.execute(
                select(func.count())
                .select_from(GroupMember)
                .where(GroupMember.group_id == group.id)
            )
        ).scalar_one()
        items.append(
            {
                "id": str(group.id),
                "workspace_id": str(group.workspace_id),
                "name": group.name,
                "code": group.code,
                "description": group.description,
                "created_at": group.created_at.isoformat() if group.created_at else None,
                "member_count": count,
            }
        )
    return items


async def create_group(db: AsyncSession, operator: User, workspace_id: uuid.UUID, data) -> Group:
    await _require_group_manage(db, operator, workspace_id)
    exists = (
        await db.execute(
            select(Group).where(
                Group.workspace_id == workspace_id,
                Group.code == data.code,
                Group.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if exists is not None:
        raise ValidationException(message=f"群组编码已存在：{data.code}")
    group = Group(
        workspace_id=workspace_id,
        name=data.name,
        code=data.code,
        description=data.description,
    )
    db.add(group)
    await db.commit()
    await db.refresh(group)
    return group


async def update_group(db: AsyncSession, operator: User, workspace_id: uuid.UUID, group_id: uuid.UUID, data) -> Group:
    await _require_group_manage(db, operator, workspace_id)
    group = await _get_group(db, group_id)
    if group.workspace_id != workspace_id:
        raise BusinessException(message="群组不属于该工作空间")
    if data.name is not None:
        group.name = data.name
    if data.description is not None:
        group.description = data.description
    await db.commit()
    await db.refresh(group)
    return group


async def delete_group(db: AsyncSession, operator: User, workspace_id: uuid.UUID, group_id: uuid.UUID) -> None:
    await _require_group_manage(db, operator, workspace_id)
    group = await _get_group(db, group_id)
    if group.workspace_id != workspace_id:
        raise BusinessException(message="群组不属于该工作空间")
    group.deleted_at = _now()
    await db.commit()


async def list_group_members(db: AsyncSession, user: User, workspace_id: uuid.UUID, group_id: uuid.UUID) -> list[dict]:
    if not user.is_superuser:
        await _require_ws_member(db, workspace_id, user)
    group = await _get_group(db, group_id)
    if group.workspace_id != workspace_id:
        raise BusinessException(message="群组不属于该工作空间")
    rows = (
        await db.execute(
            select(GroupMember, User.username, User.full_name)
            .join(User, User.id == GroupMember.user_id)
            .where(GroupMember.group_id == group_id)
            .order_by(GroupMember.created_at)
        )
    ).all()
    return [
        {
            "group_id": str(gm.group_id),
            "user_id": str(gm.user_id),
            "username": username,
            "full_name": full_name,
            "created_at": gm.created_at.isoformat() if gm.created_at else None,
        }
        for gm, username, full_name in rows
    ]


async def add_group_member(
    db: AsyncSession, operator: User, workspace_id: uuid.UUID, group_id: uuid.UUID, username: str
) -> None:
    await _require_group_manage(db, operator, workspace_id)
    group = await _get_group(db, group_id)
    if group.workspace_id != workspace_id:
        raise BusinessException(message="群组不属于该工作空间")
    target = (
        await db.execute(
            select(User).where(User.username == username, User.deleted_at.is_(None))
        )
    ).scalar_one_or_none()
    if target is None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_USER_NOT_FOUND, message=f"用户不存在：{username}"
        )
    existing = (
        await db.execute(
            select(GroupMember).where(
                GroupMember.group_id == group_id,
                GroupMember.user_id == target.id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ValidationException(message=f"用户 {username} 已在群组中")
    db.add(GroupMember(group_id=group_id, user_id=target.id))
    await db.commit()


async def remove_group_member(
    db: AsyncSession, operator: User, workspace_id: uuid.UUID, group_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    await _require_group_manage(db, operator, workspace_id)
    group = await _get_group(db, group_id)
    if group.workspace_id != workspace_id:
        raise BusinessException(message="群组不属于该工作空间")
    member = (
        await db.execute(
            select(GroupMember).where(
                GroupMember.group_id == group_id,
                GroupMember.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if member is None:
        raise BusinessException(message="该用户不在群组中")
    await db.delete(member)
    await db.commit()


# ---------------- 群组-知识库并集授权 ----------------
async def effective_kb_role(db: AsyncSession, user_id: uuid.UUID, kb_id: uuid.UUID) -> str | None:
    """有效角色 = max(直接成员角色, 群组授权角色)，即 FastGPT 式并集。"""
    best: str | None = None
    direct = (
        await db.execute(
            select(KbMember.role).where(
                KbMember.kb_id == kb_id,
                KbMember.user_id == user_id,
                KbMember.status == MEMBER_STATUS_ACTIVE,
            )
        )
    ).scalar_one_or_none()
    if direct is not None:
        best = direct
    group_roles = (
        await db.execute(
            select(KbGroupAccess.role)
            .join(GroupMember, GroupMember.group_id == KbGroupAccess.group_id)
            .where(
                KbGroupAccess.kb_id == kb_id,
                GroupMember.user_id == user_id,
                KbGroupAccess.role != ROLE_OWNER,
            )
        )
    ).scalars().all()
    for role in group_roles:
        if best is None or ROLE_RANK.get(role, 0) > ROLE_RANK.get(best, 0):
            best = role
    return best


async def list_kb_groups(db: AsyncSession, operator: User, kb_id: uuid.UUID) -> list[dict]:
    if not operator.is_superuser:
        direct = (
            await db.execute(
                select(KbMember).where(
                    KbMember.kb_id == kb_id,
                    KbMember.user_id == operator.id,
                    KbMember.status == MEMBER_STATUS_ACTIVE,
                )
            )
        ).scalar_one_or_none()
        if direct is None:
            raise PermissionException(message="您不是该知识库成员")
    rows = (
        await db.execute(
            select(KbGroupAccess, Group.name, Group.code, Workspace.name)
            .join(Group, Group.id == KbGroupAccess.group_id)
            .join(Workspace, Workspace.id == Group.workspace_id)
            .where(KbGroupAccess.kb_id == kb_id)
            .order_by(KbGroupAccess.created_at)
        )
    ).all()
    return [
        {
            "id": str(access.id),
            "kb_id": str(access.kb_id),
            "group_id": str(access.group_id),
            "group_name": group_name,
            "group_code": group_code,
            "workspace_name": workspace_name,
            "role": access.role,
            "created_at": access.created_at.isoformat() if access.created_at else None,
        }
        for access, group_name, group_code, workspace_name in rows
    ]


async def grant_kb_to_group(
    db: AsyncSession,
    operator: User,
    kb_id: uuid.UUID,
    group_id: uuid.UUID,
    role: str,
) -> None:
    if not operator.is_superuser:
        direct = (
            await db.execute(
                select(KbMember).where(
                    KbMember.kb_id == kb_id,
                    KbMember.user_id == operator.id,
                    KbMember.status == MEMBER_STATUS_ACTIVE,
                )
            )
        ).scalar_one_or_none()
        if direct is None or direct.role not in MANAGE_ROLES:
            raise PermissionException(message="需要知识库管理员或所有者权限")
    await _get_group(db, group_id)
    existing = (
        await db.execute(
            select(KbGroupAccess).where(
                KbGroupAccess.kb_id == kb_id,
                KbGroupAccess.group_id == group_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.role = role
    else:
        db.add(KbGroupAccess(kb_id=kb_id, group_id=group_id, role=role))
    await db.commit()


async def revoke_kb_from_group(
    db: AsyncSession, operator: User, kb_id: uuid.UUID, group_id: uuid.UUID
) -> None:
    if not operator.is_superuser:
        direct = (
            await db.execute(
                select(KbMember).where(
                    KbMember.kb_id == kb_id,
                    KbMember.user_id == operator.id,
                    KbMember.status == MEMBER_STATUS_ACTIVE,
                )
            )
        ).scalar_one_or_none()
        if direct is None or direct.role not in MANAGE_ROLES:
            raise PermissionException(message="需要知识库管理员或所有者权限")
    access = (
        await db.execute(
            select(KbGroupAccess).where(
                KbGroupAccess.kb_id == kb_id,
                KbGroupAccess.group_id == group_id,
            )
        )
    ).scalar_one_or_none()
    if access is None:
        raise BusinessException(message="该群组未授权此知识库")
    await db.delete(access)
    await db.commit()


# ---------------- API Key ----------------
def hash_api_key(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


async def create_api_key(
    db: AsyncSession, user: User, name: str, scopes: list[str], expires_at: datetime | None
) -> tuple[dict, str]:
    secret = "hd_" + secrets.token_urlsafe(32)
    key = ApiKeyModel(
        user_id=user.id,
        name=name,
        key_prefix=secret[:10],
        key_hash=hash_api_key(secret),
        scopes=list(dict.fromkeys(scopes)),
        expires_at=expires_at,
    )
    db.add(key)
    await db.commit()
    await db.refresh(key)
    return {
        "id": str(key.id),
        "name": key.name,
        "key_prefix": key.key_prefix,
        "scopes": key.scopes,
        "expires_at": key.expires_at.isoformat() if key.expires_at else None,
        "last_used_at": key.last_used_at.isoformat() if key.last_used_at else None,
        "created_at": key.created_at.isoformat() if key.created_at else None,
        "revoked_at": key.revoked_at.isoformat() if key.revoked_at else None,
    }, secret


async def list_api_keys(db: AsyncSession, user: User) -> list[dict]:
    keys = (
        await db.execute(
            select(ApiKeyModel)
            .where(ApiKeyModel.user_id == user.id)
            .order_by(ApiKeyModel.created_at.desc())
        )
    ).scalars().all()
    return [
        {
            "id": str(k.id),
            "name": k.name,
            "key_prefix": k.key_prefix,
            "scopes": k.scopes,
            "expires_at": k.expires_at.isoformat() if k.expires_at else None,
            "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
            "created_at": k.created_at.isoformat() if k.created_at else None,
            "revoked_at": k.revoked_at.isoformat() if k.revoked_at else None,
        }
        for k in keys
    ]


async def revoke_api_key(db: AsyncSession, user: User, key_id: uuid.UUID) -> None:
    key = await db.get(ApiKeyModel, key_id)
    if key is None or key.user_id != user.id:
        raise BusinessException(message="API Key 不存在")
    if key.revoked_at is None:
        key.revoked_at = _now()
        await db.commit()


async def authenticate_api_key(db: AsyncSession, secret: str) -> tuple[User, list[str]] | None:
    if not secret.startswith("hd_"):
        return None
    key = (
        await db.execute(
            select(ApiKeyModel).where(ApiKeyModel.key_hash == hash_api_key(secret))
        )
    ).scalar_one_or_none()
    if key is None or key.revoked_at is not None:
        return None
    if key.expires_at is not None and key.expires_at < _now():
        return None
    user = await db.get(User, key.user_id)
    if user is None or not user.is_active or user.deleted_at is not None:
        return None
    key.last_used_at = _now()
    await db.commit()
    return user, list(key.scopes or [])

