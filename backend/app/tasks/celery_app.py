"""Celery 应用配置模块。

本模块创建并配置 Celery 应用实例 "document_parser"，用于异步执行
文档解析等耗时任务。主要配置包括：

- 消息代理（Broker）：基于 Redis，负责任务分发
- 结果后端（Backend）：基于 Redis，存储任务执行结果
- 任务序列化：统一使用 JSON
- 超时控制：硬超时 3600 秒，软超时 3000 秒
- 可靠性：acks_late + reject_on_worker_lost，避免任务丢失
- 定时任务：每日凌晨 2 点清理过期任务

启动 Worker：
    celery -A app.tasks.celery_app worker --loglevel=info

启动 Beat 调度器：
    celery -A app.tasks.celery_app beat --loglevel=info
"""

from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

# 创建 Celery 应用实例
celery_app = Celery(
    "document_parser",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["app.tasks.document_tasks"],
)

# 序列化与内容类型配置：统一使用 JSON，保证跨语言兼容性
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    # 任务状态追踪：记录任务开始状态，便于前端轮询进度
    task_track_started=True,
    # 超时控制：硬超时强制终止，软超时抛 SoftTimeLimitExceeded
    task_time_limit=3600,
    task_soft_time_limit=3000,
    # 预取策略：每次仅预取一个任务，避免长任务阻塞短任务
    worker_prefetch_multiplier=1,
    # 结果保留时长：24 小时后自动过期
    result_expires=86400,
    # 可靠性配置：任务执行成功后才确认，Worker 异常退出时拒绝任务并重新入队
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # 启动时重试连接 Broker，避免 Broker 未就绪时崩溃
    broker_connection_retry_on_startup=True,
)

# 定时任务调度：每日凌晨 2 点清理过期任务
celery_app.conf.beat_schedule = {
    "cleanup-expired-tasks-daily": {
        "task": "cleanup_expired_tasks",
        "schedule": crontab(hour=2, minute=0),
    },
}
