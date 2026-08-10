"""工作台仪表盘服务。"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.audit_log import AuditLog
from app.models.knowledge_base import KnowledgeBase
from app.models.user import User


def _serialize_log(log: AuditLog) -> dict:
    return {
        "id": str(log.id),
        "user_id": str(log.user_id) if log.user_id else None,
        "username": log.username,
        "action": log.action,
        "resource_type": log.resource_type,
        "resource_id": log.resource_id,
        "method": log.method,
        "path": log.path,
        "status_code": log.status_code,
        "ip": log.ip,
        "trace_id": log.trace_id,
        "created_at": log.created_at.isoformat() if log.created_at else "",
    }


async def _login_trend(db: AsyncSession, days: int, user_id=None) -> list[dict]:
    threshold = datetime.now(timezone.utc) - timedelta(days=days)
    stmt = (
        select(
            func.date_trunc("day", AuditLog.created_at).label("day"),
            func.count(AuditLog.id),
        )
        .where(
            AuditLog.action == "auth.login",
            AuditLog.created_at >= threshold,
        )
        .group_by("day")
        .order_by("day")
    )
    if user_id is not None:
        stmt = stmt.where(AuditLog.user_id == user_id)
    rows = (await db.execute(stmt)).all()
    return [{"date": r[0].isoformat() if r[0] else "", "count": r[1]} for r in rows]


async def overview(db: AsyncSession, user: User) -> dict:
    """工作台概览：项目信息 + 用户统计 + 近期审计（按权限分级）。"""
    total_users = (
        await db.execute(
            select(func.count()).select_from(User).where(User.deleted_at.is_(None))
        )
    ).scalar_one()
    active_users = (
        await db.execute(
            select(func.count())
            .select_from(User)
            .where(User.deleted_at.is_(None), User.is_active.is_(True))
        )
    ).scalar_one()
    superusers = (
        await db.execute(
            select(func.count())
            .select_from(User)
            .where(User.deleted_at.is_(None), User.is_superuser.is_(True))
        )
    ).scalar_one()
    kbs_count = (
        await db.execute(
            select(func.count())
            .select_from(KnowledgeBase)
            .where(KnowledgeBase.deleted_at.is_(None))
        )
    ).scalar_one()

    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    login_base = select(func.count(AuditLog.id)).where(
        AuditLog.action == "auth.login", AuditLog.created_at >= today_start
    )
    audit_base = select(func.count(AuditLog.id)).where(
        AuditLog.created_at >= today_start
    )
    if not user.is_superuser:
        login_base = login_base.where(AuditLog.user_id == user.id)
        audit_base = audit_base.where(AuditLog.user_id == user.id)
    today_logins = (await db.execute(login_base)).scalar_one()
    today_actions = (await db.execute(audit_base)).scalar_one()

    recent_stmt = (
        select(AuditLog)
        .order_by(AuditLog.created_at.desc())
        .limit(8)
    )
    if not user.is_superuser:
        recent_stmt = recent_stmt.where(AuditLog.user_id == user.id)
    recent = (await db.execute(recent_stmt)).scalars().all()

    return {
        "project": {
            "app_name": settings.APP_NAME,
            "version": settings.VERSION,
            "env": settings.APP_ENV,
            "debug": settings.DEBUG,
            "database": settings.POSTGRES_DB,
        },
        "user": {
            "id": str(user.id),
            "username": user.username,
            "full_name": user.full_name,
            "email": user.email,
            "is_superuser": user.is_superuser,
            "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
            "created_at": user.created_at.isoformat() if user.created_at else None,
        },
        "stats": {
            "users_total": total_users,
            "users_active": active_users,
            "users_superuser": superusers,
            "kbs_count": kbs_count,
            "today_logins": today_logins,
            "today_actions": today_actions,
        },
        "login_trend": await _login_trend(
            db, 7, user_id=None if user.is_superuser else user.id
        ),
        "recent_audit": [_serialize_log(log) for log in recent],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


async def stats(db: AsyncSession) -> dict:
    """超管全局统计。"""
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    total_users = (
        await db.execute(
            select(func.count()).select_from(User).where(User.deleted_at.is_(None))
        )
    ).scalar_one()
    active_users = (
        await db.execute(
            select(func.count())
            .select_from(User)
            .where(User.deleted_at.is_(None), User.is_active.is_(True))
        )
    ).scalar_one()
    superusers = (
        await db.execute(
            select(func.count())
            .select_from(User)
            .where(User.deleted_at.is_(None), User.is_superuser.is_(True))
        )
    ).scalar_one()
    audit_total = (
        await db.execute(select(func.count()).select_from(AuditLog))
    ).scalar_one()
    audit_today = (
        await db.execute(
            select(func.count()).select_from(AuditLog).where(
                AuditLog.created_at >= today_start
            )
        )
    ).scalar_one()
    login_today = (
        await db.execute(
            select(func.count())
            .select_from(AuditLog)
            .where(
                AuditLog.action == "auth.login",
                AuditLog.created_at >= today_start,
            )
        )
    ).scalar_one()
    kbs_count = (
        await db.execute(
            select(func.count())
            .select_from(KnowledgeBase)
            .where(KnowledgeBase.deleted_at.is_(None))
        )
    ).scalar_one()
    return {
        "users_total": total_users,
        "users_active": active_users,
        "users_superuser": superusers,
        "audit_total": audit_total,
        "audit_today": audit_today,
        "login_today": login_today,
        "kbs_count": kbs_count,
    }


async def trends(db: AsyncSession, days: int) -> dict:
    return {
        "days": days,
        "login": await _login_trend(db, days),
    }
