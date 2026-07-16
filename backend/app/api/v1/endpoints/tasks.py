"""任务管理端点模块。

本模块定义异步解析任务的接口，包括：

- ``POST /tasks/``：提交文档解析任务到 arq 队列
- ``GET /tasks/{task_id}``：查询任务状态
- ``POST /tasks/{task_id}/retry``：重试文档解析任务
- ``GET /tasks/{task_id}/stream``：SSE 流式推送任务进度
- ``GET /tasks/``：分页查询任务列表

任务状态来源为数据库 Task 记录，arq 通过 job_id 与 Task 记录关联。
SSE 端点通过 StreamingResponse 每 0.5 秒轮询数据库 Task 进度并推送给客户端。
"""

import asyncio
import json
from uuid import UUID

from arq import create_pool
from arq.connections import RedisSettings
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

logger = get_logger(__name__)

router = APIRouter(prefix="/tasks", tags=["任务管理"])

# arq 连接池单例（懒加载）
_arq_pool = None


async def get_arq_pool():
    """获取 arq Redis 连接池单例。

    首次调用时创建连接池并缓存，后续直接返回单例。
    arq 使用 database=1 作为任务队列（与原 Celery broker 一致）。

    Returns:
        ArqRedis: arq Redis 连接池实例。
    """
    global _arq_pool
    if _arq_pool is None:
        _arq_pool = await create_pool(
            RedisSettings(host="localhost", port=6379, database=1)
        )
    return _arq_pool


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
        2. 通过 arq ``enqueue_job`` 将任务投递到 Redis 队列。
        3. 在数据库中创建任务记录，记录 arq job_id。
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

    # 提交 arq 任务
    pool = await get_arq_pool()
    job = await pool.enqueue_job(
        "parse_document_task",
        str(payload.document_id),
        payload.schema_id,
        payload.term_base_id,
    )

    if job is None:
        # 任务未入队（同名任务已存在且未完成）
        raise BusinessException(
            code=ErrorCode.BUSINESS_TASK_FAILED,
            message="任务提交失败，可能已有相同任务在执行中",
        )

    # 创建任务记录
    task = Task(
        id=job.job_id,
        document_id=payload.document_id,
        status="pending",
        progress=0,
    )
    db.add(task)
    await db.commit()

    logger.info(
        "任务已提交",
        task_id=job.job_id,
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

    直接返回数据库 Task 记录中的状态与进度。
    arq 任务进度由 Worker 写入数据库 Task 记录。

    Args:
        task_id: arq 任务唯一标识。
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

    # 构建 TaskResponse
    task_response = TaskResponse(
        id=task.id,
        document_id=task.document_id,
        status=task.status,
        progress=task.progress,
        result=task.result,
        error_message=task.error_message,
        created_at=task.created_at,
        completed_at=task.completed_at,
    )

    return success(data=task_response.model_dump())


@router.post("/{task_id}/retry")
async def retry_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """重试文档解析任务。

    处理流程：
        1. 根据 ``task_id`` 查询原任务记录。
        2. 从原任务获取 ``document_id``，并验证文档仍然存在。
        3. 通过 arq ``enqueue_job`` 重新投递解析任务到 Redis 队列。
           由于 Task 模型未存储 ``schema_id`` 与 ``term_base_id``，
           重试时这两个参数以 ``None`` 提交。
        4. 在数据库中创建新的任务记录，记录新的 arq job_id。
        5. 返回新任务标识与初始状态。

    Args:
        task_id: 原任务唯一标识。
        db: 异步数据库会话。
        current_user: 当前已认证用户。

    Returns:
        dict: 包含新任务 ``task_id`` 与 ``status`` 的统一成功响应。

    Raises:
        BusinessException: 原任务不存在时抛出 ``BUSINESS_TASK_NOT_FOUND``；
            文档不存在时抛出 ``BUSINESS_DOCUMENT_NOT_FOUND``；
            任务入队失败时抛出 ``BUSINESS_TASK_FAILED``。
    """
    # 查询原任务记录
    stmt = select(Task).where(Task.id == task_id)
    result = await db.execute(stmt)
    task = result.scalar_one_or_none()

    if task is None:
        logger.warning("任务不存在，无法重试", task_id=task_id)
        raise BusinessException(
            code=ErrorCode.BUSINESS_TASK_NOT_FOUND,
            message=f"任务 {task_id} 不存在",
        )

    document_id = task.document_id

    # 验证文档仍然存在
    doc_stmt = select(Document).where(Document.id == document_id)
    doc_result = await db.execute(doc_stmt)
    document = doc_result.scalar_one_or_none()

    if document is None:
        logger.warning("文档不存在，无法重试", document_id=str(document_id))
        raise BusinessException(
            code=ErrorCode.BUSINESS_DOCUMENT_NOT_FOUND,
            message=f"文档 {document_id} 不存在",
        )

    # 提交 arq 任务（schema_id 与 term_base_id 原任务未存储，传 None）
    pool = await get_arq_pool()
    job = await pool.enqueue_job(
        "parse_document_task",
        str(document_id),
        None,
        None,
    )

    if job is None:
        # 任务未入队（同名任务已存在且未完成）
        raise BusinessException(
            code=ErrorCode.BUSINESS_TASK_FAILED,
            message="任务重试失败，可能已有相同任务在执行中",
        )

    # 创建新的任务记录
    new_task = Task(
        id=job.job_id,
        document_id=document_id,
        status="pending",
        progress=0,
    )
    db.add(new_task)
    await db.commit()

    logger.info(
        "任务已重试提交",
        task_id=job.job_id,
        original_task_id=task_id,
        document_id=str(document_id),
    )
    return success(data={"task_id": new_task.id, "status": "pending"})


@router.get("/{task_id}/stream")
async def stream_task_progress(
    task_id: str,
    current_user: User = Depends(get_current_active_user),
) -> StreamingResponse:
    """SSE 流式推送任务进度。

    通过 Server-Sent Events 协议向客户端实时推送任务进度。
    每 0.5 秒轮询一次数据库 Task 记录，根据任务状态推送不同事件：

    - ``progress``：推送进度数据（进度百分比与状态）
    - ``done``：推送最终结果并关闭流
    - ``error``：推送错误信息并关闭流

    事件格式遵循 API 契约第 6 节的 SSE 规范：
        ``data: {"event":"progress","progress":50,"message":"解析中"}\\n\\n``

    Args:
        task_id: arq 任务唯一标识。
        current_user: 当前已认证用户。

    Returns:
        StreamingResponse: ``text/event-stream`` 类型的流式响应。
    """
    # 延迟导入，避免循环依赖
    from app.core.database import AsyncSessionLocal

    async def event_generator():
        """SSE 事件生成器。

        持续轮询数据库 Task 记录，直到任务成功或失败后终止。
        """
        while True:
            # 从数据库查询任务状态
            async with AsyncSessionLocal() as db:
                stmt = select(Task).where(Task.id == task_id)
                result = await db.execute(stmt)
                task = result.scalar_one_or_none()

            if task is None:
                # 任务不存在，推送错误并终止
                payload: dict = {
                    "event": "error",
                    "state": "FAILURE",
                    "error": f"任务 {task_id} 不存在",
                }
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                break

            status: str = task.status
            progress: int = task.progress

            if status in ("success", "completed"):
                # 任务成功：推送结果并终止
                payload = {
                    "event": "done",
                    "state": "SUCCESS",
                    "progress": 100,
                    "result": task.result,
                }
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                break

            elif status == "failed":
                # 任务失败：推送错误并终止
                payload = {
                    "event": "error",
                    "state": "FAILURE",
                    "error": task.error_message or "任务执行失败",
                }
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                break

            elif status == "progress":
                # 进度更新
                payload = {
                    "event": "progress",
                    "state": "PROGRESS",
                    "progress": progress,
                    "message": "处理中",
                }
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

            else:
                # pending / started 等中间状态
                payload = {
                    "event": "progress",
                    "state": status.upper() if status else "PENDING",
                    "progress": progress,
                    "message": "等待中" if status == "pending" else "处理中",
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
