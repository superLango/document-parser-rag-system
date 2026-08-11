"""开发环境同步执行器：outbox 仍落库，任务在进程内立即执行。

生产环境使用 arq（TASK_EXECUTOR=arq + Redis）；本地 Redis 密码不可用时
以 sync 模式保证 Phase 1 功能闭环。两种模式共用 document_service 状态机。
"""

import uuid

from sqlalchemy import select, text

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.models.document import TaskOutbox
from app.services import document_service

logger = get_logger(__name__)


async def execute_sync_task(document_id: str, kb_id: str) -> dict:
    async with AsyncSessionLocal() as db:
        await db.execute(text("SELECT set_config('app.is_superuser', 'true', true)"))
        await db.execute(
            text("SELECT set_config('app.current_kb', :kb, true)"),
            {"kb": kb_id},
        )
        try:
            from app.models.document import DocumentTask

            # 1) 优先按该文档最新 pending outbox 路由（parse/index）
            outbox = (
                await db.execute(
                    select(TaskOutbox)
                    .where(TaskOutbox.status == "pending")
                    .where(TaskOutbox.payload["document_id"].astext == document_id)
                    .order_by(TaskOutbox.created_at.desc())
                    .limit(1)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if outbox is not None:
                task_type = outbox.type
            else:
                # 2) 无 outbox（如产物预置场景）按最新 queued 任务路由
                task_row = (
                    await db.execute(
                        select(DocumentTask)
                        .where(
                            DocumentTask.document_id == uuid.UUID(document_id),
                            DocumentTask.status == "queued",
                        )
                        .order_by(DocumentTask.created_at.desc())
                        .limit(1)
                        .with_for_update()
                    )
                ).scalar_one_or_none()
                if task_row is None:
                    raise RuntimeError("没有待执行的解析/索引任务")
                task_type = task_row.type

            if task_type == "document_index":
                result = await document_service.run_index_task(
                    db, uuid.UUID(document_id), uuid.UUID(kb_id)
                )
            else:
                result = await document_service.run_parse_task(
                    db, uuid.UUID(document_id), uuid.UUID(kb_id)
                )
                # 解析成功 → 同会话自动创建独立索引任务（D8，失败不影响解析）
                try:
                    index_task = await document_service.enqueue_index_task(
                        db, uuid.UUID(kb_id), uuid.UUID(document_id)
                    )
                    # sync 模式无 dispatcher：立即执行自动索引，避免任务悬挂
                    if index_task is not None and settings.TASK_EXECUTOR == "sync":
                        await document_service.run_index_task(
                            db, uuid.UUID(document_id), uuid.UUID(kb_id)
                        )
                        idx_outbox = (
                            await db.execute(
                                select(TaskOutbox).where(
                                    TaskOutbox.task_id == index_task.task_id
                                )
                            )
                        ).scalar_one_or_none()
                        if idx_outbox is not None:
                            await document_service.mark_outbox(db, idx_outbox, "done")
                except Exception:
                    logger.exception("自动触发索引失败", document_id=document_id)
            if outbox is not None:
                await document_service.mark_outbox(db, outbox, "done")
            return result
        except Exception as exc:
            await db.rollback()
            try:
                await document_service.fail_task(
                    db, uuid.UUID(kb_id), uuid.UUID(document_id), str(exc)
                )
            except Exception:
                logger.exception("同步任务失败标记异常", document_id=document_id)
            raise
