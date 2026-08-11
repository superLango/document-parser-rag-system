"""arq Worker：文档解析任务 + Outbox 分发（Phase 1）。"""

import uuid
from typing import ClassVar

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
    """文档解析任务：parsekit Phase 2 流水线（渲染→擦除→版面→拼装）。"""
    db = await _superuser_session()
    try:
        await db.execute(
            text("SELECT set_config('app.current_kb', :kb, true)"),
            {"kb": kb_id},
        )
        result = await document_service.run_parse_task(
            db, uuid.UUID(document_id), uuid.UUID(kb_id)
        )
        # 解析成功 → 自动创建独立索引任务（D8，失败不影响解析）
        try:
            await document_service.enqueue_index_task(
                db, uuid.UUID(kb_id), uuid.UUID(document_id)
            )
        except Exception:
            logger.exception("自动触发索引失败", document_id=document_id)
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


async def index_document_task(ctx: dict, document_id: str, kb_id: str) -> dict:
    """独立索引任务：分块 → 嵌入 → 幂等入库（D8）。"""
    db = await _superuser_session()
    try:
        await db.execute(
            text("SELECT set_config('app.current_kb', :kb, true)"),
            {"kb": kb_id},
        )
        result = await document_service.run_index_task(
            db, uuid.UUID(document_id), uuid.UUID(kb_id)
        )
        await db.commit()
        return result
    except Exception as exc:
        await db.rollback()
        try:
            await document_service.fail_index_task(
                db, uuid.UUID(kb_id), uuid.UUID(document_id), str(exc)
            )
        except Exception:
            logger.exception("标记索引任务失败时出错", document_id=document_id)
        raise
    finally:
        await db.close()


async def cleanup_expired_parse_pages(ctx: dict) -> int:
    """U14：每日清理超过保留期的 pages 中间产物。"""
    db = await _superuser_session()
    try:
        return await document_service.cleanup_expired_pages(db)
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
        job_name = (
            "index_document_task" if row.type == "document_index" else "parse_document_task"
        )
        await redis.enqueue_job(
            job_name,
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
    functions: ClassVar[list] = [parse_document_task, index_document_task]
    cron_jobs: ClassVar[list] = [
        cron(
            dispatch_outbox,
            second=range(0, 60, max(1, settings.TASK_DISPATCH_INTERVAL_SECONDS)),
        ),
        cron(cleanup_expired_parse_pages, hour=3, minute=0),
    ]
    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
    max_jobs = 10
    job_timeout = 600
    keep_result = 60
