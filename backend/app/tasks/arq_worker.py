"""arq 异步任务队列 Worker 配置。

替代原 celery_app.py，原生 asyncio，与 FastAPI 完美契合。
arq 通过 Redis/Valkey 进行任务分发，使用 msgpack 编码。

本模块还集成了 Prometheus 指标采集：
- 启动时在 9100 端口暴露 metrics HTTP server
- 通过 task_counter / task_duration / task_queue_size 三个指标
  分别记录任务总数、任务执行时长和当前队列大小
- 使用 @_record_metrics 装饰器自动在任务执行前后记录指标

启动 Worker:
    arq app.tasks.arq_worker.WorkerSettings

任务通过 enqueue_job 提交:
    pool = await create_pool(RedisSettings(...))
    job = await pool.enqueue_job("parse_document_task", document_id, schema_id, term_base_id)
"""

import time
from functools import wraps
from urllib.parse import urlparse

from arq import cron
from arq.connections import RedisSettings
from prometheus_client import Counter, Gauge, Histogram, start_http_server

from app.core.config import settings

# ---------------------------------------------------------------
# Prometheus 指标定义
# task_counter: 任务执行总数，按任务名和状态（success/failure）分组
# task_duration: 任务执行时长直方图，按任务名分组
# task_queue_size: 当前队列中待处理任务数（Gauge）
# ---------------------------------------------------------------
task_counter = Counter(
    "arq_tasks_total",
    "Total tasks processed",
    ["task_name", "status"],
)
task_duration = Histogram(
    "arq_task_duration_seconds",
    "Task duration",
    ["task_name"],
)
task_queue_size = Gauge(
    "arq_queue_size",
    "Current queue size",
)


def _record_metrics(func):
    """装饰器：自动记录 arq 任务的执行计数与耗时。

    在任务执行成功时记录 status=success，抛出异常时记录 status=failure，
    并始终记录执行时长到 task_duration 直方图。

    Args:
        func: 被装饰的 arq 任务函数，签名为 async def(ctx, *args) -> result。

    Returns:
        包装后的协程函数，保持原函数签名与元信息。
    """

    @wraps(func)
    async def wrapper(ctx: dict, *args, **kwargs):
        task_name = func.__name__
        start = time.perf_counter()
        try:
            result = await func(ctx, *args, **kwargs)
            task_counter.labels(task_name=task_name, status="success").inc()
            return result
        except Exception:
            task_counter.labels(task_name=task_name, status="failure").inc()
            raise
        finally:
            task_duration.labels(task_name=task_name).observe(
                time.perf_counter() - start
            )

    return wrapper


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

@_record_metrics
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


@_record_metrics
async def index_document_task(ctx: dict, doc_id: str) -> dict:
    """文档入知识库任务。"""
    from app.tasks.rag_tasks import index_document_impl
    return await index_document_impl(doc_id, ctx)


@_record_metrics
async def rebuild_index_task(ctx: dict) -> dict:
    """重建知识库索引。"""
    from app.tasks.rag_tasks import rebuild_index_impl
    return await rebuild_index_impl(ctx)


@_record_metrics
async def remove_document_task(ctx: dict, doc_id: str) -> dict:
    """从知识库移除文档。"""
    from app.tasks.rag_tasks import remove_document_impl
    return await remove_document_impl(doc_id, ctx)


@_record_metrics
async def build_document_graph_task(ctx: dict, doc_id: str) -> dict:
    """构建文档知识图谱。"""
    from app.tasks.graph_tasks import build_document_graph_impl
    return await build_document_graph_impl(doc_id, ctx)


@_record_metrics
async def rebuild_all_graphs_task(ctx: dict) -> dict:
    """重建所有知识图谱。"""
    from app.tasks.graph_tasks import rebuild_all_graphs_impl
    return await rebuild_all_graphs_impl(ctx)


@_record_metrics
async def remove_document_graph_task(ctx: dict, doc_id: str) -> dict:
    """删除文档知识图谱。"""
    from app.tasks.graph_tasks import remove_document_graph_impl
    return await remove_document_graph_impl(doc_id, ctx)


@_record_metrics
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
        # 启动 Prometheus metrics HTTP server（端口 9102，避开 WeKnora 占用的 9100/9101）
        # 供 Prometheus 抓取 arq 任务相关指标
        start_http_server(9102)
        # 初始化队列大小指标为 0，后续由任务调度自然反映
        task_queue_size.set(0)
        logger.info("arq Worker 启动，metrics server 监听 9102 端口")

        # 在 arq event loop 中预热 OCR 模型
        # 重要：paddleocr/paddlepaddle-gpu 在 arq 的 asyncio loop 中首次调用时，
        # 可能因 CUDA 上下文初始化与 arq 的信号处理冲突而报 CUDA error(304)
        # 在 on_startup 中提前 warmup，确保 GPU 上下文在主线程中正确初始化
        try:
            from app.services.ocr_service import ocr_service
            logger.info("开始预热 OCR 模型...")
            await ocr_service.warmup()
            logger.info(
                "OCR 模型预热完成",
                backend=ocr_service._backend,
                loaded=ocr_service._loaded,
            )
        except Exception as exc:
            logger.warning(
                "OCR 模型预热失败，将在任务执行时重试",
                error=str(exc),
            )

    async def on_shutdown(ctx):
        from app.core.logging import get_logger
        logger = get_logger("arq_worker")
        logger.info("arq Worker 关闭")
