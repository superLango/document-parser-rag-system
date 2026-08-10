"""arq Worker：文档解析任务 + Outbox 分发（Phase 1）。"""

import uuid

from arq import cron
from arq.connections import RedisSettings
from sqlalchemy import text

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.models.document import TaskOutbox
from app.services import document_service

logger = get_logger(__name__)


async def _superuser_session():
    db = AsyncSessionLocal()
    await db.execute(text("SELECT set_config('app.is_superuser', 'true', true)"))
    return db


async def parse_document_task(ctx: dict, document_id: str, kb_id: str) -> dict:
    """Phase 1 解析任务（占位流水线，真实解析后续阶段替换）。"""
    db = await _superuser_session()
    try:
        await db.execute(
            text("SELECT set_config('app.current_kb', :kb, true)"),
            {"kb": kb_id},
        )
        result = await document_service.run_parse_task(
            db, uuid.UUID(document_id), uuid.UUID(kb_id)
        )
        await db.commit()
        return result
    except Exception as exc:
        await db.rollback()
        try:
            await document_service.fail_task(
                db, uuid.UUID(kb_id), uuid.UUID(document_id), str(exc)
            )
        except Exception:
            logger.exception("标记任务失败时出错", document_id=document_id)
        raise
    finally:
        await db.close()


async def dispatch_outbox(ctx: dict) -> int:
    """扫描 pending outbox → 入队 arq → 标记 enqueued。"""
    db = await _superuser_session()
    try:
        rows = await document_service.claim_outbox(db, limit=20)
    finally:
        await db.close()

    redis = ctx.get("redis")
    if redis is None:
        logger.warning("Redis 不可用，outbox 暂缓分发", count=len(rows))
        return 0
    enqueued = 0
    for row in rows:
        payload = row.payload or {}
        await redis.enqueue_job(
            "parse_document_task",
            payload.get("document_id"),
            payload.get("kb_id"),
        )
        db = AsyncSessionLocal()
        try:
            current = await db.get(TaskOutbox, row.id)
            if current is not None:
                await document_service.mark_outbox(db, current, "enqueued")
            enqueued += 1
        finally:
            await db.close()
    return enqueued


class WorkerSettings:
    functions = [parse_document_task]
    cron_jobs = [
        cron(
            dispatch_outbox,
            second=range(0, 60, max(1, settings.TASK_DISPATCH_INTERVAL_SECONDS)),
        )
    ]
    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
    max_jobs = 10
    job_timeout = 600
    keep_result = 60
