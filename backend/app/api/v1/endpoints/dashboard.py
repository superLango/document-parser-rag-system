"""工作台仪表盘端点。"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, require_permission
from app.core.database import get_db
from app.core.response import success
from app.models.user import User
from app.services.dashboard_service import overview, stats, trends

router = APIRouter(prefix="/dashboard", tags=["工作台"])


@router.get("/overview")
async def overview_endpoint(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """工作台概览（登录后主页面数据源）。"""
    return success(data=await overview(db, current_user))


@router.get("/stats")
async def stats_endpoint(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("system.stats")),
) -> dict:
    return success(data=await stats(db))


@router.get("/trends")
async def trends_endpoint(
    days: int = Query(7, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("system.stats")),
) -> dict:
    return success(data=await trends(db, days))
