"""Phase 1 文档服务：上传记录、任务/Outbox、解析占位流程、删除。"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.document import Document, DocumentTask, TaskDeadLetter, TaskOutbox
from app.services import storage

logger = get_logger(__name__)

PARSE_STAGES = ["rendering", "layout", "ocr", "rebuild"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def create_document(
    db: AsyncSession,
    kb_id: uuid.UUID,
    *,
    filename: str,
    file_type: str | None,
    file_size: int,
    sha256: str,
    object_key: str,
) -> tuple[Document, DocumentTask]:
    task_id = str(uuid.uuid4())
    document = Document(
        kb_id=kb_id,
        filename=filename,
        file_type=file_type,
        file_size=file_size,
        object_key=object_key,
        sha256=sha256,
        status="queued",
        process_status="queued",
    )
    db.add(document)
    await db.flush()
    task = DocumentTask(
        kb_id=kb_id,
        document_id=document.id,
        task_id=task_id,
        type="document_parse",
        status="queued",
        checkpoint={},
    )
    db.add(task)
    await db.flush()
    db.add(
        TaskOutbox(
            task_id=task_id,
            type="document_parse",
            payload={
                "document_id": str(document.id),
                "kb_id": str(kb_id),
            },
            status="pending",
        )
    )
    await db.commit()
    await db.refresh(document)
    await db.refresh(task)
    return document, task


async def list_documents(
    db: AsyncSession,
    kb_id: uuid.UUID,
    keyword: str | None,
    page: int,
    page_size: int,
) -> tuple[list[Document], int]:
    base = select(Document).where(Document.kb_id == kb_id, Document.deleted_at.is_(None))
    count_base = (
        select(func.count())
        .select_from(Document)
        .where(Document.kb_id == kb_id, Document.deleted_at.is_(None))
    )
    if keyword:
        like = f"%{keyword}%"
        cond = or_(Document.filename.ilike(like), Document.sha256.ilike(like))
        base = base.where(cond)
        count_base = count_base.where(cond)
    total = (await db.execute(count_base)).scalar_one()
    rows = (
        await db.execute(
            base.order_by(Document.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()
    return list(rows), total


async def get_document(
    db: AsyncSession, kb_id: uuid.UUID, document_id: uuid.UUID
) -> Document:
    doc = (
        await db.execute(
            select(Document).where(
                Document.id == document_id,
                Document.kb_id == kb_id,
                Document.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if doc is None:
        from app.core.exceptions import BusinessException, ErrorCode

        raise BusinessException(
            code=ErrorCode.BUSINESS_NOT_FOUND, message="文档不存在"
        )
    return doc


async def delete_document(
    db: AsyncSession, kb_id: uuid.UUID, document_id: uuid.UUID
) -> None:
    doc = await get_document(db, kb_id, document_id)
    doc.deleted_at = _now()
    doc.status = "deleted"
    await db.commit()
    await storage.delete_document_objects(kb_id, doc.object_key)


async def list_tasks(
    db: AsyncSession,
    kb_id: uuid.UUID,
    page: int,
    page_size: int,
) -> tuple[list[DocumentTask], int]:
    base = select(DocumentTask).where(DocumentTask.kb_id == kb_id)
    count_base = (
        select(func.count())
        .select_from(DocumentTask)
        .where(DocumentTask.kb_id == kb_id)
    )
    total = (await db.execute(count_base)).scalar_one()
    rows = (
        await db.execute(
            base.order_by(DocumentTask.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()
    return list(rows), total


async def claim_outbox(db: AsyncSession, limit: int = 10) -> list[TaskOutbox]:
    rows = (
        await db.execute(
            select(TaskOutbox)
            .where(TaskOutbox.status == "pending")
            .order_by(TaskOutbox.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    ).scalars().all()
    for row in rows:
        row.status = "claimed"
    await db.commit()
    return list(rows)


async def mark_outbox(
    db: AsyncSession, outbox: TaskOutbox, status: str, error: str | None = None
) -> None:
    outbox.status = status
    if status == "enqueued":
        outbox.enqueued_at = _now()
    if error:
        outbox.error = error[:500]
    await db.commit()


async def _update_task(
    db: AsyncSession, task: DocumentTask, **fields
) -> None:
    for key, value in fields.items():
        setattr(task, key, value)
    task.updated_at = _now()
    await db.commit()
    await db.refresh(task)


async def run_parse_task(
    db: AsyncSession, document_id: uuid.UUID, kb_id: uuid.UUID
) -> dict:
    """Phase 1 解析占位实现：驱动状态机与 checkpoint，真实解析后续阶段替换。"""
    document = await get_document(db, kb_id, document_id)
    task = (
        await db.execute(
            select(DocumentTask).where(
                DocumentTask.document_id == document_id,
                DocumentTask.kb_id == kb_id,
            )
        )
    ).scalars().first()
    if task is None:
        raise RuntimeError(f"任务不存在：document={document_id}")

    task.attempts += 1
    task.status = "running"
    task.heartbeat_at = _now()
    await db.commit()

    done: list[str] = []
    for stage in PARSE_STAGES:
        document.process_status = stage
        document.status = "parsing"
        done.append(stage)
        task.checkpoint = {"stages": list(done), "stub": True}
        task.heartbeat_at = _now()
        task.updated_at = _now()
        document.updated_at = _now()
        await db.commit()

    document.status = "completed"
    document.process_status = "completed"
    task.status = "completed"
    task.checkpoint = {
        "stages": PARSE_STAGES,
        "stub": True,
        "completed_at": _now().isoformat(),
    }
    await db.commit()
    await db.refresh(document)
    await db.refresh(task)
    return {"task_id": task.task_id, "status": "completed"}


async def fail_task(
    db: AsyncSession,
    kb_id: uuid.UUID,
    document_id: uuid.UUID,
    error: str,
) -> None:
    document = await get_document(db, kb_id, document_id)
    task = (
        await db.execute(
            select(DocumentTask).where(
                DocumentTask.document_id == document_id,
                DocumentTask.kb_id == kb_id,
            )
        )
    ).scalars().first()
    document.status = "failed"
    document.process_status = "failed"
    document.error = {"message": error[:500]}
    if task is not None:
        task.status = "failed"
        task.error = {"message": error[:500]}
        db.add(
            TaskDeadLetter(
                task_id=task.task_id,
                type=task.type,
                error=error[:1000],
                attempts=task.attempts,
            )
        )
    await db.commit()
