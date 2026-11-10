"""Workspace / knowledge-base access control helpers."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    KnowledgeBase,
    KnowledgeBaseMember,
    User,
    Workspace,
    WorkspaceMember,
    new_id,
)

KB_ROLE_RANK = {"viewer": 1, "editor": 2, "owner": 3}
WORKSPACE_ROLE_RANK = {"member": 1, "admin": 2, "owner": 3}


@dataclass
class Principal:
    actor_id: str
    actor_type: str
    scopes: set[str]
    user: User | None = None
    workspace_id: str | None = None
    kb_ids: set[str] | None = None
    anonymous: bool = False


def workspace_role(
    db: Session, user_id: str, workspace_id: str
) -> str | None:
    member = db.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user_id,
        )
    )
    if member is None:
        return None
    return member.role if member.role in WORKSPACE_ROLE_RANK else "member"


def require_workspace_role(
    db: Session, principal: Principal, workspace_id: str, minimum: str = "member"
) -> str:
    if principal.anonymous:
        # 免登录模式：固定访客对所有工作空间拥有 owner 权限。
        return "owner"
    role = workspace_role(db, principal.actor_id, workspace_id)
    if role is None:
        # 404 avoids leaking workspace existence to non-members.
        raise HTTPException(status_code=404, detail="workspace not found")
    if WORKSPACE_ROLE_RANK[role] < WORKSPACE_ROLE_RANK[minimum]:
        raise HTTPException(status_code=403, detail="insufficient workspace role")
    return role


def kb_member_role(db: Session, user_id: str, kb_id: str) -> str | None:
    member = db.scalar(
        select(KnowledgeBaseMember).where(
            KnowledgeBaseMember.kb_id == kb_id,
            KnowledgeBaseMember.user_id == user_id,
        )
    )
    if member is None:
        return None
    return member.role if member.role in KB_ROLE_RANK else "viewer"


def _user_kb_role(db: Session, user_id: str, kb: KnowledgeBase) -> str | None:
    ws_role = workspace_role(db, user_id, kb.workspace_id)
    if ws_role in {"owner", "admin"}:
        return "owner"
    if ws_role is None:
        return None
    return kb_member_role(db, user_id, kb.id)


def kb_role(db: Session, principal: Principal, kb: KnowledgeBase) -> str | None:
    """Effective role for this principal on a KB (None means no access)."""

    if principal.anonymous:
        # 嵌入式免登录模式：固定访客可访问所有知识库，避免外部系统上传的
        # 文档在无登录页面里因知识库成员校验被拒绝。
        return "owner"
    if principal.actor_type == "api_key":
        if principal.workspace_id != kb.workspace_id:
            return None
        if principal.kb_ids is not None and kb.id not in principal.kb_ids:
            return None
        base = _user_kb_role(db, principal.actor_id, kb)
        if base is None:
            return None
        cap = "editor" if "documents:write" in principal.scopes else "viewer"
        if "documents:read" not in principal.scopes and "tasks:read" not in principal.scopes:
            if cap == "viewer":
                return None
        return base if KB_ROLE_RANK[base] < KB_ROLE_RANK[cap] else cap
    return _user_kb_role(db, principal.actor_id, kb)


def require_kb_role(
    db: Session, principal: Principal, kb: KnowledgeBase, minimum: str = "viewer"
) -> str:
    role = kb_role(db, principal, kb)
    if role is None:
        raise HTTPException(status_code=403, detail="not allowed for this knowledge base")
    if KB_ROLE_RANK[role] < KB_ROLE_RANK[minimum]:
        raise HTTPException(
            status_code=403, detail=f"requires knowledge base role: {minimum}"
        )
    return role


def default_workspace(db: Session, user: User) -> Workspace:
    """Return the user's first owner/admin workspace, creating one if needed."""

    rows = (
        db.execute(
            select(Workspace, WorkspaceMember.role)
            .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
            .where(
                WorkspaceMember.user_id == user.id,
                Workspace.deleted_at.is_(None),
                WorkspaceMember.role.in_(["owner", "admin"]),
            )
            .order_by(Workspace.created_at.asc())
        )
        .all()
    )
    if rows:
        return rows[0][0]

    workspace = Workspace(
        id=new_id(),
        name=f"个人工作空间 {user.display_name or user.username}"[:128],
        description="",
        owner_id=user.id,
    )
    db.add(workspace)
    db.flush()
    db.add(
        WorkspaceMember(
            id=new_id(),
            workspace_id=workspace.id,
            user_id=user.id,
            role="owner",
        )
    )
    return workspace


def kb_ids_from_text(text: str | None) -> set[str] | None:
    if not text:
        return None
    ids = {part.strip() for part in text.split(",") if part.strip()}
    return ids or None


def kb_ids_to_text(ids: list[str] | set[str] | None) -> str:
    if not ids:
        return ""
    return ",".join(sorted({str(item).strip() for item in ids if str(item).strip()}))


def accessible_kb_ids(db: Session, principal: Principal) -> list[str]:
    """Knowledge-base ids this principal can read (viewer+)."""

    kbs = list(
        db.scalars(
            select(KnowledgeBase).where(KnowledgeBase.deleted_at.is_(None))
        ).all()
    )
    if principal.anonymous:
        # 免登录模式：不按成员过滤，访客可读写全部知识库。
        return [kb.id for kb in kbs]
    if principal.actor_type == "api_key":
        if not principal.workspace_id:
            return []
        if workspace_role(db, principal.actor_id, principal.workspace_id) is None:
            return []
        allowed = set(principal.kb_ids or [])
        return [
            kb.id
            for kb in kbs
            if kb.workspace_id == principal.workspace_id
            and (not allowed or kb.id in allowed)
            and _user_kb_role(db, principal.actor_id, kb) is not None
        ]

    admin_workspaces = {
        row.workspace_id
        for row in db.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.user_id == principal.actor_id,
                WorkspaceMember.role.in_(["owner", "admin"]),
            )
        ).scalars()
    }
    member_kbs = {
        row.kb_id
        for row in db.execute(
            select(KnowledgeBaseMember).where(
                KnowledgeBaseMember.user_id == principal.actor_id
            )
        ).scalars()
    }
    return [
        kb.id
        for kb in kbs
        if kb.workspace_id in admin_workspaces or kb.id in member_kbs
    ]
