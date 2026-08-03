"""审计日志查看端点（阶段 1.1 + 阶段 3 审计深化）。

提供超管审计日志查询接口（前缀 ``/audit-logs``）：

- GET /audit-logs         分页查询审计日志（超管，支持 action/user/kb/日期过滤）
- GET /audit-logs/actions  获取所有已记录的 action 列表（用于过滤下拉）
- GET /audit-logs/stats    审计统计（按 action/日期聚合，供可视化）

审计日志为系统级数据，不走 RLS，仅超管可访问。
"""

from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_pagination_params, require_superuser
from app.core.database import get_db
from app.core.exceptions import BusinessException, ErrorCode
from app.core.response import paginated, success
from app.models.audit_log import AuditLog

router = APIRouter(prefix="/audit-logs", tags=["审计日志"])


@router.get("")
async def list_audit_logs(
    pagination: dict = Depends(get_pagination_params),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_superuser),
    action: str | None = Query(None, description="按动作过滤"),
    user_id: str | None = Query(None, description="按操作者 ID 过滤"),
    kb_id: str | None = Query(None, description="按知识库 ID 过滤"),
    resource_type: str | None = Query(None, description="按资源类型过滤"),
    start_date: str | None = Query(None, description="起始日期 YYYY-MM-DD"),
    end_date: str | None = Query(None, description="截止日期 YYYY-MM-DD"),
) -> dict:
    """分页查询审计日志（超管）。

    支持按 action / user_id / kb_id / resource_type / 日期范围过滤。
    按时间倒序返回。
    """
    page = pagination["page"]
    page_size = pagination["page_size"]

    base = select(AuditLog)
    count_base = select(func.count()).select_from(AuditLog)

    if action:
        base = base.where(AuditLog.action == action)
        count_base = count_base.where(AuditLog.action == action)
    if user_id:
        from uuid import UUID

        base = base.where(AuditLog.user_id == UUID(user_id))
        count_base = count_base.where(AuditLog.user_id == UUID(user_id))
    if kb_id:
        from uuid import UUID

        base = base.where(AuditLog.kb_id == UUID(kb_id))
        count_base = count_base.where(AuditLog.kb_id == UUID(kb_id))
    if resource_type:
        base = base.where(AuditLog.resource_type == resource_type)
        count_base = count_base.where(AuditLog.resource_type == resource_type)
    if start_date:
        try:
            start_dt = datetime.fromisoformat(start_date)
            base = base.where(AuditLog.created_at >= start_dt)
            count_base = count_base.where(AuditLog.created_at >= start_dt)
        except ValueError:
            raise BusinessException(
                code=ErrorCode.VALIDATION_ERROR,
                message="start_date 格式应为 YYYY-MM-DD",
            )
    if end_date:
        try:
            end_dt = datetime.fromisoformat(end_date) + timedelta(days=1)
            base = base.where(AuditLog.created_at < end_dt)
            count_base = count_base.where(AuditLog.created_at < end_dt)
        except ValueError:
            raise BusinessException(
                code=ErrorCode.VALIDATION_ERROR,
                message="end_date 格式应为 YYYY-MM-DD",
            )

    total = (await db.execute(count_base)).scalar_one()
    logs = (
        await db.execute(
            base.order_by(AuditLog.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()

    items = [
        {
            "id": str(log.id),
            "user_id": str(log.user_id) if log.user_id else None,
            "username": log.username,
            "kb_id": str(log.kb_id) if log.kb_id else None,
            "action": log.action,
            "resource_type": log.resource_type,
            "resource_id": log.resource_id,
            "method": log.method,
            "path": log.path,
            "status_code": log.status_code,
            "ip": log.ip,
            "user_agent": log.user_agent,
            "details": log.details,
            "trace_id": log.trace_id,
            "created_at": log.created_at.isoformat() if log.created_at else "",
        }
        for log in logs
    ]
    return paginated(items, total, page, page_size)


@router.get("/actions")
async def list_actions(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_superuser),
) -> dict:
    """获取所有已记录的 action 列表（用于过滤下拉）。"""
    rows = await db.execute(
        select(distinct(AuditLog.action)).order_by(AuditLog.action)
    )
    actions = [r[0] for r in rows.all() if r[0]]
    return success(data=actions)


@router.get("/stats")
async def audit_stats(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_superuser),
    days: int = Query(7, ge=1, le=90, description="统计最近 N 天的数据"),
) -> dict:
    """审计统计（超管，供可视化图表）。

    返回最近 N 天的：
    - by_action：按 action 分组的操作数
    - by_day：按日期分组的操作数（用于趋势图）
    - by_user：按操作者分组的 Top 10
    - by_resource_type：按资源类型分组
    - total：总数
    """
    threshold = datetime.utcnow() - timedelta(days=days)

    # 按 action 分组
    action_rows = await db.execute(
        select(AuditLog.action, func.count(AuditLog.id))
        .where(AuditLog.created_at >= threshold)
        .group_by(AuditLog.action)
        .order_by(func.count(AuditLog.id).desc())
    )
    by_action = {r[0]: r[1] for r in action_rows.all() if r[0]}

    # 按日期分组（趋势图）
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

    # 按操作者分组 Top 10
    user_rows = await db.execute(
        select(AuditLog.username, func.count(AuditLog.id))
        .where(AuditLog.created_at >= threshold)
        .group_by(AuditLog.username)
        .order_by(func.count(AuditLog.id).desc())
        .limit(10)
    )
    by_user = {r[0] or "未知": r[1] for r in user_rows.all()}

    # 按资源类型分组
    resource_rows = await db.execute(
        select(AuditLog.resource_type, func.count(AuditLog.id))
        .where(AuditLog.created_at >= threshold)
        .group_by(AuditLog.resource_type)
        .order_by(func.count(AuditLog.id).desc())
    )
    by_resource_type = {(r[0] or "未知"): r[1] for r in resource_rows.all()}

    total = sum(by_action.values())

    return success(data={
        "days": days,
        "total": total,
        "by_action": by_action,
        "by_day": by_day,
        "by_user": by_user,
        "by_resource_type": by_resource_type,
    })
