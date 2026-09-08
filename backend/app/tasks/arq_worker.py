"""arq Worker：文档解析任务 + Outbox 分发（Phase 1）。"""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from typing import ClassVar
from urllib.parse import unquote, urlparse

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.models.document import TaskOutbox
from app.services import document_service
from arq import cron
from arq.connections import RedisSettings
from sqlalchemy import text

logger = get_logger(__name__)


async def _superuser_session():
    db = AsyncSessionLocal()
    await db.execute(text("SELECT set_config('app.is_superuser', 'true', true)"))
    return db


async def _update_integration_task(db, document_id, **patch) -> list[str]:
    """按 document_id 更新对接任务状态（无对接任务则跳过）。"""
    from app.models.integration_task import IntegrationTask
    from sqlalchemy import select

    tasks = (
        (
            await db.execute(
                select(IntegrationTask).where(
                    IntegrationTask.document_id == document_id
                )
            )
        )
        .scalars()
        .all()
    )
    for task in tasks:
        for key, value in patch.items():
            setattr(task, key, value)
        task.updated_at = datetime.now(timezone.utc)
    return [str(task.task_id) for task in tasks]


async def _notify_integration_terminal(
    task_ids: list[str] | None, status: str, reason: str = "", parse_time: float | None = None
) -> None:
    """通知全部关联的一站式任务；网络失败不影响 Worker 业务状态。"""
    from app.services.integration_callback import send_status_callback

    if not task_ids:
        return
    await asyncio.gather(
        *(send_status_callback(task_id, status, reason, parse_time) for task_id in task_ids)
    )


async def _trigger_integration_extract(db, kb_id, document_id) -> None:
    """索引完成后：存在待抽取的对接任务则自动触发抽取（带 schema_template_id）。"""
    from app.models.integration_task import IntegrationTask
    from app.services.extraction import extraction_task_service
    from sqlalchemy import select

    itask = (
        (
            await db.execute(
                select(IntegrationTask).where(
                    IntegrationTask.document_id == document_id,
                    IntegrationTask.extract_status == "pending",
                )
            )
        )
        .scalars()
        .first()
    )
    if itask is None:
        return
    await db.execute(
        text("SELECT set_config('app.current_kb', :kb, true)"), {"kb": str(kb_id)}
    )
    await extraction_task_service.start_document_extraction(
        db,
        kb_id,
        document_id,
        schema_template_id=str(itask.schema_template_id)
        if itask.schema_template_id
        else None,
    )
    itask.extract_status = "queued"
    itask.extract_progress = 0
    itask.updated_at = datetime.now(timezone.utc)


async def _apply_extract_result(
    db, document_id, result
) -> tuple[list[str], str, str, float | None]:
    """按抽取任务结果回写对接任务状态（成功取 version/耗时，失败回写错误原因）。"""
    if isinstance(result, dict) and result.get("status") == "completed":
        task_ids = await _update_integration_task(
            db,
            document_id,
            extract_status="completed",
            extract_progress=100,
            result_version=result.get("version"),
            error="",
        )
        # 解析耗时(秒): 取 pipeline timing.total_sec
        parse_time = None
        timing = result.get("timing") if isinstance(result, dict) else None
        if isinstance(timing, dict):
            try:
                parse_time = float(timing.get("total_sec"))
            except (TypeError, ValueError):
                parse_time = None
        return task_ids, "success", "", parse_time
    else:
        err = (
            result.get("error") if isinstance(result, dict) else str(result)
        ) or "结构化抽取失败"
        task_ids = await _update_integration_task(
            db,
            document_id,
            extract_status="failed",
            extract_progress=100,
            error=str(err)[:500],
        )
        return task_ids, "failed", str(err)[:500], None


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
        except Exception as exc:
            logger.exception("自动触发索引失败", document_id=document_id)
            await db.rollback()
            reason = f"自动触发索引失败：{exc}"[:500]
            task_ids = await _update_integration_task(
                db,
                uuid.UUID(document_id),
                ocr_status="failed",
                error=reason,
            )
            await db.commit()
            await _notify_integration_terminal(task_ids, "failed", reason)
            if task_ids:
                return result
        await db.commit()
        await _update_integration_task(
            db,
            uuid.UUID(document_id),
            ocr_status="completed",
            ocr_progress=100,
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
        await db.rollback()
        try:
            task_ids = await _update_integration_task(
                db,
                uuid.UUID(document_id),
                ocr_status="failed",
                error=str(exc)[:500],
            )
            await db.commit()
            await _notify_integration_terminal(task_ids, "failed", str(exc)[:500])
        except Exception:
            logger.exception("回写对接任务 OCR 失败状态出错", document_id=document_id)
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
        # 索引完成 → 自动触发对接任务的结构化抽取
        try:
            await _trigger_integration_extract(db, kb_id, uuid.UUID(document_id))
            await db.commit()
        except Exception as exc:
            logger.exception("自动触发对接抽取失败", document_id=document_id)
            await db.rollback()
            reason = f"自动触发结构化抽取失败：{exc}"[:500]
            task_ids = await _update_integration_task(
                db,
                uuid.UUID(document_id),
                extract_status="failed",
                extract_progress=100,
                error=reason,
            )
            await db.commit()
            await _notify_integration_terminal(task_ids, "failed", reason)
        return result
    except Exception as exc:
        await db.rollback()
        try:
            await document_service.fail_index_task(
                db, uuid.UUID(kb_id), uuid.UUID(document_id), str(exc)
            )
        except Exception:
            logger.exception("标记索引任务失败时出错", document_id=document_id)
        await db.rollback()
        try:
            task_ids = await _update_integration_task(
                db,
                uuid.UUID(document_id),
                ocr_status="failed",
                error=str(exc)[:500],
            )
            await db.commit()
            await _notify_integration_terminal(task_ids, "failed", str(exc)[:500])
        except Exception:
            logger.exception("回写对接任务 OCR 失败状态出错", document_id=document_id)
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
        result = await extraction_task_service.run_extraction_task(
            db, uuid.UUID(document_id), uuid.UUID(kb_id)
        )
        task_ids, status, reason, parse_time = await _apply_extract_result(
            db, uuid.UUID(document_id), result
        )
        await db.commit()
        await _notify_integration_terminal(task_ids, status, reason, parse_time)
        return result
    except Exception as exc:
        await db.rollback()
        try:
            task_ids = await _update_integration_task(
                db,
                uuid.UUID(document_id),
                extract_status="failed",
                extract_progress=100,
                error=str(exc)[:500],
            )
            await db.commit()
            await _notify_integration_terminal(task_ids, "failed", str(exc)[:500])
        except Exception:
            logger.exception("回写对接任务抽取失败状态出错", document_id=document_id)
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


async def sync_term_base_task(ctx: dict, kb_id: str, base_id: str) -> dict:
    """单个术语集定时同步任务（按 cron 命中由调度器入队）。

    advisory lock 防并发（手动同步/多 worker 重复触发）；失败回写 failed 不重试。
    """
    from app.services.glossary import term_base_service

    db = await _superuser_session()
    try:
        await db.execute(
            text("SELECT set_config('app.current_kb', :kb, true)"), {"kb": kb_id}
        )
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
            {"key": f"term-sync:{base_id}"},
        )
        result = await term_base_service.sync_term_base(
            db, uuid.UUID(kb_id), uuid.UUID(base_id)
        )
        await db.commit()
        return result
    except Exception as exc:
        await db.rollback()
        try:
            await term_base_service.mark_sync_failed(
                db, uuid.UUID(kb_id), uuid.UUID(base_id), str(exc)
            )
        except Exception:
            logger.exception("回写定时同步失败状态出错", base_id=base_id, kb_id=kb_id)
        raise
    finally:
        await db.close()


async def dispatch_term_sync_cron(ctx: dict) -> int:
    """术语集定时同步调度：每分钟扫描 cron 命中项并异步入队。

    按各术语集 sync_cron 表达式匹配当前分钟窗口；Redis 幂等键防止同分钟重复入队。
    """
    from app.services.glossary import term_base_service
    from croniter import croniter

    db = await _superuser_session()
    try:
        bases = await term_base_service.list_syncable_bases(
            db, settings.TERM_SYNC_BATCH_LIMIT
        )
    finally:
        await db.close()
    redis = ctx.get("redis")
    if redis is None:
        logger.warning("Redis 不可用，术语集定时同步暂缓")
        return 0
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(seconds=60)
    enqueued = 0
    for base in bases:
        key = f"term-sync-dispatch:{base.id}:{now:%Y%m%d%H%M}"
        if await redis.get(key):
            continue
        try:
            nxt = croniter(base.sync_cron, window_start).get_next(datetime)
        except Exception:  # noqa: BLE001 - 表达式异常跳过该术语集
            logger.warning(
                "术语集 cron 表达式无效", base_id=str(base.id), cron=base.sync_cron
            )
            continue
        if nxt > now:
            continue
        await redis.enqueue_job("sync_term_base_task", str(base.kb_id), str(base.id))
        await redis.set(key, "1", ex=180)
        enqueued += 1
    logger.info("术语集定时同步调度完成", scanned=len(bases), enqueued=enqueued)
    return enqueued


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
        sync_term_base_task,
    ]
    cron_jobs: ClassVar[list] = [
        cron(
            dispatch_outbox,
            second=tuple(range(0, 60, max(1, settings.TASK_DISPATCH_INTERVAL_SECONDS))),
        ),
        cron(cleanup_expired_parse_pages, hour=3, minute=0),
        # 术语集定时同步：每分钟扫描 cron 命中项并异步入队（按各术语集 sync_cron）
        cron(dispatch_term_sync_cron, second=0),
    ]
    redis_settings = _redis_settings_from_dsn(settings.REDIS_URL)
    max_jobs = 10

    @staticmethod
    async def on_startup(ctx: dict) -> None:
        # 异步预热进程内模型（BGE-M3/重排/版面）与外部 vLLM 服务，
        # 避免抽取任务首次执行时才加载导致失败；不阻塞 worker 启动。
        from app.services.model_warmup import model_warmup

        if settings.MODEL_WARMUP_ENABLED:
            await model_warmup.warmup_all()

    # 任务时长取决于文档/上下文/输出长度，无法预估；arq 要求数值型超时，
    # 设 7 天作为"实际不超时"的安全网，避免误杀仍在抽取的任务。
    # 显式停止/关闭时由 CancelledError 处理落 failed。
    job_timeout = 7 * 24 * 3600
    keep_result = 60
