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

import asyncio
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
    kb_id: str | None = None,
) -> dict:
    """文档解析任务（arq 入口）。

    委托给 document_tasks 模块的异步实现。

    Args:
        ctx: arq 任务上下文。
        document_id: 文档唯一标识。
        schema_id: 结构化抽取模式标识，可选。
        term_base_id: 术语库标识，可选。
        kb_id: 知识库 ID 字符串，None 表示全局模式（向后兼容）。
            非 None 时 worker 激活 RLS 并路由到 KB 专属资源（bucket/目录/向量库）。
    """
    from app.tasks.document_tasks import parse_document_impl
    return await parse_document_impl(
        document_id, schema_id, term_base_id, ctx, kb_id=kb_id
    )


# TODO: rag_tasks和graph_tasks已删除，以下任务待Phase1重构
# @_record_metrics
# async def index_document_task(ctx: dict, doc_id: str) -> dict:
#     """文档入知识库任务。"""
#     from app.tasks.rag_tasks import index_document_impl
#     return await index_document_impl(doc_id, ctx)
#
#
# @_record_metrics
# async def rebuild_index_task(ctx: dict) -> dict:
#     """重建知识库索引。"""
#     from app.tasks.rag_tasks import rebuild_index_impl
#     return await rebuild_index_impl(ctx)
#
#
# @_record_metrics
# async def remove_document_task(ctx: dict, doc_id: str) -> dict:
#     """从知识库移除文档。"""
#     from app.tasks.rag_tasks import remove_document_impl
#     return await remove_document_impl(doc_id, ctx)
#
#
# @_record_metrics
# async def build_document_graph_task(ctx: dict, doc_id: str) -> dict:
#     """构建文档知识图谱。"""
#     from app.tasks.graph_tasks import build_document_graph_impl
#     return await build_document_graph_impl(doc_id, ctx)
#
#
# @_record_metrics
# async def rebuild_all_graphs_task(ctx: dict) -> dict:
#     """重建所有知识图谱。"""
#     from app.tasks.graph_tasks import rebuild_all_graphs_impl
#     return await rebuild_all_graphs_impl(ctx)
#
#
# @_record_metrics
# async def remove_document_graph_task(ctx: dict, doc_id: str) -> dict:
#     """删除文档知识图谱。"""
#     from app.tasks.graph_tasks import remove_document_graph_impl
#     return await remove_document_graph_impl(doc_id, ctx)

# TODO: index_graph_task待Phase1实现
# @_record_metrics
# async def index_graph_task(ctx: dict, doc_id: str) -> dict:
#     """文档入库+图谱构建任务。"""
#     pass


@_record_metrics
async def cleanup_expired_tasks_task(ctx: dict) -> dict:
    """定时清理过期任务记录。"""
    from app.tasks.document_tasks import cleanup_expired_tasks_impl
    return await cleanup_expired_tasks_impl()


@_record_metrics
async def scheduled_cleanup_task(ctx: dict) -> dict:
    """全量资源清理任务（过期任务/审计归档/孤儿向量/孤儿图谱/临时文件）。

    由 arq cron 每日凌晨 3:00 触发，也可通过 ``POST /system/cleanup`` 手动触发。
    """
    from app.tasks.cleanup_tasks import run_full_cleanup
    return await run_full_cleanup(dry_run=False)


@_record_metrics
async def warmup_prompt_cache_task(ctx: dict) -> dict:
    """Prompt 缓存预热任务（低峰期触发，提升 prefix cache 命中率）。

    遍历所有类别的静态 prompt 前缀，发送 1-token 请求到 vLLM，
    触发 prefill 并驻留 KV cache。串行执行避免并发抢占 GPU。
    """
    from app.tasks.prompt_cache_warmer import warmup_prompt_cache_task as _warmup
    return await _warmup(ctx)


@_record_metrics
async def extract_v3_task(ctx: dict, task_id: str, kb_id: str | None = None) -> dict:
    """v3 结构化抽取任务（arq 入口，向后兼容）。

    在文档 OCR + 五维向量入库完成后触发，执行 v3 抽取流程。

    Args:
        ctx: arq 任务上下文。
        task_id: 任务 ID（雪花 ID），同时作为向量库的 doc_id。
        kb_id: 知识库 ID。
    """
    from app.tasks.extraction_tasks import extract_v3_impl
    return await extract_v3_impl(task_id, ctx)


@_record_metrics
async def extract_document_task(
    ctx: dict,
    document_id: str,
    kb_id: str | None = None,
) -> dict:
    """文档结构化抽取任务（arq 入口，"抽取"按钮触发）。

    Args:
        ctx: arq 任务上下文。
        document_id: 文档唯一标识。
        kb_id: 知识库 ID 字符串，None 表示全局模式。
    """
    from app.tasks.extraction_tasks import extract_document_impl
    return await extract_document_impl(document_id, kb_id, ctx)


@_record_metrics
async def build_index_graph_task(
    ctx: dict,
    document_id: str,
    kb_id: str | None = None,
) -> dict:
    """构建RAG向量索引和图谱任务（arq 入口，"构建图谱"按钮触发）。

    Args:
        ctx: arq 任务上下文。
        document_id: 文档唯一标识。
        kb_id: 知识库 ID 字符串，None 表示全局模式。
    """
    from app.tasks.index_graph_tasks import build_index_graph_impl
    return await build_index_graph_impl(document_id, kb_id, ctx)


class WorkerSettings:
    """arq Worker 配置。

    启动: arq app.tasks.arq_worker.WorkerSettings
    """
    redis_settings = get_redis_settings()

    # 注册所有任务函数
    functions = [
        parse_document_task,
        extract_document_task,
        build_index_graph_task,
        cleanup_expired_tasks_task,
        scheduled_cleanup_task,
        warmup_prompt_cache_task,
        extract_v3_task,
    ]

    # 最大并发任务数（等价于 Celery worker_prefetch_multiplier=1）
    max_jobs = 1

    # 关闭 arq 信号处理：arq 的 SIGINT/SIGTERM 处理器与底层 C++ 库
    # （torch / OpenCV）的信号处理冲突，多页大图推理时可能触发段错误。
    # 关闭后由系统默认信号处理接管，不影响任务正常执行。
    handle_signals = False

    # 任务超时（秒，等价于 task_time_limit=3600）
    job_timeout = 7200

    # 定时任务（等价于 Celery beat_schedule）
    cron_jobs = [
        # 清理过期任务：每天 1:00
        cron(cleanup_expired_tasks_task, hour=1, minute=0),
        # Prompt 缓存预热：每天 1:30（低峰期触发）
        # 向 vLLM 发送所有类别的静态 prompt 前缀，驻留 KV cache 提升命中率
        cron(
            warmup_prompt_cache_task,
            hour=settings.EXTRACTION_PROMPT_CACHE_WARMUP_CRON_HOUR,
            minute=30,
        ),
        # 全量资源清理：每天 3:00（过期任务/审计归档/孤儿向量/孤儿图谱/临时文件）
        cron(scheduled_cleanup_task, hour=3, minute=0),
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

        # 预热 GLM-OCR 模型（PP-DocLayoutV3 版面分析 + vLLM OCR 客户端）
        try:
            from app.services.ocr import ocr_service
            logger.info("开始预热 GLM-OCR 模型")
            await ocr_service.warmup()
            logger.info("GLM-OCR 模型预热完成")
        except Exception as exc:
            logger.warning(
                "GLM-OCR 模型预热失败，将在任务执行时重试",
                error=str(exc),
            )

        # 预热 gliclass 零样本分类模型（召回阶段类别过滤）
        # 仅在启用召回分类过滤时预热，避免不必要的显存占用
        if settings.EXTRACTION_RECALL_CLASSIFY_FILTER_ENABLED:
            try:
                from app.services.rag.chunk_services.chunk_classifier import (
                    chunk_classifier_service,
                )

                logger.info("开始预热 gliclass 分类模型")
                await asyncio.to_thread(chunk_classifier_service.warmup)
                logger.info("gliclass 分类模型预热完成")
            except Exception as exc:
                logger.warning(
                    "gliclass 分类模型预热失败，将在首次调用时懒加载",
                    error=str(exc),
                )

        # 预热 bge-m3 嵌入模型（五维向量化 + 检索阶段共用）
        # 模型加载 ~4s + 首次推理 ~0.5s，启动时预热避免首个文档任务承担延迟
        try:
            from app.services.embedding.embedding_service import embedding_service

            logger.info("开始预热 bge-m3 嵌入模型（五维向量化）")
            await embedding_service.warmup()
            logger.info("bge-m3 嵌入模型预热完成")
        except Exception as exc:
            logger.warning(
                "bge-m3 嵌入模型预热失败，将在首次调用时懒加载",
                error=str(exc),
            )

    async def on_shutdown(ctx):
        from app.core.logging import get_logger
        logger = get_logger("arq_worker")
        logger.info("arq Worker 关闭")
