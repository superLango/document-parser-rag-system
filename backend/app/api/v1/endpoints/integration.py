# ruff: noqa: B008 - FastAPI Depends 默认参数为框架标准写法（与现有端点一致）
"""系统对接端点：一站式上传 / 状态查询 / 结果查看 / 重触发（无认证，先走通流程）。

内部使用 superuser 会话 + 显式 kb_id 绕过 RLS；后续接入认证时在此统一补充。
"""

import uuid

from fastapi import APIRouter, Depends, Request, UploadFile
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.exceptions import ValidationException
from app.core.response import success
from app.services import integration_service

router = APIRouter(prefix="/integration", tags=["系统对接"])


async def _superuser_ctx(db: AsyncSession, kb_id=None) -> None:
    await db.execute(text("SELECT set_config('app.is_superuser', 'true', true)"))
    if kb_id:
        await db.execute(
            text("SELECT set_config('app.current_kb', :kb, true)"), {"kb": str(kb_id)}
        )


@router.post("/upload")
async def integration_upload(
    request: Request,
    file: UploadFile,
    kb_id: uuid.UUID,
    prompt_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """一站式上传：上传 PDF → OCR 解析 → 索引 → 结构化抽取（异步）。"""
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
    await _superuser_ctx(db, kb_id)
    itask = await integration_service.create_task(
        db,
        kb_id=kb_id,
        prompt_id=prompt_id,
        filename=filename,
        file_size=size,
        data=data,
    )
    return success(
        data=integration_service.to_view(itask),
        message="任务已创建，正在异步执行 OCR 解析与结构化抽取",
    )


@router.get("/tasks/{task_id}/status")
async def integration_status(
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """任务状态：OCR 状态 + 结构化抽取状态，失败返回原因。"""
    await _superuser_ctx(db)
    itask = await integration_service.get_task(db, task_id)
    return success(data=integration_service.to_view(itask))


@router.get("/tasks/{task_id}/result")
async def integration_result(
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """抽取结果 JSON（任务完成后可查）。"""
    await _superuser_ctx(db)
    data = await integration_service.get_result(db, task_id)
    return success(data=data)


@router.post("/tasks/{task_id}/retrigger")
async def integration_retrigger(
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """整流程重触发：重新 OCR 解析 → 索引 → 结构化抽取。"""
    await _superuser_ctx(db)
    itask = await integration_service.retrigger(db, task_id)
    return success(data=integration_service.to_view(itask), message="任务已重新触发")
