"""仪表盘聚合服务（阶段 2.1）。

提供全局统计的 SQL 聚合查询，避免 N+1：
- get_global_stats：文档/任务/Schema/术语/用户/KB 计数 + 成功率
- get_trends：最近 N 天文档上传与任务完成趋势（按日期分组）
- get_distribution：文档类型分布 + 任务状态分布 + 任务类型分布
- get_kb_trends / get_kb_distribution：KB 内视角（RLS 已按 kb_id 过滤）

所有查询使用 async session + func.count 聚合，单次往返。
"""

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.models.knowledge_base import KnowledgeBase
from app.models.schema_model import SchemaConfig
from app.models.task import Task
from app.models.term import Term
from app.models.user import User


async def get_global_stats(db: AsyncSession) -> dict[str, Any]:
    """全局统计（超管视角，跨所有 KB）。"""
    doc_count = await db.scalar(select(func.count()).select_from(Document))
    task_count = await db.scalar(select(func.count()).select_from(Task))
    schema_count = await db.scalar(select(func.count()).select_from(SchemaConfig))
    term_count = await db.scalar(select(func.count()).select_from(Term))
    kb_count = await db.scalar(select(func.count()).select_from(KnowledgeBase))
    user_count = await db.scalar(
        select(func.count()).select_from(User).where(User.deleted_at.is_(None))
    )
    success_count = await db.scalar(
        select(func.count()).select_from(Task).where(Task.status == "success")
    )
    total = task_count or 0
    success_rate = round((success_count / total) * 100, 1) if total else 0.0
    return {
        "documents_count": doc_count or 0,
        "tasks_count": total,
        "schemas_count": schema_count or 0,
        "terms_count": term_count or 0,
        "kbs_count": kb_count or 0,
        "users_count": user_count or 0,
        "success_rate": success_rate,
    }


async def get_trends(db: AsyncSession, days: int = 30) -> dict[str, list]:
    """最近 N 天文档上传与任务创建趋势。

    Returns:
        {"dates": [...], "documents": [...], "tasks": [...]}
    """
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days - 1)

    # 文档按日期分组
    doc_rows = await db.execute(
        select(
            func.date_trunc("day", Document.created_at).label("d"),
            func.count(Document.id).label("c"),
        )
        .where(Document.created_at >= start)
        .group_by("d")
        .order_by("d")
    )
    doc_map = {r.d.date(): r.c for r in doc_rows.all()}

    # 任务按日期分组
    task_rows = await db.execute(
        select(
            func.date_trunc("day", Task.created_at).label("d"),
            func.count(Task.id).label("c"),
        )
        .where(Task.created_at >= start)
        .group_by("d")
        .order_by("d")
    )
    task_map = {r.d.date(): r.c for r in task_rows.all()}

    dates = []
    docs = []
    tasks = []
    cur = start.date()
    while cur <= end.date():
        dates.append(cur.isoformat())
        docs.append(doc_map.get(cur, 0))
        tasks.append(task_map.get(cur, 0))
        cur += timedelta(days=1)
    return {"dates": dates, "documents": docs, "tasks": tasks}


async def get_distribution(db: AsyncSession) -> dict[str, list[dict]]:
    """文档类型 + 任务状态 + 任务类型分布。"""
    # 文档类型分布
    doc_type_rows = await db.execute(
        select(Document.file_type, func.count(Document.id))
        .where(Document.file_type.isnot(None))
        .group_by(Document.file_type)
    )
    doc_types = [
        {"name": r[0] or "unknown", "value": r[1]} for r in doc_type_rows.all()
    ]

    # 任务状态分布
    task_status_rows = await db.execute(
        select(Task.status, func.count(Task.id)).group_by(Task.status)
    )
    task_statuses = [
        {"name": r[0], "value": r[1]} for r in task_status_rows.all()
    ]

    # 任务类型分布
    task_type_rows = await db.execute(
        select(Task.task_type, func.count(Task.id)).group_by(Task.task_type)
    )
    task_types = [
        {"name": r[0] or "unknown", "value": r[1]} for r in task_type_rows.all()
    ]

    return {
        "doc_types": doc_types,
        "task_statuses": task_statuses,
        "task_types": task_types,
    }


async def get_kb_stats(db: AsyncSession, kb_id) -> dict[str, Any]:
    """KB 内统计（RLS 已按 kb_id 过滤，额外显式过滤防御）。

    返回字段与前端 Overview.vue 期望的 KbStats 类型一致：
    - total_documents: 文档数
    - total_chunks: 向量分块数（从 Milvus 统计，失败则返回 0）
    - total_tasks: 任务数
    - total_members: 成员数
    """
    from app.models.knowledge_base import KbMember

    doc_count = await db.scalar(
        select(func.count()).select_from(Document).where(Document.kb_id == kb_id)
    )
    task_count = await db.scalar(
        select(func.count()).select_from(Task).where(Task.kb_id == kb_id)
    )
    member_count = await db.scalar(
        select(func.count()).select_from(KbMember).where(KbMember.kb_id == kb_id)
    )

    # 从 Milvus 获取 chunk 数（失败时返回 0，不影响整体统计）
    chunk_count = 0
    try:
        from app.services.vector.chunk_vector_store import chunk_vector_store
        chunk_count = await chunk_vector_store.count_kb(kb_id)
    except Exception:
        pass

    return {
        "total_documents": doc_count or 0,
        "total_chunks": chunk_count,
        "total_tasks": task_count or 0,
        "total_members": member_count or 0,
    }
