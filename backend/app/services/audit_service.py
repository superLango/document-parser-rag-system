"""审计日志服务。"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.models.audit_log import AuditLog

logger = get_logger(__name__)


async def write_audit_log(
    *,
    user_id: uuid.UUID | None,
    username: str | None,
    kb_id: uuid.UUID | None,
    action: str,
    resource_type: str | None,
    resource_id: str | None,
    method: str | None,
    path: str | None,
    status_code: int | None,
    ip: str | None,
    user_agent: str | None,
    details: dict | None,
    trace_id: str | None,
) -> None:
    try:
        async with AsyncSessionLocal() as db:
            log = AuditLog(
                user_id=user_id,
                username=username,
                kb_id=kb_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                method=method,
                path=path,
                status_code=status_code,
                ip=ip,
                user_agent=user_agent,
                details=details,
                trace_id=trace_id,
            )
            db.add(log)
            await db.commit()
        _log_anomaly(action, status_code, details, username, ip)
    except Exception as exc:
        logger.warning("审计日志写入失败", action=action, error=str(exc))


def _log_anomaly(
    action: str,
    status_code: int | None,
    details: dict | None,
    username: str | None,
    ip: str | None,
) -> None:
    """异常操作检测：命中规则时记录安全告警日志。

    原系统会向超管发送站内通知；通知中心尚未迁移，此阶段以结构化告警日志替代，
    后续通知中心迁移时接入。
    """
    if status_code is None:
        return
    error_msg = (details or {}).get("error", "") if details else ""
    if action == "auth.login" and status_code == 400 and "锁定" in error_msg:
        logger.warning(
            "audit_alert",
            alert="账户锁定",
            title=f"账户安全告警：{username or '未知用户'} 账户被锁定",
            ip=ip,
        )
    elif status_code == 403:
        logger.warning(
            "audit_alert",
            alert="权限拒绝",
            title=f"权限拒绝告警：{username or '匿名'} 访问被拒（{action}）",
            ip=ip,
        )
    elif status_code >= 500:
        logger.warning(
            "audit_alert",
            alert="服务器错误",
            title=f"服务器错误告警：{action} 返回 {status_code}",
            ip=ip,
            error=error_msg[:200],
        )
    elif "batch.delete" in action and status_code == 200:
        logger.info(
            "audit_alert",
            alert="批量删除",
            title=f"批量删除操作：{username or '匿名'} 执行了 {action}",
            ip=ip,
        )


async def list_audit_logs(
    db: AsyncSession,
    page: int,
    page_size: int,
    action: str | None = None,
    user_id: str | None = None,
    kb_id: str | None = None,
    resource_type: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> tuple[list[AuditLog], int]:
    base = select(AuditLog)
    count_base = select(func.count()).select_from(AuditLog)

    if action:
        base = base.where(AuditLog.action == action)
        count_base = count_base.where(AuditLog.action == action)
    if user_id:
        base = base.where(AuditLog.user_id == uuid.UUID(user_id))
        count_base = count_base.where(AuditLog.user_id == uuid.UUID(user_id))
    if kb_id:
        base = base.where(AuditLog.kb_id == uuid.UUID(kb_id))
        count_base = count_base.where(AuditLog.kb_id == uuid.UUID(kb_id))
    if resource_type:
        base = base.where(AuditLog.resource_type == resource_type)
        count_base = count_base.where(AuditLog.resource_type == resource_type)
    if start_date:
        start_dt = datetime.fromisoformat(start_date)
        base = base.where(AuditLog.created_at >= start_dt)
        count_base = count_base.where(AuditLog.created_at >= start_dt)
    if end_date:
        end_dt = datetime.fromisoformat(end_date) + timedelta(days=1)
        base = base.where(AuditLog.created_at < end_dt)
        count_base = count_base.where(AuditLog.created_at < end_dt)

    total = (await db.execute(count_base)).scalar_one()
    logs = (
        await db.execute(
            base.order_by(AuditLog.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()
    return list(logs), total


async def list_actions(db: AsyncSession) -> list[str]:
    rows = await db.execute(select(distinct(AuditLog.action)).order_by(AuditLog.action))
    return [r[0] for r in rows.all() if r[0]]


async def audit_stats(db: AsyncSession, days: int) -> dict:
    threshold = datetime.now(timezone.utc) - timedelta(days=days)

    action_rows = await db.execute(
        select(AuditLog.action, func.count(AuditLog.id))
        .where(AuditLog.created_at >= threshold)
        .group_by(AuditLog.action)
        .order_by(func.count(AuditLog.id).desc())
    )
    by_action = {r[0]: r[1] for r in action_rows.all() if r[0]}

    day_rows = await db.execute(
        select(
            func.date_trunc("day", AuditLog.created_at).label("day"),
            func.count(AuditLog.id),
        )
        .where(AuditLog.created_at >= threshold)
        .group_by("day")
        .order_by("day")
    )
    by_day = [
        {"date": r[0].isoformat() if r[0] else "", "count": r[1]}
        for r in day_rows.all()
    ]

    user_rows = await db.execute(
        select(AuditLog.username, func.count(AuditLog.id))
        .where(AuditLog.created_at >= threshold)
        .group_by(AuditLog.username)
        .order_by(func.count(AuditLog.id).desc())
        .limit(10)
    )
    by_user = {r[0] or "未知": r[1] for r in user_rows.all()}

    resource_rows = await db.execute(
        select(AuditLog.resource_type, func.count(AuditLog.id))
        .where(AuditLog.created_at >= threshold)
        .group_by(AuditLog.resource_type)
        .order_by(func.count(AuditLog.id).desc())
    )
    by_resource_type = {(r[0] or "未知"): r[1] for r in resource_rows.all()}

    return {
        "days": days,
        "total": sum(by_action.values()),
        "by_action": by_action,
        "by_day": by_day,
        "by_user": by_user,
        "by_resource_type": by_resource_type,
    }
