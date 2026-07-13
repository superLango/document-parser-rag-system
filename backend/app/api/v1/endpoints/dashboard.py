"""仪表盘统计端点模块。

提供系统概览统计数据，包括文档数、任务数、Schema 数、术语数与成功率。
"""

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user
from app.core.database import get_db
from app.core.response import success
from app.models.document import Document
from app.models.schema_model import SchemaConfig
from app.models.task import Task
from app.models.term import Term
from app.models.user import User

router = APIRouter(prefix="/dashboard", tags=["仪表盘"])


@router.get("/stats")
async def get_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """获取仪表盘统计数据。

    Returns:
        dict: 包含各类计数与最近活动列表的统一成功响应。
    """
    # 文档总数
    doc_count = await db.scalar(select(func.count()).select_from(Document))
    # 任务总数
    task_count = await db.scalar(select(func.count()).select_from(Task))
    # Schema 总数
    schema_count = await db.scalar(select(func.count()).select_from(SchemaConfig))
    # 术语总数
    term_count = await db.scalar(select(func.count()).select_from(Term))

    # 成功率
    success_count = await db.scalar(
        select(func.count()).select_from(Task).where(Task.status == "success")
    )
    total_tasks = task_count or 0
    success_rate = round((success_count / total_tasks) * 100, 1) if total_tasks > 0 else 0.0

    # 最近文档（5 条）
    recent_docs_stmt = (
        select(Document)
        .order_by(Document.created_at.desc())
        .limit(5)
    )
    recent_docs_result = await db.execute(recent_docs_stmt)
    recent_documents = [
        {
            "id": str(doc.id),
            "title": doc.filename,
            "file_name": doc.filename,
            "file_size": doc.file_size,
            "doc_type": doc.file_type,
            "status": doc.status,
            "uploaded_at": doc.created_at.isoformat() if doc.created_at else "",
        }
        for doc in recent_docs_result.scalars().all()
    ]

    # 最近任务（5 条）
    recent_tasks_stmt = (
        select(Task)
        .order_by(Task.created_at.desc())
        .limit(5)
    )
    recent_tasks_result = await db.execute(recent_tasks_stmt)
    recent_tasks = [
        {
            "id": str(task.id),
            "document_id": str(task.document_id),
            "status": task.status,
            "progress": task.progress,
            "started_at": task.created_at.isoformat() if task.created_at else None,
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        }
        for task in recent_tasks_result.scalars().all()
    ]

    return success(data={
        "documents_count": doc_count or 0,
        "tasks_count": task_count or 0,
        "schemas_count": schema_count or 0,
        "terms_count": term_count or 0,
        "success_rate": success_rate,
        "recent_documents": recent_documents,
        "recent_tasks": recent_tasks,
    })
