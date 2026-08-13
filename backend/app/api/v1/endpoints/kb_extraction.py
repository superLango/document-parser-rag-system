# ruff: noqa: B008 - FastAPI Depends 默认参数为框架标准写法
"""知识库结构化抽取端点（E4）。"""

import asyncio
import csv
import io
import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import activate_kb_context, require_not_pending
from app.api.v1.endpoints.kb_documents import _require_editor
from app.core.config import settings
from app.core.database import get_db
from app.core.response import success
from app.middleware.audit_log import audit_action
from app.models.document import Document, DocumentTask
from app.services import kb_service
from app.services.extraction import extraction_task_service, result_store

router = APIRouter(prefix="/kb/{kb_id}/extraction", tags=["知识库-结构化抽取"])


async def _kb_access(
    kb_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_not_pending),
) -> dict:
    data = await kb_service.get_kb(db, current_user, kb_id)
    await activate_kb_context(db, kb_id, current_user)
    return data


@router.get("/documents")
async def list_extractable_documents(
    kb_id: uuid.UUID, request: Request,
    db: AsyncSession = Depends(get_db), current_user=Depends(require_not_pending),
) -> dict:
    """已完成解析+索引的可抽取文档列表。"""
    await _kb_access(kb_id, db=db, current_user=current_user)
    rows = (
        await db.execute(
            select(Document)
            .where(
                Document.kb_id == kb_id,
                Document.deleted_at.is_(None),
                Document.process_status == "completed",
                Document.index_status == "indexed",
            )
            .order_by(Document.updated_at.desc())
        )
    ).scalars().all()
    items = []
    for doc in rows:
        latest = await result_store.get_latest(db, kb_id, doc.id)
        items.append({
            "id": str(doc.id),
            "filename": doc.filename,
            "file_size": doc.file_size,
            "page_count": doc.page_count,
            "status": doc.status,
            "extraction_status": doc.extraction_status,
            "latest_schema_name": latest.schema_name if latest else None,
            "history_count": await result_store.history_count(db, kb_id, doc.id),
            "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
        })
    return success(data={"items": items})


@router.post("/{document_id}")
@audit_action(action="extraction.start", resource_type="extraction")
async def start_extraction(
    kb_id: uuid.UUID, document_id: uuid.UUID, request: Request,
    db: AsyncSession = Depends(get_db), current_user=Depends(require_not_pending),
) -> dict:
    """启动结构化抽取（editor+；sync 模式立即后台执行）。"""
    kb = await _kb_access(kb_id, db=db, current_user=current_user)
    _require_editor(kb)
    started = await extraction_task_service.start_document_extraction(db, kb_id, document_id)
    if settings.TASK_EXECUTOR == "sync":
        from app.tasks.sync_executor import execute_sync_task

        asyncio.create_task(execute_sync_task(str(document_id), str(kb_id)))
    return success(data={"task_id": started["task_id"], "status": "queued"})


@router.get("/{document_id}/status")
async def get_extraction_status(
    kb_id: uuid.UUID, document_id: uuid.UUID, request: Request,
    db: AsyncSession = Depends(get_db), current_user=Depends(require_not_pending),
) -> dict:
    await _kb_access(kb_id, db=db, current_user=current_user)
    task = (
        await db.execute(
            select(DocumentTask)
            .where(
                DocumentTask.document_id == document_id,
                DocumentTask.kb_id == kb_id,
                DocumentTask.type == "document_extraction",
            )
            .order_by(DocumentTask.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    latest = await result_store.get_latest(db, kb_id, document_id)
    return success(data={
        "task_id": task.task_id if task else None,
        "task_status": task.status if task else None,
        "status": latest.status if latest else None,
        "progress": latest.progress if latest else 0,
        "error": latest.error if latest else None,
    })


@router.get("/{document_id}/result")
async def get_extraction_result(
    kb_id: uuid.UUID, document_id: uuid.UUID, request: Request,
    db: AsyncSession = Depends(get_db), current_user=Depends(require_not_pending),
) -> dict:
    await _kb_access(kb_id, db=db, current_user=current_user)
    row = await result_store.get_latest(db, kb_id, document_id)
    if row is None:
        return success(data=None)
    return success(data={
        "schema_template_id": str(row.schema_template_id) if row.schema_template_id else None,
        "schema_name": row.schema_name,
        "status": row.status,
        "progress": row.progress,
        "categories": row.categories or [],
        "summary": row.summary or {},
        "timing": row.timing or {},
        "version": row.version,
        "error": row.error,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    })


@router.get("/{document_id}/history")
async def get_extraction_history(
    kb_id: uuid.UUID, document_id: uuid.UUID, request: Request,
    db: AsyncSession = Depends(get_db), current_user=Depends(require_not_pending),
) -> dict:
    await _kb_access(kb_id, db=db, current_user=current_user)
    return success(data={"items": await result_store.list_history(db, kb_id, document_id)})


@router.get("/export")
async def export_extraction_result(
    kb_id: uuid.UUID, document_id: uuid.UUID, request: Request,
    db: AsyncSession = Depends(get_db), current_user=Depends(require_not_pending),
) -> StreamingResponse:
    await _kb_access(kb_id, db=db, current_user=current_user)
    row = await result_store.get_latest(db, kb_id, document_id)
    buf = io.StringIO()
    writer = csv.writer(buf)
    headers = ["类别"]
    seen: set[str] = set()
    if row is not None:
        for cat in row.categories or []:
            for rec in cat.get("records") or []:
                for k in rec:
                    if k not in seen:
                        seen.add(k)
                        headers.append(k)
    writer.writerow(headers)
    if row is not None:
        for cat in row.categories or []:
            for rec in cat.get("records") or []:
                writer.writerow([cat.get("feature", "")] + [rec.get(h, "") for h in headers[1:]])
    filename = f"extraction_{document_id}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("/{document_id}/result")
@audit_action(action="extraction.delete", resource_type="extraction")
async def delete_extraction_result(
    kb_id: uuid.UUID, document_id: uuid.UUID, request: Request,
    db: AsyncSession = Depends(get_db), current_user=Depends(require_not_pending),
) -> dict:
    """删除最新结果与全部历史（editor+）。"""
    kb = await _kb_access(kb_id, db=db, current_user=current_user)
    _require_editor(kb)
    await result_store.delete_result_and_history(db, kb_id, document_id)
    return success(message="抽取结果已删除")
