"""Phase 1 知识库文档端点：上传/列表/详情/任务/删除。"""

import asyncio
import hashlib
import uuid

from fastapi import APIRouter, Depends, Query, Request, Response, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    UPLOAD_LIMIT,
    activate_kb_context,
    get_pagination_params,
    limiter,
    require_not_pending,
)
from app.core.config import settings
from app.core.database import get_db
from app.core.exceptions import ValidationException
from app.core.response import paginated, success
from app.middleware.audit_log import audit_action
from app.models.user import User
from app.schemas.document import DocumentOut, DocumentTaskOut, UploadDocumentOut
from app.services import document_service, kb_service, storage

router = APIRouter(prefix="/kb/{kb_id}/documents", tags=["知识库文档"])

EDIT_ROLES = frozenset({"owner", "admin", "editor"})


async def _kb_access(
    kb_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> dict:
    data = await kb_service.get_kb(db, current_user, kb_id)
    await activate_kb_context(db, kb_id, current_user)
    return data


def _require_editor(kb: dict) -> None:
    if kb.get("my_role") not in EDIT_ROLES:
        from app.core.exceptions import PermissionException

        raise PermissionException(message="需要编辑者及以上权限")


@router.post("")
@limiter.limit(UPLOAD_LIMIT)
@audit_action(action="document.upload", resource_type="document")
async def upload_document(
    kb_id: uuid.UUID,
    request: Request,
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> dict:
    kb = await _kb_access(kb_id, db=db, current_user=current_user)
    _require_editor(kb)

    filename = (file.filename or "document.pdf").strip()
    if not filename.lower().endswith(".pdf"):
        raise ValidationException(message="仅支持 PDF 文件")
    if len(filename.encode("utf-8")) > 255:
        raise ValidationException(message="文件名过长")

    max_bytes = settings.DOCUMENT_MAX_SIZE_MB * 1024 * 1024
    chunks: list[bytes] = []
    size = 0
    while chunk := await file.read(1024 * 1024):
        size += len(chunk)
        if size > max_bytes:
            raise ValidationException(
                message=f"文件超过 {settings.DOCUMENT_MAX_SIZE_MB}MB 限制"
            )
        chunks.append(chunk)
    data = b"".join(chunks)
    if not data:
        raise ValidationException(message="文件为空")
    sha256 = hashlib.sha256(data).hexdigest()

    task_id = str(uuid.uuid4())
    object_key = await storage.put_original(kb_id, task_id, filename, data)
    try:
        document, task = await document_service.create_document(
            db,
            kb_id,
            filename=filename,
            file_type="pdf",
            file_size=size,
            sha256=sha256,
            object_key=object_key,
            task_id=task_id,
        )
    except Exception:
        await storage.delete_document_objects(kb_id, object_key)
        raise
    return success(
        data=UploadDocumentOut(
            document=DocumentOut.model_validate(document),
            task=DocumentTaskOut.model_validate(task),
        ).model_dump(),
        message="文档已上传，待解析",
    )


@router.post("/{document_id}/start")
@audit_action(action="document.parse_start", resource_type="document")
async def start_document_parse(
    kb_id: uuid.UUID,
    document_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> dict:
    """手动开始解析（editor+；上传后默认待解析）。"""
    kb = await _kb_access(kb_id, db=db, current_user=current_user)
    _require_editor(kb)
    task = await document_service.start_document_parse(db, kb_id, document_id)
    if settings.TASK_EXECUTOR == "sync":
        from app.tasks.sync_executor import execute_sync_task

        asyncio.create_task(execute_sync_task(str(document_id), str(kb_id)))
    return success(
        data=DocumentTaskOut.model_validate(task).model_dump(),
        message="解析已开始",
    )


@router.get("")
async def list_documents(
    kb_id: uuid.UUID,
    keyword: str | None = Query(None),
    pagination: dict = Depends(get_pagination_params),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> dict:
    await _kb_access(kb_id, db=db, current_user=current_user)
    items, total = await document_service.list_documents(
        db,
        kb_id,
        keyword,
        pagination["page"],
        pagination["page_size"],
    )
    return paginated(
        [DocumentOut.model_validate(d).model_dump() for d in items],
        total,
        pagination["page"],
        pagination["page_size"],
    )


@router.get("/tasks")
async def list_tasks(
    kb_id: uuid.UUID,
    pagination: dict = Depends(get_pagination_params),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> dict:
    await _kb_access(kb_id, db=db, current_user=current_user)
    items, total, filenames = await document_service.list_tasks(
        db, kb_id, pagination["page"], pagination["page_size"]
    )
    rows = []
    for task in items:
        row = DocumentTaskOut.model_validate(task).model_dump()
        row["filename"] = filenames.get(str(task.document_id))
        rows.append(row)
    return paginated(rows, total, pagination["page"], pagination["page_size"])


@router.get("/{document_id}")
async def get_document(
    kb_id: uuid.UUID,
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> dict:
    await _kb_access(kb_id, db=db, current_user=current_user)
    document = await document_service.get_document(db, kb_id, document_id)
    return success(data=DocumentOut.model_validate(document).model_dump())


@router.delete("/{document_id}")
@audit_action(action="document.delete", resource_type="document")
async def delete_document(
    kb_id: uuid.UUID,
    document_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> dict:
    kb = await _kb_access(kb_id, db=db, current_user=current_user)
    _require_editor(kb)
    await document_service.delete_document(db, kb_id, document_id)
    return success(message="文档已删除")


@router.get("/{document_id}/pages/{page_index}")
async def get_document_page(
    kb_id: uuid.UUID,
    document_id: uuid.UUID,
    page_index: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> Response:
    """页面预览 PNG（viewer+；已清理/越界 400）。"""
    await _kb_access(kb_id, db=db, current_user=current_user)
    data = await document_service.get_page_image(
        db, kb_id, document_id, page_index
    )
    return Response(content=data, media_type="image/png")


@router.get("/{document_id}/original")
async def get_document_original(
    kb_id: uuid.UUID,
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> Response:
    """原始 PDF 预览（viewer+；供待解析/解析中内页查看原文档）。"""
    await _kb_access(kb_id, db=db, current_user=current_user)
    document = await document_service.get_document(db, kb_id, document_id)
    try:
        data = storage.get_object(document.object_key)
    except Exception as exc:
        raise ValidationException(message="原始 PDF 读取失败") from exc
    return Response(content=data, media_type="application/pdf")


@router.get("/{document_id}/markdown")
async def get_document_markdown(
    kb_id: uuid.UUID,
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> Response:
    """查看解析 Markdown 产物（viewer+）。"""
    await _kb_access(kb_id, db=db, current_user=current_user)
    document = await document_service.get_document(db, kb_id, document_id)
    if not document.markdown_path:
        raise ValidationException(message="文档暂无解析产物")
    try:
        content = storage.get_object(document.markdown_path)
    except Exception as exc:
        raise ValidationException(message="解析产物读取失败") from exc
    return Response(
        content=content.decode("utf-8", errors="replace"),
        media_type="text/markdown; charset=utf-8",
    )


@router.get("/{document_id}/layout")
async def get_document_layout(
    kb_id: uuid.UUID,
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> dict:
    """查看版面结构 layout.json（viewer+）。"""
    await _kb_access(kb_id, db=db, current_user=current_user)
    document = await document_service.get_document(db, kb_id, document_id)
    if not document.layout_path:
        raise ValidationException(message="文档暂无版面产物")
    try:
        content = storage.get_object(document.layout_path)
    except Exception as exc:
        raise ValidationException(message="版面产物读取失败") from exc
    import json

    layout = json.loads(content.decode("utf-8"))
    return success(data=layout)


@router.post("/{document_id}/reparse")
@audit_action(action="document.reparse", resource_type="document")
async def reparse_document(
    kb_id: uuid.UUID,
    document_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> dict:
    """重新解析（editor+，幂等：同一文档同时只有一个活动任务）。"""
    kb = await _kb_access(kb_id, db=db, current_user=current_user)
    _require_editor(kb)
    task_id = str(uuid.uuid4())
    document, task = await document_service.reset_document_for_reparse(
        db, kb_id, document_id, task_id
    )
    if settings.TASK_EXECUTOR == "sync":
        from app.tasks.sync_executor import execute_sync_task

        asyncio.create_task(execute_sync_task(str(document.id), str(kb_id)))
    return success(
        data=UploadDocumentOut(
            document=DocumentOut.model_validate(document),
            task=DocumentTaskOut.model_validate(task),
        ).model_dump(),
        message="重新解析任务已创建",
    )
