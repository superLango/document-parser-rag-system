"""arq Worker：文档解析任务 + Outbox 分发（Phase 1）。"""

import uuid
from typing import ClassVar
from urllib.parse import unquote, urlparse

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


async def extract_document_task(ctx: dict, document_id: str, kb_id: str) -> dict:
    """结构化抽取任务（E4）：由 arq 执行抽取流水线并落库。"""
    from app.services.extraction import extraction_task_service

    db = await _superuser_session()
    try:
        await db.execute(
            text("SELECT set_config('app.current_kb', :kb, true)"),
            {"kb": kb_id},
        )
        return await extraction_task_service.run_extraction_task(
            db, uuid.UUID(document_id), uuid.UUID(kb_id)
        )
    except Exception:
        await db.rollback()
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


async def sync_term_bases_cron(ctx: dict) -> int:
    """术语集定时同步（S8/C3）：扫描 sync_enabled 术语集并逐个同步。

    单术语集失败仅记录日志，不中断整轮；受 TERM_SYNC_BATCH_LIMIT 限制。
    """
    from app.services.glossary import term_base_service

    db = await _superuser_session()
    try:
        bases = await term_base_service.list_syncable_bases(
            db, settings.TERM_SYNC_BATCH_LIMIT
        )
    finally:
        await db.close()
    synced = 0
    for base in bases:
        db = await _superuser_session()
        try:
            await db.execute(
                text("SELECT set_config('app.current_kb', :kb, true)"),
                {"kb": str(base.kb_id)},
            )
            await term_base_service.sync_term_base(db, base.kb_id, base.id)
            synced += 1
        except Exception:
            logger.exception(
                "术语集定时同步失败", base_id=str(base.id), kb_id=str(base.kb_id)
            )
        finally:
            await db.close()
    logger.info("术语集定时同步完成", scanned=len(bases), synced=synced)
    return synced


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
        if row.type == "document_index":
            job_name = "index_document_task"
        elif row.type == "document_extraction":
            job_name = "extract_document_task"
        else:
            job_name = "parse_document_task"
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


def _redis_settings_from_dsn(dsn: str) -> RedisSettings:
    """从 DSN 构建 RedisSettings（显式解码密码，支持含 @ 等特殊字符）。"""
    parsed = urlparse(dsn)
    return RedisSettings(
        host=parsed.hostname or "localhost",
        port=parsed.port or 6379,
        password=unquote(parsed.password) if parsed.password else None,
        database=int((parsed.path or "/0").lstrip("/") or 0),
    )


class WorkerSettings:
    functions: ClassVar[list] = [
        parse_document_task,
        index_document_task,
        extract_document_task,
    ]
    cron_jobs: ClassVar[list] = [
        cron(
            dispatch_outbox,
            second=tuple(range(0, 60, max(1, settings.TASK_DISPATCH_INTERVAL_SECONDS))),
        ),
        cron(cleanup_expired_parse_pages, hour=3, minute=0),
        cron(
            sync_term_bases_cron,
            hour=tuple(
                max(0, min(23, int(h))) for h in settings.TERM_SYNC_CRON_HOURS.split(",") if h.strip()
            ) or (3,),
        ),
    ]
    redis_settings = _redis_settings_from_dsn(settings.REDIS_URL)
    max_jobs = 10
    # 任务时长取决于文档/上下文/输出长度，无法预估；arq 要求数值型超时，
    # 设 7 天作为"实际不超时"的安全网，避免误杀仍在抽取的任务。
    # 显式停止/关闭时由 CancelledError 处理落 failed。
    job_timeout = 7 * 24 * 3600
    keep_result = 60
