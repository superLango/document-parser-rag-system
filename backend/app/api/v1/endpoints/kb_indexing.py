# ruff: noqa: B008 - FastAPI Depends 默认参数为框架标准写法（与现有端点一致）
"""S4 独立索引端点：手动触发索引 / 索引任务列表。"""

import asyncio
import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    activate_kb_context,
    get_pagination_params,
    require_not_pending,
)
from app.api.v1.endpoints.kb_documents import _require_editor
from app.core.config import settings
from app.core.database import get_db
from app.core.exceptions import BusinessException, ErrorCode
from app.core.response import paginated, success
from app.middleware.audit_log import audit_action
from app.models.user import User
from app.schemas.document import DocumentOut, DocumentTaskOut
from app.schemas.indexing import SearchRequest
from app.services import document_service, kb_service

router = APIRouter(prefix="/kb/{kb_id}", tags=["知识库索引"])


async def _kb_access(
    kb_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> dict:
    data = await kb_service.get_kb(db, current_user, kb_id)
    await activate_kb_context(db, kb_id, current_user)
    return data


@router.post("/documents/{document_id}/index")
@audit_action(action="document.index_start", resource_type="document")
async def start_document_index(
    kb_id: uuid.UUID,
    document_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> dict:
    """手动触发/重索引（editor+，幂等：同一文档同时仅一个活动索引任务）。"""
    kb = await _kb_access(kb_id, db=db, current_user=current_user)
    _require_editor(kb)
    task = await document_service.enqueue_index_task(db, kb_id, document_id)
    if task is None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_CONFLICT,
            message="文档已有索引任务进行中，请稍后重试",
            http_status=409,
        )
    if settings.TASK_EXECUTOR == "sync":
        from app.tasks.sync_executor import execute_sync_task

        asyncio.create_task(execute_sync_task(str(document_id), str(kb_id)))
    document = await document_service.get_document(db, kb_id, document_id)
    return success(
        data={
            "document": DocumentOut.model_validate(document).model_dump(),
            "task": DocumentTaskOut.model_validate(task).model_dump(),
        },
        message="索引任务已创建",
    )


@router.post("/search")
async def search_kb(
    kb_id: uuid.UUID,
    payload: SearchRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> dict:
    """混合检索（有效成员可读）：双向量 + BM25 + RRF。"""
    from dataclasses import asdict

    from app.services.indexing.retrieval import SearchFilters, retrieval_service

    await _kb_access(kb_id, db=db, current_user=current_user)
    filters = None
    if payload.filters is not None:
        filters = SearchFilters(
            document_id=payload.filters.document_id,
            has_table=payload.filters.has_table,
            level=payload.filters.level,
        )
    hits = await retrieval_service.search(
        db, kb_id, payload.query, top_k=payload.top_k, filters=filters
    )
    return success(
        data={
            "query": payload.query,
            "total": len(hits),
            "items": [asdict(h) for h in hits],
        },
        message="检索完成",
    )


@router.get("/index/tasks")
async def list_index_tasks(
    kb_id: uuid.UUID,
    request: Request,
    pagination: dict = Depends(get_pagination_params),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> dict:
    """索引任务列表（有效成员可读）。"""
    await _kb_access(kb_id, db=db, current_user=current_user)
    page = pagination["page"]
    page_size = pagination["page_size"]
    rows, total, filenames = await document_service.list_tasks(
        db, kb_id, page, page_size, task_type="document_index"
    )
    items = []
    for t in rows:
        item = DocumentTaskOut.model_validate(t).model_dump()
        item["filename"] = filenames.get(str(t.document_id), "")
        items.append(item)
    return paginated(items=items, total=total, page=page, page_size=page_size)
