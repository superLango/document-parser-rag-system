"""任务管理端点模块。

本模块定义异步解析任务的接口，包括：

- ``POST /tasks/``：提交文档解析任务到 Celery 队列
- ``GET /tasks/{task_id}``：查询任务状态
- ``GET /tasks/{task_id}/stream``：SSE 流式推送任务进度
- ``GET /tasks/``：分页查询任务列表

任务状态来源结合数据库 Task 记录与 Celery AsyncResult 实时状态，
SSE 端点通过 StreamingResponse 每 0.5 秒轮询 Celery 进度并推送给客户端。
"""

import asyncio
import json
from uuid import UUID

from celery.result import AsyncResult
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, get_pagination_params
from app.core.database import get_db
from app.core.exceptions import BusinessException, ErrorCode
from app.core.logging import get_logger
from app.core.response import paginated, success
from app.models.document import Document
from app.models.task import Task
from app.models.user import User
from app.schemas.task import TaskResponse
from app.tasks.celery_app import celery_app
from app.tasks.document_tasks import parse_document

logger = get_logger(__name__)

router = APIRouter(prefix="/tasks", tags=["任务管理"])

# Celery 状态到业务状态的映射
_STATE_MAPPING: dict[str, str] = {
    "PENDING": "pending",
    "STARTED": "started",
    "PROGRESS": "progress",
    "SUCCESS": "success",
    "FAILURE": "failed",
    "RETRY": "pending",
}


class TaskCreateRequest(BaseModel):
    """任务提交请求模型。

    Attributes:
        document_id: 待解析文档的唯一标识。
        schema_id: 解析模式/模板标识，可选。
        term_base_id: 术语库标识，可选。
    """

    document_id: UUID
    schema_id: str | None = None
    term_base_id: str | None = None


@router.post("/")
async def submit_task(
    payload: TaskCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """提交文档解析任务。

    处理流程：
        1. 验证指定文档存在。
        2. 调用 ``parse_document.delay`` 将任务投递到 Celery 队列。
        3. 在数据库中创建任务记录，记录 Celery task id。
        4. 返回任务标识与初始状态。

    Args:
        payload: 任务提交请求体，包含 document_id 与可选参数。
        db: 异步数据库会话。
        current_user: 当前已认证用户。

    Returns:
        dict: 包含 ``task_id`` 与 ``status`` 的统一成功响应。

    Raises:
        BusinessException: 文档不存在时抛出 ``BUSINESS_DOCUMENT_NOT_FOUND``。
    """
    # 验证文档存在
    stmt = select(Document).where(Document.id == payload.document_id)
    result = await db.execute(stmt)
    document = result.scalar_one_or_none()

    if document is None:
        logger.warning("文档不存在", document_id=str(payload.document_id))
        raise BusinessException(
            code=ErrorCode.BUSINESS_DOCUMENT_NOT_FOUND,
            message=f"文档 {payload.document_id} 不存在",
        )

    # 提交 Celery 任务
    async_result = parse_document.delay(
        str(payload.document_id),
        payload.schema_id,
        payload.term_base_id,
    )

    # 创建任务记录
    task = Task(
        id=async_result.id,
        document_id=payload.document_id,
        status="pending",
        progress=0,
    )
    db.add(task)
    await db.commit()

    logger.info(
        "任务已提交",
        task_id=async_result.id,
        document_id=str(payload.document_id),
        schema_id=payload.schema_id,
        term_base_id=payload.term_base_id,
    )
    return success(data={"task_id": task.id, "status": "pending"})


@router.get("/{task_id}")
async def get_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """查询任务状态。

    同时查询数据库 Task 记录与 Celery AsyncResult 实时状态，
    以 Celery 状态为优先来源，确保返回最新进度。

    Args:
        task_id: Celery 任务唯一标识。
        db: 异步数据库会话。
        current_user: 当前已认证用户。

    Returns:
        dict: 包含任务详情的统一成功响应。

    Raises:
        BusinessException: 任务不存在时抛出 ``BUSINESS_TASK_NOT_FOUND``。
    """
    # 查询数据库
    stmt = select(Task).where(Task.id == task_id)
    result = await db.execute(stmt)
    task = result.scalar_one_or_none()

    if task is None:
        logger.warning("任务不存在", task_id=task_id)
        raise BusinessException(
            code=ErrorCode.BUSINESS_TASK_NOT_FOUND,
            message=f"任务 {task_id} 不存在",
        )

    # 查询 Celery 实时状态
    async_result = AsyncResult(task_id, app=celery_app)
    celery_state: str = async_result.state
    current_status: str = _STATE_MAPPING.get(celery_state, task.status)

    # 若 Celery 处于 PROGRESS 状态，从其 meta 中提取进度
    progress: int = task.progress
    if celery_state == "PROGRESS" and isinstance(async_result.info, dict):
        progress = async_result.info.get("progress", task.progress)

    # 构建 TaskResponse
    task_response = TaskResponse(
        id=task.id,
        document_id=task.document_id,
        status=current_status,
        progress=progress,
        result=task.result,
        error_message=task.error_message,
        created_at=task.created_at,
        completed_at=task.completed_at,
    )

    return success(data=task_response.model_dump())


@router.get("/{task_id}/stream")
async def stream_task_progress(
    task_id: str,
    current_user: User = Depends(get_current_active_user),
) -> StreamingResponse:
    """SSE 流式推送任务进度。

    通过 Server-Sent Events 协议向客户端实时推送任务进度。
    每 0.5 秒轮询一次 Celery AsyncResult，根据任务状态推送不同事件：

    - ``PROGRESS``：推送进度数据（进度百分比与消息）
    - ``SUCCESS``：推送最终结果并关闭流
    - ``FAILURE``：推送错误信息并关闭流
    - ``PENDING``/``STARTED`` 等：推送等待/处理中状态

    事件格式遵循 API 契约第 6 节的 SSE 规范：
        ``data: {"event":"progress","percent":50,"message":"解析中"}\\n\\n``

    Args:
        task_id: Celery 任务唯一标识。
        current_user: 当前已认证用户。

    Returns:
        StreamingResponse: ``text/event-stream`` 类型的流式响应。
    """

    async def event_generator():
        """SSE 事件生成器。

        持续轮询 Celery 任务状态，直到任务成功或失败后终止。
        """
        async_result = AsyncResult(task_id, app=celery_app)

        while True:
            state: str = async_result.state

            if state == "PROGRESS":
                # 进度更新：从 Celery meta 中提取进度信息
                info = async_result.info if isinstance(async_result.info, dict) else {}
                payload: dict = {
                    "event": "progress",
                    "state": state,
                    "progress": info.get("progress", 0),
                    "message": info.get("message", "解析中"),
                }
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

            elif state == "SUCCESS":
                # 任务成功：推送结果并终止
                payload = {
                    "event": "done",
                    "state": state,
                    "result": async_result.result,
                }
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                break

            elif state == "FAILURE":
                # 任务失败：推送错误并终止
                payload = {
                    "event": "error",
                    "state": state,
                    "error": str(async_result.result),
                }
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                break

            else:
                # PENDING / STARTED / RETRY 等中间状态
                payload = {
                    "event": "progress",
                    "state": state,
                    "progress": 0,
                    "message": "等待中" if state == "PENDING" else "处理中",
                }
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

            # 每 0.5 秒轮询一次
            await asyncio.sleep(0.5)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 禁用 Nginx 缓冲，确保实时推送
            "Access-Control-Allow-Origin": "*",  # SSE CORS 头
            "Access-Control-Allow-Headers": "*",
            "Access-Control-Allow-Methods": "GET",
        },
    )


@router.get("/")
async def list_tasks(
    pagination: dict = Depends(get_pagination_params),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """分页查询任务列表。

    按创建时间降序返回任务记录。

    Args:
        pagination: 分页参数字典，包含 ``page`` 与 ``page_size``。
        db: 异步数据库会话。
        current_user: 当前已认证用户。

    Returns:
        dict: 包含分页任务列表的统一成功响应。
    """
    page: int = pagination["page"]
    page_size: int = pagination["page_size"]

    # 查询总数
    count_stmt = select(func.count()).select_from(Task)
    total_result = await db.execute(count_stmt)
    total: int = total_result.scalar_one()

    # 查询当前页数据（按创建时间降序）
    offset: int = (page - 1) * page_size
    list_stmt = (
        select(Task)
        .order_by(Task.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    result = await db.execute(list_stmt)
    tasks = result.scalars().all()

    items: list[dict] = [
        TaskResponse.model_validate(task).model_dump() for task in tasks
    ]
    return paginated(items, total, page, page_size)
