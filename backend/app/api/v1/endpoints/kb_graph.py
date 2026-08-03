"""知识库内知识图谱端点（阶段 1.5）。

提供 KB 隔离的图谱查询与管理接口，所有端点强制
``Depends(get_kb_context)``，并将 ``kb_ctx.kb_id`` 透传给
``graph_store``（已支持按 kb_id 路由到专属 graph space）。

端点（前缀 ``/kbs/{kb_id}/graph``）：
- GET    /                       全局图谱（限制节点数）（任意成员）
- GET    /search                 搜索节点（任意成员）
- GET    /subgraph               实体周边子图（任意成员）
- GET    /stats                  图统计信息（任意成员）
- POST   /documents/{document_id} 触发文档图谱构建（editor+）
- POST   /rebuild                重建 KB 全部图谱（admin+）
- DELETE /documents/{document_id} 删除文档图谱数据（editor+）

与旧 ``knowledge_graph.py``（全局，向后兼容）共存。
"""

import uuid

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import KBContext, get_kb_context, require_role
from app.core.database import get_db
from app.core.exceptions import BusinessException, ErrorCode
from app.core.logging import get_logger
from app.core.response import success
from app.models.document import Document
from app.models.knowledge_base import EDIT_ROLES, MANAGE_ROLES
from app.services.graph.graph_store import graph_store

logger = get_logger(__name__)

router = APIRouter(prefix="/kbs/{kb_id}/graph", tags=["知识库-知识图谱"])

# arq 连接池单例（懒加载，与 knowledge_graph.py 独立但指向同一 Redis）
_arq_pool = None


async def _get_arq_pool():
    """获取 arq Redis 连接池单例。"""
    global _arq_pool
    if _arq_pool is None:
        _arq_pool = await create_pool(
            RedisSettings(host="localhost", port=6379, database=1)
        )
    return _arq_pool


@router.get("")
async def get_graph(
    limit: int = Query(50, ge=1, le=500, description="最大返回节点数"),
    kb_ctx: KBContext = Depends(get_kb_context),
) -> dict:
    """获取 KB 全局知识图谱（限制节点数）。

    透传 kb_id 给 graph_store，路由到 KB 专属 graph space。
    NebulaGraph 不可用时返回空图谱（优雅降级）。
    """
    graph_data = await graph_store.get_graph(limit=limit, kb_id=kb_ctx.kb_id)
    return success(data=graph_data)


@router.get("/search")
async def search_nodes(
    kb_ctx: KBContext = Depends(get_kb_context),
    label: str | None = Query(None, description="节点标签过滤"),
    name: str | None = Query(None, description="节点名称模糊匹配关键词"),
    limit: int = Query(50, ge=1, le=500, description="返回最大数量"),
) -> dict:
    """搜索 KB 图节点（透传 kb_id 到 KB 专属 space）。"""
    nodes = await graph_store.search_nodes(
        label=label, name=name, limit=limit, kb_id=kb_ctx.kb_id
    )
    return success(data={"nodes": nodes, "edges": [], "total": len(nodes)})


@router.get("/subgraph")
async def get_subgraph(
    entity: str = Query(..., description="中心实体名称"),
    max_hops: int = Query(2, ge=1, le=5, description="最大跳数，1-5"),
    kb_ctx: KBContext = Depends(get_kb_context),
) -> dict:
    """获取实体周边子图（透传 kb_id 到 KB 专属 space）。"""
    subgraph = await graph_store.get_subgraph(entity, max_hops=max_hops, kb_id=kb_ctx.kb_id)
    return success(data=subgraph)


@router.get("/stats")
async def graph_stats(
    kb_ctx: KBContext = Depends(get_kb_context),
) -> dict:
    """图统计信息（透传 kb_id 到 KB 专属 space）。

    返回节点总数、关系总数、节点标签列表。
    NebulaGraph 不可用时返回零值（优雅降级）。
    """
    stats = await graph_store.get_stats(kb_id=kb_ctx.kb_id)
    return success(data=stats)


@router.post("/documents/{document_id}")
async def build_graph(
    document_id: uuid.UUID,
    kb_ctx: KBContext = Depends(require_role(*EDIT_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """触发文档知识图谱构建（editor+，异步任务）。

    校验文档存在且属于当前 KB（RLS 已过滤，额外防御性校验 kb_id），
    且文档已完成解析（parsed_text 非空）。
    """
    document = await db.get(Document, document_id)
    if document is None or document.kb_id != kb_ctx.kb_id:
        raise BusinessException(
            code=ErrorCode.BUSINESS_DOCUMENT_NOT_FOUND,
            message=f"文档 {document_id} 不存在",
        )
    if not document.parsed_text:
        raise BusinessException(
            code=ErrorCode.BUSINESS_TASK_FAILED,
            message="文档尚未解析完成，无法构建图谱",
        )

    pool = await _get_arq_pool()
    job = await pool.enqueue_job(
        "build_document_graph_task",
        str(document_id),
        str(kb_ctx.kb_id),
    )
    if job is None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_TASK_FAILED,
            message="任务提交失败，可能已有相同任务在执行中",
        )
    logger.info(
        "KB 文档图谱构建任务已提交",
        kb_id=str(kb_ctx.kb_id),
        document_id=str(document_id),
        task_id=job.job_id,
    )
    return success(data={"task_id": job.job_id, "status": "pending"})


@router.post("/rebuild")
async def rebuild_graph(
    kb_ctx: KBContext = Depends(require_role(*MANAGE_ROLES)),
) -> dict:
    """重建 KB 全部文档的知识图谱（admin+，异步任务）。

    透传 kb_id 给 worker，仅重建当前 KB 的图谱。
    """
    pool = await _get_arq_pool()
    job = await pool.enqueue_job("rebuild_all_graphs_task", str(kb_ctx.kb_id))
    if job is None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_TASK_FAILED,
            message="任务提交失败，可能已有相同任务在执行中",
        )
    logger.info(
        "KB 图谱重建任务已提交",
        kb_id=str(kb_ctx.kb_id),
        task_id=job.job_id,
    )
    return success(data={"task_id": job.job_id, "status": "pending"})


@router.delete("/documents/{document_id}")
async def remove_graph(
    document_id: uuid.UUID,
    kb_ctx: KBContext = Depends(require_role(*EDIT_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """删除文档的图谱数据（editor+，异步任务）。

    仅清理图谱节点与边，不删除文档本身。透传 kb_id 确保仅操作当前 KB space。
    """
    document = await db.get(Document, document_id)
    if document is None or document.kb_id != kb_ctx.kb_id:
        raise BusinessException(
            code=ErrorCode.BUSINESS_DOCUMENT_NOT_FOUND,
            message=f"文档 {document_id} 不存在",
        )
    pool = await _get_arq_pool()
    job = await pool.enqueue_job(
        "remove_document_graph_task",
        str(document_id),
        str(kb_ctx.kb_id),
    )
    if job is None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_TASK_FAILED,
            message="任务提交失败",
        )
    return success(data={"task_id": job.job_id, "status": "pending"})
