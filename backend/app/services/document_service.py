"""文档服务：上传记录、任务/Outbox、parsekit 解析流水线、删除与重解析。"""

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.document import Document, DocumentTask, TaskDeadLetter, TaskOutbox
from app.services import storage
from app.services.parsekit import ParseOptions, ParsekitError, parse_pdf

logger = get_logger(__name__)

PARSE_STAGES = ["rendering", "layout", "ocr", "rebuild"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _artifact_keys(kb_id: uuid.UUID, task_id: str) -> dict:
    base = f"kb-{kb_id.hex}/ocr/{task_id}"
    return {
        "base": base,
        "markdown": f"{base}/result.md",
        "layout": f"{base}/layout.json",
    }


async def create_document(
    db: AsyncSession,
    kb_id: uuid.UUID,
    *,
    filename: str,
    file_type: str | None,
    file_size: int,
    sha256: str,
    object_key: str,
    task_id: str | None = None,
) -> tuple[Document, DocumentTask]:
    task_id = task_id or str(uuid.uuid4())
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


async def reset_document_for_reparse(
    db: AsyncSession,
    kb_id: uuid.UUID,
    document_id: uuid.UUID,
    task_id: str,
) -> tuple[Document, DocumentTask]:
    """重置文档并创建新解析任务（幂等：咨询锁 + 活动任务检查）。"""
    from app.core.exceptions import BusinessException, ErrorCode

    # 咨询锁串行化同一文档的重解析，避免并发创建两个任务
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
        {"key": f"reparse:{document_id}"},
    )
    document = (
        await db.execute(
            select(Document)
            .where(
                Document.id == document_id,
                Document.kb_id == kb_id,
                Document.deleted_at.is_(None),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if document is None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_NOT_FOUND, message="文档不存在"
        )
    active = (
        await db.execute(
            select(func.count())
            .select_from(DocumentTask)
            .where(
                DocumentTask.document_id == document_id,
                DocumentTask.status.in_(("queued", "running")),
            )
        )
    ).scalar_one()
    if active > 0:
        raise BusinessException(
            code=ErrorCode.BUSINESS_NOT_FOUND,
            message="文档已有解析任务进行中，请稍后重试",
        )

    document.status = "queued"
    document.process_status = "queued"
    document.page_count = 0
    document.markdown_path = None
    document.layout_path = None
    document.error = None
    document.updated_at = _now()
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


async def run_parse_task(
    db: AsyncSession, document_id: uuid.UUID, kb_id: uuid.UUID
) -> dict:
    """Phase 2 解析流水线：渲染→擦除→版面→顺序→拼装→产物落库。"""
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

    options = ParseOptions.from_settings()
    checkpoint_meta = {
        "engine": options.layout_engine,
        "header_footer_mode": options.header_footer_mode,
        "dpi": options.dpi,
    }
    done: list[str] = []
    for stage in PARSE_STAGES:
        document.process_status = stage
        document.status = "parsing"
        done.append(stage)
        task.checkpoint = {**checkpoint_meta, "stages": list(done)}
        task.heartbeat_at = _now()
        task.updated_at = _now()
        document.updated_at = _now()
        await db.commit()

    try:
        pdf_bytes = storage.get_object(document.object_key)
    except Exception as exc:
        raise RuntimeError(f"读取原始 PDF 失败：{exc}") from exc

    try:
        result = parse_pdf(pdf_bytes, options=options)
    except ParsekitError as exc:
        raise RuntimeError(str(exc)) from exc

    keys = _artifact_keys(kb_id, task.task_id)
    try:
        storage.put_object(
            keys["markdown"], result.markdown.encode("utf-8"), "text/markdown"
        )
        storage.put_object(
            keys["layout"],
            json.dumps(result.layout, ensure_ascii=False).encode("utf-8"),
            "application/json",
        )
        for page in result.pages:
            storage.put_object(
                f"{keys['base']}/{page['path']}",
                page["image_bytes"],
                "image/png",
            )
    except Exception as exc:
        raise RuntimeError(f"解析产物落库失败：{exc}") from exc

    partial = bool(result.page_failures) and options.partial_on_page_failure
    document.page_count = len(result.pages)
    document.markdown_path = keys["markdown"]
    document.layout_path = keys["layout"]
    document.status = "completed"
    document.process_status = "partial" if partial else "completed"
    document.error = None
    task.status = "completed"
    task.error = None
    task.checkpoint = {
        **checkpoint_meta,
        "stages": PARSE_STAGES,
        "page_count": len(result.pages),
        "blocks": result.stats.get("blocks", 0),
        "erased_blocks": result.stats.get("erased_blocks", 0),
        "page_failures": result.page_failures,
        "partial": partial,
        "completed_at": _now().isoformat(),
    }
    task.heartbeat_at = _now()
    task.updated_at = _now()
    document.updated_at = _now()
    await db.commit()
    await db.refresh(document)
    await db.refresh(task)
    return {
        "task_id": task.task_id,
        "status": task.status,
        "partial": partial,
    }


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
