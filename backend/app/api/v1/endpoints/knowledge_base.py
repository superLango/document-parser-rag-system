"""知识库管理端点模块。

本模块定义 RAG 知识库的管理接口，包括：

- ``POST /kb/documents/{doc_id}/index``：触发文档入知识库（异步任务）
- ``POST /kb/rebuild``：重建整个知识库索引
- ``DELETE /kb/documents/{doc_id}``：从知识库移除文档
- ``GET /kb/stats``：知识库统计信息
- ``GET /kb/search``：知识库搜索（测试用，不经过 LLM 生成）

POST 端点通过 arq 异步任务执行索引构建，返回 ``task_id`` 供前端轮询进度。
所有接口均需 Bearer Token 鉴权，统一响应体由 ``app.core.response`` 构造。
"""

import uuid

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user
from app.core.database import get_db
from app.core.exceptions import BusinessException, ErrorCode
from app.core.logging import get_logger
from app.core.response import success
from app.models.document import Document
from app.models.user import User
from app.services.embedding.embedding_service import embedding_service
from app.services.vector.chunk_vector_store import vector_store

logger = get_logger(__name__)

router = APIRouter(prefix="/kb", tags=["知识库管理"])

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


@router.post("/documents/{doc_id}/index")
async def index_document_endpoint(
    doc_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """触发文档入知识库（异步任务）。

    处理流程：
        1. 验证文档存在且已完成解析。
        2. 通过 arq ``enqueue_job`` 投递索引任务。
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
            message="文档尚未解析完成，无法索引",
        )

    # 提交 arq 任务
    pool = await get_arq_pool()
    job = await pool.enqueue_job("index_document_task", str(doc_id))

    if job is None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_TASK_FAILED,
            message="任务提交失败，可能已有相同任务在执行中",
        )

    logger.info(
        "文档索引任务已提交",
        doc_id=str(doc_id),
        task_id=job.job_id,
    )
    return success(data={"task_id": job.job_id, "status": "pending"})


@router.post("/rebuild")
async def rebuild_index_endpoint(
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """重建知识库索引。

    清空 Milvus 集合并对所有已解析文档重新索引。
    该操作为异步任务，返回 task_id 供前端追踪进度。

    Args:
        current_user: 当前已认证用户。

    Returns:
        dict: 包含 task_id 与 status 的统一成功响应。
    """
    # 提交 arq 任务
    pool = await get_arq_pool()
    job = await pool.enqueue_job("rebuild_index_task")

    if job is None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_TASK_FAILED,
            message="任务提交失败，可能已有相同任务在执行中",
        )

    logger.info(
        "知识库重建任务已提交",
        task_id=job.job_id,
    )
    return success(data={"task_id": job.job_id, "status": "pending"})


@router.delete("/documents/{doc_id}")
async def remove_from_kb_endpoint(
    doc_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """从知识库移除文档。

    提交异步任务从 Milvus 删除指定文档的所有分块。
    不删除 Document 数据库记录本身，仅清理向量索引。

    Args:
        doc_id: 文档唯一标识。
        db: 异步数据库会话。
        current_user: 当前已认证用户。

    Returns:
        dict: 包含 task_id 与 status 的统一成功响应。
    """
    # 提交 arq 任务
    pool = await get_arq_pool()
    job = await pool.enqueue_job("remove_document_task", str(doc_id))

    if job is None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_TASK_FAILED,
            message="任务提交失败，可能已有相同任务在执行中",
        )

    logger.info(
        "文档移除任务已提交",
        doc_id=str(doc_id),
        task_id=job.job_id,
    )
    return success(data={"task_id": job.job_id, "status": "pending"})


@router.get("/stats")
async def kb_stats_endpoint(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """知识库统计信息。

    返回知识库的整体统计：
    - total_chunks: Milvus 中的分块总数
    - total_docs: 数据库中的文档总数
    - indexed_docs: 已索引（status=indexed）的文档数
    - completed_docs: 已解析完成（status=completed）的文档数

    Args:
        db: 异步数据库会话。
        current_user: 当前已认证用户。

    Returns:
        dict: 包含统计信息的统一成功响应。
    """
    # 查询 Milvus 统计（分块总数）
    total_chunks: int = await vector_store.count()

    # 查询数据库统计
    total_docs_result = await db.execute(
        select(func.count()).select_from(Document)
    )
    total_docs: int = total_docs_result.scalar_one()

    indexed_docs_result = await db.execute(
        select(func.count())
        .select_from(Document)
        .where(Document.status == "indexed")
    )
    indexed_docs: int = indexed_docs_result.scalar_one()

    completed_docs_result = await db.execute(
        select(func.count())
        .select_from(Document)
        .where(Document.status == "completed")
    )
    completed_docs: int = completed_docs_result.scalar_one()

    data: dict = {
        "total_chunks": total_chunks,
        "total_docs": total_docs,
        "indexed_docs": indexed_docs,
        "completed_docs": completed_docs,
    }

    logger.info("知识库统计查询完成", data=data)
    return success(data=data)


@router.get("/search")
async def kb_search_endpoint(
    q: str = Query(..., description="查询文本"),
    top_k: int = Query(10, ge=1, le=100, description="返回结果数量"),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """知识库搜索（测试用，不经过 LLM 生成）。

    对查询文本进行嵌入后执行混合检索（Dense + Sparse），
    返回原始检索结果，便于调试检索质量。

    Args:
        q: 查询文本。
        top_k: 返回结果数量，默认 10，范围 1-100。
        current_user: 当前已认证用户。

    Returns:
        dict: 包含检索结果的统一成功响应。
    """
    logger.info("知识库搜索", query=q, top_k=top_k)

    # 嵌入查询文本
    embed_result: dict = await embedding_service.embed_query(q)
    query_dense = embed_result["dense_vector"]
    query_sparse = embed_result["sparse_for_milvus"]

    # 执行混合检索
    results: list[dict] = await vector_store.hybrid_search(
        query_dense, query_sparse, top_k=top_k
    )

    logger.info("知识库搜索完成", query=q, result_count=len(results))
    return success(data={"query": q, "results": results, "total": len(results)})
