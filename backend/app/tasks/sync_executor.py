"""开发环境同步执行器：outbox 仍落库，任务在进程内立即执行。

生产环境使用 arq（TASK_EXECUTOR=arq + Redis）；本地 Redis 密码不可用时
以 sync 模式保证 Phase 1 功能闭环。两种模式共用 document_service 状态机。
"""

import uuid

from sqlalchemy import select, text

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
            result = await document_service.run_parse_task(
                db, uuid.UUID(document_id), uuid.UUID(kb_id)
            )
            task_id = result["task_id"]
            outbox = (
                await db.execute(
                    select(TaskOutbox).where(TaskOutbox.task_id == task_id)
                )
            ).scalar_one_or_none()
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
