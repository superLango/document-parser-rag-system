"""任务 Schema 模块。

定义异步任务（Celery）相关的响应模型。
任务用于跟踪文档解析、知识库构建等异步流程的进度。
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class TaskResponse(BaseModel):
    """任务详情响应模型。

    Attributes:
        id: 任务唯一标识（Celery task id）。
        document_id: 关联文档 ID，可为空。
        status: 任务状态（pending/running/success/failed）。
        progress: 任务进度（0-100）。
        result: 任务结果数据，可为空。
        error_message: 错误信息，失败时填充。
        created_at: 创建时间。
        completed_at: 完成时间，可为空。
    """

    id: str
    document_id: UUID | None = None
    status: str
    progress: int
    result: dict | None = None
    error_message: str | None = None
    created_at: datetime
    completed_at: datetime | None = None


class TaskListResponse(BaseModel):
    """任务列表分页响应。

    遵循统一分页结构：{"items": [...], "total": 100, "page": 1, "page_size": 20}

    Attributes:
        items: 任务响应列表。
        total: 总记录数。
        page: 当前页码。
        page_size: 每页条数。
    """

    items: list[TaskResponse]
    total: int
    page: int
    page_size: int


class TaskSubmitResponse(BaseModel):
    """任务提交响应模型。

    任务提交后立即返回，客户端可据此轮询或订阅 SSE 获取进度。

    Attributes:
        task_id: 任务唯一标识。
        status: 初始状态，默认 "pending"。
    """

    task_id: str
    status: str = "pending"
