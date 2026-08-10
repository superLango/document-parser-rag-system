"""审计日志端点（超管）。"""

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_pagination_params, require_permission
from app.core.database import get_db
from app.core.exceptions import BusinessException, ErrorCode
from app.core.response import paginated, success
from app.schemas.audit_log import AuditLogOut
from app.services.audit_service import audit_stats, list_actions, list_audit_logs

router = APIRouter(prefix="/audit-logs", tags=["审计日志"])


@router.get("")
async def list_logs(
    pagination: dict = Depends(get_pagination_params),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("audit.view")),
    action: str | None = Query(None),
    user_id: str | None = Query(None),
    kb_id: str | None = Query(None),
    resource_type: str | None = Query(None),
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
) -> dict:
    try:
        logs, total = await list_audit_logs(
            db,
            pagination["page"],
            pagination["page_size"],
            action=action,
            user_id=user_id,
            kb_id=kb_id,
            resource_type=resource_type,
            start_date=start_date,
            end_date=end_date,
        )
    except ValueError:
        raise BusinessException(
            code=ErrorCode.VALIDATION_ERROR,
            message="日期格式应为 YYYY-MM-DD，ID 应为合法 UUID",
        )
    items = [AuditLogOut.model_validate(log).model_dump() for log in logs]
    return paginated(items, total, pagination["page"], pagination["page_size"])


@router.get("/export")
async def export_logs(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("audit.export")),
    action: str | None = Query(None),
    user_id: str | None = Query(None),
    kb_id: str | None = Query(None),
    resource_type: str | None = Query(None),
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
) -> StreamingResponse:
    import csv
    import io
    from datetime import datetime, timezone

    logs, _ = await list_audit_logs(
        db,
        1,
        100000,
        action=action,
        user_id=user_id,
        kb_id=kb_id,
        resource_type=resource_type,
        start_date=start_date,
        end_date=end_date,
    )
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "created_at", "action", "username", "resource_type", "resource_id",
        "method", "path", "status_code", "ip", "details",
    ])
    for log in logs:
        writer.writerow([
            log.created_at.isoformat() if log.created_at else "",
            log.action,
            log.username or "",
            log.resource_type or "",
            log.resource_id or "",
            log.method or "",
            log.path or "",
            log.status_code or "",
            log.ip or "",
            str(log.details or ""),
        ])
    filename = f"audit_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/actions")
async def list_actions_endpoint(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("audit.view")),
) -> dict:
    return success(data=await list_actions(db))


@router.get("/stats")
async def stats_endpoint(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("audit.view")),
    days: int = Query(7, ge=1, le=90),
) -> dict:
    return success(data=await audit_stats(db, days))
