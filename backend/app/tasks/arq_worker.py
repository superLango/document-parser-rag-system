"""arq 异步任务队列 Worker 配置。

替代原 celery_app.py，原生 asyncio，与 FastAPI 完美契合。
arq 通过 Redis/Valkey 进行任务分发，使用 msgpack 编码。

启动 Worker:
    arq app.tasks.arq_worker.WorkerSettings

任务通过 enqueue_job 提交:
    pool = await create_pool(RedisSettings(...))
    job = await pool.enqueue_job("parse_document_task", document_id, schema_id, term_base_id)
"""

from urllib.parse import urlparse

from arq import cron
from arq.connections import RedisSettings

from app.core.config import settings


def get_redis_settings() -> RedisSettings:
    """从配置构建 arq RedisSettings。

    解析 REDIS_URL，支持 docker 容器内的 valkey 服务名。
    arq 使用 database=1 作为任务队列（与 Celery broker 一致）。
    """
    redis_url = getattr(settings, "redis_url", None) or "redis://localhost:6379/0"
    parsed = urlparse(redis_url)
    host = parsed.hostname or "localhost"
    port = parsed.port or 6379
    # database=1 用于任务队列（database=0 用于缓存）
    return RedisSettings(
        host=host,
        port=port,
        password=parsed.password or None,
        database=1,
    )


# ---------------------------------------------------------------
# 任务函数 - 每个函数是 async def(ctx, *args) -> result
# arq 的 ctx 包含 job_id, job_try 等元数据
# ---------------------------------------------------------------

async def parse_document_task(
    ctx: dict,
    document_id: str,
    schema_id: str | None = None,
    term_base_id: str | None = None,
) -> dict:
    """文档解析任务（arq 入口）。

    委托给 document_tasks 模块的异步实现。
    """
    from app.tasks.document_tasks import parse_document_impl
    return await parse_document_impl(document_id, schema_id, term_base_id, ctx)


async def index_document_task(ctx: dict, doc_id: str) -> dict:
    """文档入知识库任务。"""
    from app.tasks.rag_tasks import index_document_impl
    return await index_document_impl(doc_id, ctx)


async def rebuild_index_task(ctx: dict) -> dict:
    """重建知识库索引。"""
    from app.tasks.rag_tasks import rebuild_index_impl
    return await rebuild_index_impl(ctx)


async def remove_document_task(ctx: dict, doc_id: str) -> dict:
    """从知识库移除文档。"""
    from app.tasks.rag_tasks import remove_document_impl
    return await remove_document_impl(doc_id, ctx)


async def build_document_graph_task(ctx: dict, doc_id: str) -> dict:
    """构建文档知识图谱。"""
    from app.tasks.graph_tasks import build_document_graph_impl
    return await build_document_graph_impl(doc_id, ctx)


async def rebuild_all_graphs_task(ctx: dict) -> dict:
    """重建所有知识图谱。"""
    from app.tasks.graph_tasks import rebuild_all_graphs_impl
    return await rebuild_all_graphs_impl(ctx)


async def remove_document_graph_task(ctx: dict, doc_id: str) -> dict:
    """删除文档知识图谱。"""
    from app.tasks.graph_tasks import remove_document_graph_impl
    return await remove_document_graph_impl(doc_id, ctx)


async def cleanup_expired_tasks_task(ctx: dict) -> dict:
    """定时清理过期任务记录。"""
    from app.tasks.document_tasks import cleanup_expired_tasks_impl
    return await cleanup_expired_tasks_impl()


class WorkerSettings:
    """arq Worker 配置。

    启动: arq app.tasks.arq_worker.WorkerSettings
    """
    redis_settings = get_redis_settings()

    # 注册所有任务函数
    functions = [
        parse_document_task,
        index_document_task,
        rebuild_index_task,
        remove_document_task,
        build_document_graph_task,
        rebuild_all_graphs_task,
        remove_document_graph_task,
        cleanup_expired_tasks_task,
    ]

    # 最大并发任务数（等价于 Celery worker_prefetch_multiplier=1）
    max_jobs = 1

    # 任务超时（秒，等价于 task_time_limit=3600）
    job_timeout = 3600

    # 定时任务（等价于 Celery beat_schedule）
    cron_jobs = [
        cron(cleanup_expired_tasks_task, hour=2, minute=0),
    ]

    # 启动时钩子
    async def on_startup(ctx):
        from app.core.logging import get_logger
        logger = get_logger("arq_worker")
        logger.info("arq Worker 启动")

    async def on_shutdown(ctx):
        from app.core.logging import get_logger
        logger = get_logger("arq_worker")
        logger.info("arq Worker 关闭")
