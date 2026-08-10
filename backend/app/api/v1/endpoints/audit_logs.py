"""审计日志端点（超管）。"""

from fastapi import APIRouter, Depends, Query
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
