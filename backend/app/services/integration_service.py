"""系统对接服务：上传→OCR→结构化抽取 一站式（task_id 统一追踪）。

- 无认证对接端点（先走通业务流程）：内部使用 superuser 会话 + 显式 kb_id；
- create_task：校验 prompt → 建对接任务 → 上传对象存储 → 建文档 → 触发解析；
- get_status / get_result / retrigger：状态聚合、结果读取、整流程重触发。
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessException, ErrorCode
from app.models.extraction import PromptTemplate, SchemaTemplate
from app.models.integration_task import IntegrationTask
from app.services import document_service, storage


def _now_dt():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)


async def _get_prompt_schema(db: AsyncSession, kb_id, prompt_id) -> str:
    """校验 prompt 属于该 KB，返回其绑定的 schema_template_id。"""
    prompt = (
        await db.execute(
            select(PromptTemplate).where(
                PromptTemplate.id == prompt_id,
                PromptTemplate.kb_id == kb_id,
                PromptTemplate.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if prompt is None or prompt.schema_template_id is None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_NOT_FOUND,
            message="Prompt 不存在或未绑定 Schema 模板",
        )
    tpl = (
        await db.execute(
            select(SchemaTemplate).where(
                SchemaTemplate.id == prompt.schema_template_id,
                SchemaTemplate.kb_id == kb_id,
                SchemaTemplate.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if tpl is None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_NOT_FOUND,
            message="Prompt 绑定的 Schema 模板不存在或未启用",
        )
    return str(prompt.schema_template_id)


async def create_task(
    db: AsyncSession,
    *,
    kb_id,
    prompt_id,
    filename: str,
    file_size: int,
    data: bytes,
) -> IntegrationTask:
    """一站式上传：建对接任务 → 上传对象存储 → 建文档 → 触发解析。"""
    schema_template_id = await _get_prompt_schema(db, kb_id, prompt_id)
    task_id = uuid.uuid4()
    object_key = await storage.put_original(kb_id, str(task_id), filename, data)
    try:
        document, _parse_task = await document_service.create_document(
            db,
            kb_id,
            filename=filename,
            file_type="pdf",
            file_size=file_size,
            sha256=__import__("hashlib").sha256(data).hexdigest(),
            object_key=object_key,
        )
        itask = IntegrationTask(
            task_id=task_id,
            kb_id=kb_id,
            document_id=document.id,
            prompt_id=prompt_id,
            schema_template_id=uuid.UUID(schema_template_id),
            filename=filename,
            ocr_status="processing",
            ocr_progress=0,
            extract_status="pending",
            extract_progress=0,
            error="",
        )
        db.add(itask)
        await db.flush()
        # 触发解析（写 outbox，arq 消费）
        await document_service.start_document_parse(db, kb_id, document.id)
        await db.commit()
        await db.refresh(itask)
        return itask
    except Exception:
        await db.rollback()
        try:
            await storage.delete_document_objects(kb_id, object_key)
        except Exception:  # noqa: BLE001, S110 - 清理失败不影响主错误
            pass
        raise


async def get_task(db: AsyncSession, task_id) -> IntegrationTask:
    itask = (
        await db.execute(
            select(IntegrationTask).where(IntegrationTask.task_id == task_id)
        )
    ).scalar_one_or_none()
    if itask is None:
        raise BusinessException(code=ErrorCode.BUSINESS_NOT_FOUND, message="对接任务不存在")
    return itask


def to_view(itask: IntegrationTask) -> dict:
    return {
        "task_id": str(itask.task_id),
        "kb_id": str(itask.kb_id),
        "document_id": str(itask.document_id) if itask.document_id else None,
        "prompt_id": str(itask.prompt_id) if itask.prompt_id else None,
        "schema_template_id": str(itask.schema_template_id) if itask.schema_template_id else None,
        "filename": itask.filename,
        "ocr_status": itask.ocr_status,
        "ocr_progress": itask.ocr_progress,
        "extract_status": itask.extract_status,
        "extract_progress": itask.extract_progress,
        "error": itask.error,
        "result_version": itask.result_version,
        "created_at": itask.created_at.isoformat() if itask.created_at else None,
        "updated_at": itask.updated_at.isoformat() if itask.updated_at else None,
    }


async def get_result(db: AsyncSession, task_id) -> dict | None:
    """返回对接任务对应文档的最新抽取结果（格式对齐 /extraction/result）。"""
    itask = await get_task(db, task_id)
    if itask.document_id is None:
        return None
    from app.services.extraction import result_store

    row = await result_store.get_latest(db, itask.kb_id, itask.document_id)
    if row is None:
        return None
    return {
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
    }


async def retrigger(db: AsyncSession, task_id) -> IntegrationTask:
    """整流程重触发：重置状态 → 重新解析（会重新 OCR → 索引 → 抽取）。"""
    itask = await get_task(db, task_id)
    if itask.document_id is None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_INVALID_STATE, message="任务无关联文档，无法重触发"
        )
    itask.ocr_status = "processing"
    itask.ocr_progress = 0
    itask.extract_status = "pending"
    itask.extract_progress = 0
    itask.error = ""
    itask.result_version = None
    itask.updated_at = _now_dt()
    await db.flush()
    await document_service.start_document_parse(db, itask.kb_id, itask.document_id)
    await db.commit()
    await db.refresh(itask)
    return itask


async def issue_session_token(db: AsyncSession, task_id):
    """签发对接任务匿名会话令牌(免登录编辑结果页)。

    校验任务存在后, 以系统超管身份签发短期 JWT; 仅允许携带该任务上下文使用
    (payload 内嵌 task_id/document_id/kb_id 供审计; 前端在打开结果页前调用)。
    """
    itask = await get_task(db, task_id)
    from app.core.security import create_access_token
    from datetime import timedelta

    token = create_access_token(
        data={"sub": "admin", "ctx": "integration_task", "task_id": str(itask.task_id),
              "document_id": str(itask.document_id) if itask.document_id else None,
              "kb_id": str(itask.kb_id)},
        expires_delta=timedelta(hours=2),
    )
    return {"task_id": str(itask.task_id), "token": token,
            "document_id": str(itask.document_id) if itask.document_id else None,
            "kb_id": str(itask.kb_id)}
