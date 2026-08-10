"""系统端点：健康检查与系统信息。"""

import asyncio
import platform
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user
from app.core.config import settings
from app.core.database import get_db
from app.core.response import success
from app.models.user import User

router = APIRouter(prefix="/system", tags=["系统管理"])


async def _check_postgres(db: AsyncSession) -> dict:
    try:
        await db.execute(text("SELECT 1"))
        return {"status": "healthy", "database": settings.POSTGRES_DB}
    except Exception as exc:
        return {"status": "unhealthy", "error": str(exc)[:200]}


async def _check_redis() -> dict:
    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(settings.REDIS_URL, socket_connect_timeout=2)
        pong = await client.ping()
        await client.aclose()
        return {"status": "healthy" if pong else "unhealthy"}
    except Exception as exc:
        return {"status": "unhealthy", "error": str(exc)[:200]}


@router.get("/health")
async def health() -> dict:
    return success(
        data={"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}
    )


@router.get("/health/deep")
async def deep_health(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    async def _safe_check(coro, name: str) -> dict:
        try:
            return await asyncio.wait_for(coro, timeout=5.0)
        except asyncio.TimeoutError:
            return {"status": "timeout", "error": f"{name} check timed out"}
        except Exception as exc:
            return {"status": "error", "error": str(exc)[:200]}

    checks = await asyncio.gather(
        _safe_check(_check_postgres(db), "postgres"),
        _safe_check(_check_redis(), "redis"),
    )
    result = {"postgres": checks[0], "redis": checks[1]}
    unhealthy = [n for n, c in result.items() if c.get("status") != "healthy"]
    overall = (
        "healthy"
        if not unhealthy
        else ("degraded" if len(unhealthy) < len(result) else "unhealthy")
    )
    return success(
        data={
            "status": overall,
            "checks": result,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )


@router.get("/health/storage")
async def storage_health(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    return success(
        data={
            "postgres": await _check_postgres(db),
            "redis": await _check_redis(),
        }
    )


@router.get("/info")
async def system_info(
    current_user: User = Depends(get_current_active_user),
) -> dict:
    return success(
        data={
            "app_name": settings.APP_NAME,
            "version": settings.VERSION,
            "env": settings.APP_ENV,
            "debug": settings.DEBUG,
            "database": settings.POSTGRES_DB,
            "python": platform.python_version(),
            "platform": platform.platform(),
            "features": {
                "auth": True,
                "rbac": True,
                "audit_log": True,
                "ip_whitelist": bool(settings.ADMIN_IP_WHITELIST),
                "registration": settings.ALLOW_REGISTRATION,
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )
