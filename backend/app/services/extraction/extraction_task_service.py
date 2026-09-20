"""结构化抽取任务服务（E1）：启动/执行状态机。

- 启动：校验文档已完成解析+索引，创建 DocumentTask(type=document_extraction) + Outbox；
- 执行：running → 调用抽取流水线（E3 实现，E1 占位报错）→ completed/failed；
- 失败不自动重试（B11），直接落 failed 并写死信。
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessException, ErrorCode
from app.models.document import Document, DocumentTask, TaskDeadLetter, TaskOutbox
from app.services.extraction import pipeline, result_store


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _get_document(db: AsyncSession, kb_id, document_id) -> Document:
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
        raise BusinessException(code=ErrorCode.BUSINESS_NOT_FOUND, message="文档不存在")
    return doc


async def start_document_extraction(
    db: AsyncSession, kb_id, document_id, schema_template_id=None,
) -> dict:
    """创建抽取任务与 outbox（editor+ 由端点层控制）。

    schema_template_id：系统对接按 prompt 指定 Schema 模板时传入，
    抽取只处理该模板下的类别。
    """
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:k))"),
        {"k": f"extract:{document_id}"},
    )
    doc = await _get_document(db, kb_id, document_id)
    # 允许 partial：部分页解析失败的文档，其成功页已入库索引，同样可以抽取
    if doc.process_status not in ("completed", "partial") or doc.index_status != "indexed":
        raise BusinessException(
            code=ErrorCode.VALIDATION_ERROR,
            message="文档未完成解析与索引，无法抽取",
        )
    active = (
        await db.execute(
            select(func.count()).select_from(DocumentTask).where(
                DocumentTask.document_id == document_id,
                DocumentTask.type == "document_extraction",
                DocumentTask.status.in_(("queued", "running")),
            )
        )
    ).scalar_one()
    if active > 0:
        raise BusinessException(
            code=ErrorCode.BUSINESS_CONFLICT,
            message="该文档已有抽取任务进行中，请稍后重试",
            http_status=409,
        )
    task_id = str(uuid.uuid4())
    task = DocumentTask(
        kb_id=kb_id,
        document_id=document_id,
        task_id=task_id,
        type="document_extraction",
        status="queued",
        checkpoint={"schema_template_id": str(schema_template_id)} if schema_template_id else {},
    )
    db.add(task)
    db.add(TaskOutbox(
        task_id=task_id,
        type="document_extraction",
        payload={
            "document_id": str(document_id),
            "kb_id": str(kb_id),
            **({"schema_template_id": str(schema_template_id)} if schema_template_id else {}),
        },
        status="pending",
    ))
    await db.commit()
    await db.refresh(task)
    return {"task_id": task.task_id, "task_type": task.type}


async def run_extraction_task(db: AsyncSession, document_id: uuid.UUID, kb_id: uuid.UUID) -> dict:
    """执行抽取任务状态机（失败不自动重试，直接落 failed + 死信）。"""
    task = (
        await db.execute(
            select(DocumentTask)
            .where(
                DocumentTask.document_id == document_id,
                DocumentTask.kb_id == kb_id,
                DocumentTask.type == "document_extraction",
                DocumentTask.status.in_(("queued", "running")),
            )
            .order_by(DocumentTask.created_at.desc())
            .limit(1)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if task is None:
        raise RuntimeError("没有待执行的抽取任务")
    task.status = "running"
    task.heartbeat_at = _now()
    task_id = task.task_id
    await db.commit()
    try:
        await result_store.set_result_status(
            db, kb_id, document_id, status="running", progress=5
        )
        async def _on_progress(progress: int, _message: str) -> None:
            await result_store.set_result_status(
                db, kb_id, document_id, status="running", progress=progress
            )

        schema_template_id = ((task.checkpoint or {}).get("schema_template_id")) if task else None
        result = await pipeline.run(
            kb_id=str(kb_id), document_id=str(document_id), progress_cb=_on_progress,
            db=db,  # 沿用外部 session（含 KB RLS 上下文）；不传会导致内部自建 session 检索不完整
            schema_template_id=schema_template_id,
        )
        # E3 后：result 含 categories/summary/timing/schema 信息，落库并完成
        saved = await result_store.save_result(
            db, kb_id, document_id,
            schema_template_id=result.get("schema_template_id"),
            schema_name=result.get("schema_name", ""),
            categories=result.get("categories", []),
            summary=result.get("summary", {}),
            timing=result.get("timing", {}),
            status="completed",
            progress=100,
        )
        task.status = "completed"
        task.checkpoint = {"version": saved.version}
        task.updated_at = _now()
        await db.commit()
        return {"task_id": task.task_id, "status": "completed", "version": saved.version}
    except asyncio.CancelledError:
        # arq 超时取消：标记失败并重抛，避免任务状态卡在 running
        await db.rollback()
        task = (
            await db.execute(
                select(DocumentTask).where(DocumentTask.task_id == task_id)
            )
        ).scalar_one_or_none()
        if task is not None:
            task.status = "failed"
            task.error = {"message": "抽取任务被取消"}
            task.updated_at = _now()
        await result_store.set_result_status(
            db, kb_id, document_id, status="failed", progress=100,
            error={"message": "抽取任务被取消"},
        )
        await db.commit()
        raise
    except Exception as exc:  # noqa: BLE001
        message = str(exc)
        await db.rollback()
        task = (
            await db.execute(
                select(DocumentTask).where(DocumentTask.task_id == task_id)
            )
        ).scalar_one_or_none()
        if task is None:
            task_id = str(uuid.uuid4())
        if task is not None:
            task.status = "failed"
            task.error = {"message": message}
            task.updated_at = _now()
        db.add(TaskDeadLetter(
            task_id=task_id,
            type="document_extraction",
            error=message,
            attempts=1,
        ))
        await result_store.set_result_status(
            db, kb_id, document_id, status="failed", progress=100, error={"message": message}
        )
        await db.commit()
        return {"task_id": task_id, "status": "failed", "error": message}
