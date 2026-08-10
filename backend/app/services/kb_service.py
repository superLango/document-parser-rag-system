"""知识库资源级 ACL 服务（P1）：成员、邀请、审批、所有权转移。"""

import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import BusinessException, ErrorCode, PermissionException, ValidationException
from app.core.logging import get_logger
from app.models.knowledge_base import (
    INVITATION_STATUS_ACCEPTED,
    INVITATION_STATUS_PENDING,
    INVITATION_STATUS_REVOKED,
    MANAGE_ROLES,
    MEMBER_STATUS_ACTIVE,
    MEMBER_STATUS_INVITED,
    MEMBER_STATUS_REMOVED,
    ROLE_OWNER,
    KbInvitation,
    KbMember,
    KnowledgeBase,
)
from app.models.workspace import GroupMember, KbGroupAccess
from app.models.user import User
from app.services.workspace_service import effective_kb_role

logger = get_logger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _get_member(
    db: AsyncSession, kb_id: uuid.UUID, user_id: uuid.UUID
) -> KbMember | None:
    return (
        await db.execute(
            select(KbMember).where(
                KbMember.kb_id == kb_id,
                KbMember.user_id == user_id,
                KbMember.status == MEMBER_STATUS_ACTIVE,
            )
        )
    ).scalar_one_or_none()


async def _require_member(
    db: AsyncSession, kb_id: uuid.UUID, user: User
) -> KbMember:
    member = await _get_member(db, kb_id, user.id)
    if member is None:
        raise PermissionException(message="您不是该知识库成员")
    return member


async def _require_effective_member(
    db: AsyncSession, kb_id: uuid.UUID, user: User
) -> str:
    """按并集授权计算有效角色；无任何访问权限则拒绝。"""
    role = await effective_kb_role(db, user.id, kb_id)
    if role is None:
        raise PermissionException(message="您不是该知识库成员")
    return role


async def _get_kb(db: AsyncSession, kb_id: uuid.UUID) -> KnowledgeBase:
    kb = (
        await db.execute(
            select(KnowledgeBase).where(
                KnowledgeBase.id == kb_id, KnowledgeBase.deleted_at.is_(None)
            )
        )
    ).scalar_one_or_none()
    if kb is None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_KB_NOT_FOUND, message=f"知识库 {kb_id} 不存在"
        )
    return kb


async def list_visible_kbs(
    db: AsyncSession,
    user: User,
    keyword: str | None,
    page: int,
    page_size: int,
) -> tuple[list[dict], int]:
    base = select(KnowledgeBase).where(KnowledgeBase.deleted_at.is_(None))
    count_base = select(func.count()).select_from(KnowledgeBase).where(KnowledgeBase.deleted_at.is_(None))
    if not user.is_superuser:
        sub = (
            select(KbMember.kb_id)
            .where(
                KbMember.user_id == user.id,
                KbMember.status == MEMBER_STATUS_ACTIVE,
            )
            .scalar_subquery()
        )
        group_sub = (
            select(KbGroupAccess.kb_id)
            .join(GroupMember, GroupMember.group_id == KbGroupAccess.group_id)
            .where(GroupMember.user_id == user.id)
            .scalar_subquery()
        )
        cond = or_(
            KnowledgeBase.owner_id == user.id,
            KnowledgeBase.id.in_(sub),
            KnowledgeBase.id.in_(group_sub),
        )
        base = base.where(cond)
        count_base = count_base.where(cond)
    if keyword:
        like = f"%{keyword}%"
        base = base.where(KnowledgeBase.name.ilike(like))
        count_base = count_base.where(KnowledgeBase.name.ilike(like))
    total = (await db.execute(count_base)).scalar_one()
    kbs = (
        await db.execute(
            base.order_by(KnowledgeBase.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()

    items: list[dict] = []
    for kb in kbs:
        my_role = None
        if not user.is_superuser:
            my_role = await effective_kb_role(db, user.id, kb.id)
        member_count = (
            await db.execute(
                select(func.count())
                .select_from(KbMember)
                .where(
                    KbMember.kb_id == kb.id,
                    KbMember.status == MEMBER_STATUS_ACTIVE,
                )
            )
        ).scalar_one()
        items.append(
            {
                "id": str(kb.id),
                "name": kb.name,
                "description": kb.description,
                "domain_code": kb.domain_code,
                "template_code": kb.template_code,
                "owner_id": str(kb.owner_id),
                "config": kb.config,
                "is_active": kb.is_active,
                "created_at": kb.created_at.isoformat() if kb.created_at else None,
                "updated_at": kb.updated_at.isoformat() if kb.updated_at else None,
                "my_role": my_role,
                "member_count": member_count,
            }
        )
    return items, total


async def create_kb(db: AsyncSession, user: User, data) -> KnowledgeBase:
    kb = KnowledgeBase(
        name=data.name,
        description=data.description,
        domain_code=data.domain_code,
        template_code=data.template_code,
        owner_id=user.id,
        config=data.config or {},
    )
    db.add(kb)
    await db.flush()
    db.add(
        KbMember(
            kb_id=kb.id,
            user_id=user.id,
            role=ROLE_OWNER,
            status=MEMBER_STATUS_ACTIVE,
            invited_by=user.id,
        )
    )
    await db.commit()
    await db.refresh(kb)
    logger.info("知识库已创建", kb_id=str(kb.id), owner=str(user.id))
    return kb


async def create_kb_with_members(
    db: AsyncSession, user: User, data
) -> tuple[KnowledgeBase, list[str], list[dict]]:
    """创建知识库并批量邀请初始成员；失败项收集返回，不阻断创建。"""
    kb = await create_kb(db, user, data)
    invited: list[str] = []
    failed: list[dict] = []
    seen: set[str] = set()
    for seed in data.members or []:
        if seed.username in seen:
            continue
        seen.add(seed.username)
        try:
            await invite_member(db, user, kb.id, seed.username, seed.role, None)
            invited.append(seed.username)
        except Exception as exc:  # 单成员失败不影响整体创建
            failed.append({"username": seed.username, "error": str(exc)[:200]})
    return kb, invited, failed


async def get_kb(db: AsyncSession, user: User, kb_id: uuid.UUID) -> dict:
    kb = await _get_kb(db, kb_id)
    if not user.is_superuser:
        await _require_member(db, kb_id, user)
    my_role = (
        await effective_kb_role(db, user.id, kb_id)
        if not user.is_superuser
        else ROLE_OWNER
    )
    member_count = (
        await db.execute(
            select(func.count())
            .select_from(KbMember)
            .where(KbMember.kb_id == kb_id, KbMember.status == MEMBER_STATUS_ACTIVE)
        )
    ).scalar_one()
    return {
        "id": str(kb.id),
        "name": kb.name,
        "description": kb.description,
        "domain_code": kb.domain_code,
        "template_code": kb.template_code,
        "owner_id": str(kb.owner_id),
        "config": kb.config,
        "is_active": kb.is_active,
        "created_at": kb.created_at.isoformat() if kb.created_at else None,
        "updated_at": kb.updated_at.isoformat() if kb.updated_at else None,
        "my_role": my_role,
        "member_count": member_count,
    }


async def update_kb(db: AsyncSession, user: User, kb_id: uuid.UUID, data) -> KnowledgeBase:
    kb = await _get_kb(db, kb_id)
    if not user.is_superuser:
        role = await _require_effective_member(db, kb_id, user)
        if role not in MANAGE_ROLES:
            raise PermissionException(message="需要管理员或所有者权限")
    if data.name is not None:
        kb.name = data.name
    if data.description is not None:
        kb.description = data.description
    if data.domain_code is not None:
        kb.domain_code = data.domain_code
    if data.template_code is not None:
        kb.template_code = data.template_code
    if data.config is not None:
        kb.config = data.config
    await db.commit()
    await db.refresh(kb)
    return kb


async def delete_kb(db: AsyncSession, user: User, kb_id: uuid.UUID) -> None:
    kb = await _get_kb(db, kb_id)
    if not user.is_superuser:
        role = await _require_effective_member(db, kb_id, user)
        if role not in MANAGE_ROLES:
            raise PermissionException(message="需要管理员或所有者权限")
    kb.deleted_at = _now()
    kb.is_active = False
    await db.commit()


async def list_members(
    db: AsyncSession, user: User, kb_id: uuid.UUID
) -> list[dict]:
    kb = await _get_kb(db, kb_id)
    if not user.is_superuser:
        await _require_member(db, kb_id, user)
    rows = (
        await db.execute(
            select(KbMember, User.username, User.full_name, User.department, User.email)
            .join(User, User.id == KbMember.user_id)
            .where(KbMember.kb_id == kb_id)
            .order_by(KbMember.created_at)
        )
    ).all()
    return [
        {
            "id": str(m.id),
            "kb_id": str(m.kb_id),
            "user_id": str(m.user_id),
            "username": username,
            "full_name": full_name,
            "department": department,
            "email": email,
            "role": m.role,
            "status": m.status,
            "invited_by": str(m.invited_by) if m.invited_by else None,
            "expires_at": m.expires_at.isoformat() if m.expires_at else None,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m, username, full_name, department, email in rows
    ]


async def invite_member(
    db: AsyncSession,
    inviter: User,
    kb_id: uuid.UUID,
    username: str,
    role: str,
    expires_at: datetime | None,
) -> KbInvitation:
    kb = await _get_kb(db, kb_id)
    if not inviter.is_superuser:
        operator_role = await _require_effective_member(db, kb_id, inviter)
        if operator_role not in MANAGE_ROLES:
            raise PermissionException(message="需要管理员或所有者权限")
    target = (
        await db.execute(
            select(User).where(
                User.username == username,
                User.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if target is None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_USER_NOT_FOUND, message=f"用户不存在：{username}"
        )
    if target.id == inviter.id:
        raise ValidationException(message="不能邀请自己（你已是成员/所有者）")
    existing = (
        await db.execute(
            select(KbMember).where(
                KbMember.kb_id == kb_id,
                KbMember.user_id == target.id,
                KbMember.status != MEMBER_STATUS_REMOVED,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ValidationException(
            message=f"用户 {username} 已是该知识库成员或待接受邀请"
        )
    expire = expires_at or (_now() + timedelta(hours=settings.INVITATION_EXPIRE_HOURS))
    member = KbMember(
        kb_id=kb_id,
        user_id=target.id,
        role=role,
        status=MEMBER_STATUS_INVITED,
        invited_by=inviter.id,
        expires_at=expire,
    )
    db.add(member)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise ValidationException(message=f"用户 {username} 已在该知识库中")
    invitation = KbInvitation(
        token=secrets.token_urlsafe(32),
        kb_id=kb_id,
        inviter_id=inviter.id,
        invitee_id=target.id,
        member_id=member.id,
        role=role,
        status=INVITATION_STATUS_PENDING,
        expires_at=expire,
    )
    db.add(invitation)
    await db.commit()
    await db.refresh(invitation)
    logger.info(
        "知识库成员邀请已发送",
        kb_id=str(kb_id),
        invitee=str(target.id),
        inviter=str(inviter.id),
    )
    return invitation


async def my_invitations(db: AsyncSession, user: User) -> list[dict]:
    now = _now()
    rows = (
        await db.execute(
            select(KbInvitation, KnowledgeBase.name, User.username)
            .join(KnowledgeBase, KnowledgeBase.id == KbInvitation.kb_id)
            .join(User, User.id == KbInvitation.inviter_id)
            .where(
                KbInvitation.invitee_id == user.id,
                KbInvitation.status == INVITATION_STATUS_PENDING,
                or_(KbInvitation.expires_at.is_(None), KbInvitation.expires_at > now),
            )
            .order_by(KbInvitation.created_at.desc())
        )
    ).all()
    return [
        {
            "id": str(inv.id),
            "token": inv.token,
            "kb_id": str(inv.kb_id),
            "kb_name": kb_name,
            "inviter_id": str(inv.inviter_id),
            "inviter_username": inviter_username,
            "invitee_id": str(inv.invitee_id),
            "role": inv.role,
            "status": inv.status,
            "expires_at": inv.expires_at.isoformat() if inv.expires_at else None,
            "created_at": inv.created_at.isoformat() if inv.created_at else None,
        }
        for inv, kb_name, inviter_username in rows
    ]


async def accept_invitation(
    db: AsyncSession, user: User, token: str
) -> dict:
    now = _now()
    first = (
        await db.execute(
            select(KbInvitation).where(KbInvitation.token == token)
        )
    ).scalar_one_or_none()
    if first is None:
        raise ValidationException(message="邀请不存在")
    # 行级咨询锁：并发接受同一邀请时串行化，第二个请求重读后判定已处理
    lock_key = first.id.int & 0x7FFFFFFFFFFFFFFF
    await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})
    invitation = (
        await db.execute(
            select(KbInvitation).where(KbInvitation.token == token)
        )
    ).scalar_one_or_none()
    if invitation is None or invitation.status != INVITATION_STATUS_PENDING:
        raise ValidationException(message="邀请不存在或已被处理")
    if invitation.invitee_id != user.id:
        raise PermissionException(message="该邀请不属于当前用户")
    if invitation.expires_at is not None and invitation.expires_at < now:
        invitation.status = INVITATION_STATUS_REVOKED
        invitation.revoked_at = now
        member = await db.get(KbMember, invitation.member_id) if invitation.member_id else None
        if member is not None:
            member.status = MEMBER_STATUS_REMOVED
        await db.commit()
        raise ValidationException(message="邀请已过期")
    member = await db.get(KbMember, invitation.member_id) if invitation.member_id else None
    if member is None or member.status != MEMBER_STATUS_INVITED:
        raise ValidationException(message="邀请关联的成员记录无效")
    member.status = MEMBER_STATUS_ACTIVE
    member.expires_at = None
    invitation.status = INVITATION_STATUS_ACCEPTED
    invitation.accepted_at = now
    kb = await db.get(KnowledgeBase, invitation.kb_id)
    await db.commit()
    logger.info("知识库邀请已接受", kb_id=str(invitation.kb_id), user=str(user.id))
    return {
        "kb_id": str(invitation.kb_id),
        "kb_name": kb.name if kb else "",
        "role": invitation.role,
        "status": INVITATION_STATUS_ACCEPTED,
    }


async def revoke_invitation(
    db: AsyncSession, operator: User, kb_id: uuid.UUID, invitation_id: uuid.UUID
) -> None:
    kb = await _get_kb(db, kb_id)
    if not operator.is_superuser:
        role = await _require_effective_member(db, kb_id, operator)
        if role not in MANAGE_ROLES:
            raise PermissionException(message="需要管理员或所有者权限")
    invitation = (
        await db.execute(
            select(KbInvitation).where(
                KbInvitation.id == invitation_id,
                KbInvitation.kb_id == kb_id,
            )
        )
    ).scalar_one_or_none()
    if invitation is None or invitation.status != INVITATION_STATUS_PENDING:
        raise ValidationException(message="邀请不存在或已处理")
    invitation.status = INVITATION_STATUS_REVOKED
    invitation.revoked_at = _now()
    member = await db.get(KbMember, invitation.member_id) if invitation.member_id else None
    if member is not None:
        member.status = MEMBER_STATUS_REMOVED
    await db.commit()


async def update_member_role(
    db: AsyncSession,
    operator: User,
    kb_id: uuid.UUID,
    target_user_id: uuid.UUID,
    role: str,
) -> None:
    kb = await _get_kb(db, kb_id)
    if not operator.is_superuser:
        operator_role = await _require_effective_member(db, kb_id, operator)
        if operator_role not in MANAGE_ROLES:
            raise PermissionException(message="需要管理员或所有者权限")
    target = await _get_member(db, kb_id, target_user_id)
    if target is None:
        raise BusinessException(message="目标用户不是有效成员")
    if target.role == ROLE_OWNER or role == ROLE_OWNER:
        raise ValidationException(message="所有者角色不可直接修改，请使用所有权转移")
    target.role = role
    await db.commit()


async def remove_member(
    db: AsyncSession, operator: User, kb_id: uuid.UUID, target_user_id: uuid.UUID
) -> None:
    kb = await _get_kb(db, kb_id)
    if not operator.is_superuser:
        operator_role = await _require_effective_member(db, kb_id, operator)
        if operator_role not in MANAGE_ROLES and operator.id != target_user_id:
            raise PermissionException(message="需要管理员或所有者权限")
    target = await _get_member(db, kb_id, target_user_id)
    if target is None:
        raise BusinessException(message="目标用户不是有效成员")
    if target.role == ROLE_OWNER:
        raise ValidationException(message="不能移除所有者")
    target.status = MEMBER_STATUS_REMOVED
    pending = (
        await db.execute(
            select(KbInvitation).where(
                KbInvitation.kb_id == kb_id,
                KbInvitation.invitee_id == target_user_id,
                KbInvitation.status == INVITATION_STATUS_PENDING,
            )
        )
    ).scalars().all()
    for inv in pending:
        inv.status = INVITATION_STATUS_REVOKED
        inv.revoked_at = _now()
    await db.commit()


async def transfer_ownership(
    db: AsyncSession,
    operator: User,
    kb_id: uuid.UUID,
    target_user_id: uuid.UUID,
) -> None:
    kb = await _get_kb(db, kb_id)
    if not operator.is_superuser:
        operator_role = await _require_effective_member(db, kb_id, operator)
        if operator_role != ROLE_OWNER:
            raise PermissionException(message="仅所有者可转移知识库")
    target = await _get_member(db, kb_id, target_user_id)
    if target is None:
        raise BusinessException(message="目标用户不是有效成员")
    old_owner = await _get_member(db, kb_id, kb.owner_id)
    if old_owner is not None:
        old_owner.role = "admin"
    target.role = ROLE_OWNER
    kb.owner_id = target_user_id
    await db.commit()
    logger.info("知识库所有权已转移", kb_id=str(kb_id), new_owner=str(target_user_id))


async def get_kb_overview(db: AsyncSession, user: User, kb_id: uuid.UUID) -> dict:
    """KB 概览：基础信息 + 成员统计（文档/任务在对应阶段迁移后启用）。"""
    data = await get_kb(db, user, kb_id)
    members = await list_members(db, user, kb_id)
    data["stats"] = {
        "members_active": sum(1 for m in members if m["status"] == "active"),
        "pending_invites": sum(1 for m in members if m["status"] == "invited"),
        "documents": 0,
        "tasks": 0,
    }
    return data


def _mask_token(token: str) -> str:
    return (token[:6] + "••••••") if len(token) > 6 else "••••••"


async def _require_kb_manage(db: AsyncSession, user: User, kb_id: uuid.UUID) -> None:
    if user.is_superuser:
        return
    role = await effective_kb_role(db, user.id, kb_id)
    if role is None:
        raise PermissionException(message="您不是该知识库成员")
    if role not in MANAGE_ROLES:
        raise PermissionException(message="需要管理员或所有者权限")


async def get_kb_external(db: AsyncSession, user: User, kb_id: uuid.UUID) -> dict:
    await _require_kb_manage(db, user, kb_id)
    kb = await _get_kb(db, kb_id)
    ext = (kb.config or {}).get("external") or {}
    return {
        "enabled": bool(ext.get("enabled")),
        "token_prefix": _mask_token(str(ext.get("token") or "")),
        "updated_at": ext.get("updated_at"),
    }


async def update_kb_external(
    db: AsyncSession,
    user: User,
    kb_id: uuid.UUID,
    enabled: bool,
    regenerate: bool,
) -> dict:
    await _require_kb_manage(db, user, kb_id)
    kb = await _get_kb(db, kb_id)
    config = dict(kb.config or {})
    ext = dict(config.get("external") or {})
    token = str(ext.get("token") or "")
    token_full: str | None = None
    if regenerate or not token:
        token = secrets.token_urlsafe(24)
        token_full = token
    ext["enabled"] = enabled
    ext["token"] = token
    ext["updated_at"] = _now().isoformat()
    config["external"] = ext
    kb.config = config
    await db.commit()
    return {
        "enabled": enabled,
        "token_prefix": _mask_token(token),
        "token": token_full,
        "updated_at": ext["updated_at"],
    }
