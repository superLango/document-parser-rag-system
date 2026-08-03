"""知识图谱管理端点模块。

本模块定义知识图谱的管理接口，包括：

- ``POST /kg/documents/{doc_id}/graph``：触发文档知识图谱构建（异步任务）
- ``POST /kg/rebuild``：重建所有文档的知识图谱
- ``DELETE /kg/documents/{doc_id}``：删除文档的知识图谱数据
- ``GET /kg/search``：搜索图节点（按标签或名称）
- ``GET /kg/subgraph``：获取实体周边子图（N 跳邻居）
- ``GET /kg/stats``：图统计信息（节点/关系/标签）

POST 端点通过 arq 异步任务执行图谱构建，返回 ``task_id`` 供前端轮询进度。
所有接口均需 Bearer Token 鉴权，统一响应体由 ``app.core.response`` 构造。
"""

import uuid

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user
from app.core.database import get_db
from app.core.exceptions import BusinessException, ErrorCode
from app.core.logging import get_logger
from app.core.response import success
from app.models.document import Document
from app.models.user import User
from app.services.graph.graph_store import graph_store

logger = get_logger(__name__)

router = APIRouter(prefix="/kg", tags=["知识图谱管理"])

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


@router.post("/documents/{doc_id}/graph")
async def build_graph_endpoint(
    doc_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """触发文档知识图谱构建（异步任务）。

    处理流程：
        1. 验证文档存在且已完成解析。
        2. 通过 arq ``enqueue_job`` 投递图谱构建任务。
        3. 返回 task_id 供前端轮询进度。

    Args:
        doc_id: 文档唯一标识。
        db: 异步数据库会话。
        current_user: 当前已认证用户。

    Returns:
        dict: 包含 task_id 与 status 的统一成功响应。

    Raises:
        BusinessException: 文档不存在或未完成解析时抛出。
    """
    # 验证文档存在
    stmt = select(Document).where(Document.id == doc_id)
    result = await db.execute(stmt)
    document = result.scalar_one_or_none()

    if document is None:
        logger.warning("文档不存在", doc_id=str(doc_id))
        raise BusinessException(
            code=ErrorCode.BUSINESS_DOCUMENT_NOT_FOUND,
            message=f"文档 {doc_id} 不存在",
        )

    # 校验文档已解析完成
    if not document.parsed_text:
        raise BusinessException(
            code=ErrorCode.BUSINESS_TASK_FAILED,
            message="文档尚未解析完成，无法构建图谱",
        )

    # 提交 arq 任务
    pool = await get_arq_pool()
    job = await pool.enqueue_job("build_document_graph_task", str(doc_id))

    if job is None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_TASK_FAILED,
            message="任务提交失败，可能已有相同任务在执行中",
        )

    logger.info(
        "文档知识图谱构建任务已提交",
        doc_id=str(doc_id),
        task_id=job.job_id,
    )
    return success(data={"task_id": job.job_id, "status": "pending"})


@router.post("/rebuild")
async def rebuild_graph_endpoint(
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """重建所有文档的知识图谱。

    遍历所有已解析文档重新构建知识图谱。
    该操作为异步任务，返回 task_id 供前端追踪进度。

    Args:
        current_user: 当前已认证用户。

    Returns:
        dict: 包含 task_id 与 status 的统一成功响应。
    """
    # 提交 arq 任务
    pool = await get_arq_pool()
    job = await pool.enqueue_job("rebuild_all_graphs_task")

    if job is None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_TASK_FAILED,
            message="任务提交失败，可能已有相同任务在执行中",
        )

    logger.info(
        "知识图谱重建任务已提交",
        task_id=job.job_id,
    )
    return success(data={"task_id": job.job_id, "status": "pending"})


@router.delete("/documents/{doc_id}")
async def remove_graph_endpoint(
    doc_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """删除文档的知识图谱数据。

    提交异步任务从 Neo4j 删除指定文档的所有关联节点与关系。
    不删除 Document 数据库记录本身，仅清理图谱数据。

    Args:
        doc_id: 文档唯一标识。
        current_user: 当前已认证用户。

    Returns:
        dict: 包含 task_id 与 status 的统一成功响应。
    """
    # 提交 arq 任务
    pool = await get_arq_pool()
    job = await pool.enqueue_job("remove_document_graph_task", str(doc_id))

    if job is None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_TASK_FAILED,
            message="任务提交失败，可能已有相同任务在执行中",
        )

    logger.info(
        "文档图谱删除任务已提交",
        doc_id=str(doc_id),
        task_id=job.job_id,
    )
    return success(data={"task_id": job.job_id, "status": "pending"})


@router.get("/search")
async def search_nodes_endpoint(
    label: str | None = Query(None, description="节点标签过滤"),
    name: str | None = Query(None, description="节点名称模糊匹配关键词"),
    limit: int = Query(50, ge=1, le=500, description="返回最大数量"),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """搜索图节点。

    支持按标签过滤和按名称模糊检索，可组合使用。
    直接查询 Neo4j，返回匹配的节点列表与关联边。

    Args:
        label: 节点标签，为 None 时不按标签过滤。
        name: 名称模糊匹配关键词，为 None 时不按名称过滤。
        limit: 返回最大数量，默认 50，范围 1-500。
        current_user: 当前已认证用户。

    Returns:
        dict: 包含 nodes 和 edges 的统一成功响应。
    """
    logger.info("图节点搜索", label=label, name=name, limit=limit)

    nodes: list[dict] = await graph_store.search_nodes(
        label=label, name=name, limit=limit
    )

    logger.info("图节点搜索完成", result_count=len(nodes))
    return success(data={"nodes": nodes, "edges": [], "total": len(nodes)})


@router.get("/graph")
async def get_graph_endpoint(
    limit: int = Query(50, ge=1, le=500, description="最大返回节点数"),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """获取全局知识图谱（限制节点数）。

    查询全量节点（按 limit 截断）及其之间的关系，
    用于前端知识图谱页面的初始加载。

    Args:
        limit: 最大返回节点数，默认 50，范围 1-500。
        current_user: 当前已认证用户。

    Returns:
        dict: 包含 nodes 和 edges 的统一成功响应。
    """
    logger.info("全局图谱查询", limit=limit)

    graph_data: dict = await graph_store.get_graph(limit=limit)

    logger.info(
        "全局图谱查询完成",
        node_count=len(graph_data.get("nodes", [])),
        edge_count=len(graph_data.get("edges", [])),
    )
    return success(data=graph_data)


@router.get("/subgraph")
async def get_subgraph_endpoint(
    entity: str = Query(..., description="中心实体名称"),
    max_hops: int = Query(2, ge=1, le=5, description="最大跳数，1-5"),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """获取实体周边子图。

    以指定实体为中心，查询 N 跳范围内的全部节点与关系，
    用于前端知识图谱可视化展示。

    Args:
        entity: 中心实体名称。
        max_hops: 最大跳数，默认 2，范围 1-5。
        current_user: 当前已认证用户。

    Returns:
        dict: 包含子图数据（nodes 与 edges）的统一成功响应。
    """
    logger.info("子图查询", entity=entity, max_hops=max_hops)

    subgraph: dict = await graph_store.get_subgraph(entity, max_hops=max_hops)

    logger.info(
        "子图查询完成",
        entity=entity,
        node_count=len(subgraph.get("nodes", [])),
        edge_count=len(subgraph.get("edges", [])),
    )
    return success(data=subgraph)


@router.get("/stats")
async def graph_stats_endpoint(
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """图统计信息。

    返回知识图谱的整体统计：
    - total_nodes: 节点总数
    - total_relations: 关系总数
    - node_labels: 全部节点标签列表

    Args:
        current_user: 当前已认证用户。

    Returns:
        dict: 包含统计信息的统一成功响应。
    """
    stats: dict = await graph_store.get_stats()

    logger.info("图统计查询完成", stats=stats)
    return success(data=stats)
