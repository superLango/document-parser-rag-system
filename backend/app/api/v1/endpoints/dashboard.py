"""仪表盘统计端点模块（阶段 2.1 增强）。

提供全局与 KB 内统计数据，含趋势与分布：
- GET /dashboard/stats           全局计数汇总
- GET /dashboard/trends           30 天文档/任务趋势
- GET /dashboard/distribution     文档类型/任务状态/任务类型分布
- GET /dashboard/kbs/{kb_id}/stats  KB 内计数汇总

所有聚合查询委托 dashboard_service，避免 N+1。
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_kb_context, require_superuser
from app.core.database import get_db
from app.core.response import success
from app.models.user import User
from app.services.infra.dashboard_service import (
    get_distribution,
    get_global_stats,
    get_kb_stats,
    get_trends,
)

router = APIRouter(prefix="/dashboard", tags=["仪表盘"])


@router.get("/stats")
async def stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
) -> dict:
    """全局统计汇总（跨所有 KB，超管视角）。

    全局聚合查询不按 kb_id 过滤，限制为超管访问以避免越权。
    """
    return success(data=await get_global_stats(db))


@router.get("/trends")
async def trends(
    days: int = Query(30, ge=1, le=365, description="趋势天数"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
) -> dict:
    """最近 N 天文档上传与任务完成趋势（超管视角）。

    全局聚合查询不按 kb_id 过滤，限制为超管访问以避免越权。
    """
    return success(data=await get_trends(db, days))


@router.get("/distribution")
async def distribution(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
) -> dict:
    """文档类型 / 任务状态 / 任务类型分布（超管视角）。

    全局聚合查询不按 kb_id 过滤，限制为超管访问以避免越权。
    """
    return success(data=await get_distribution(db))


@router.get("/kbs/{kb_id}/stats")
async def kb_stats(
    kb_ctx=Depends(get_kb_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """KB 内统计汇总（viewer+，显式按 kb_id 过滤）。

    通过 get_kb_context 校验成员身份并激活 RLS，避免越权访问其他 KB 统计。
    """
    return success(data=await get_kb_stats(db, kb_ctx.kb_id))
