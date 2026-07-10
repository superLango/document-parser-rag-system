"""文档解析任务模块。

本模块定义 Celery 异步任务，负责耗时文档处理操作：
- parse_document：文档解析主任务（Phase 2 实现具体逻辑）
- cleanup_expired_tasks：定时清理过期任务结果

任务通过 Celery 调度执行，支持进度上报与状态追踪。
"""

from celery import Task

from app.core.logging import get_logger
from app.tasks.celery_app import celery_app

logger = get_logger(__name__)


@celery_app.task(bind=True, name="parse_document")
def parse_document(
    self: Task,
    document_id: str,
    schema_id: str | None = None,
    term_base_id: str | None = None,
) -> str:
    """文档解析主任务。

    接收文档标识与可选的解析模式参数，执行完整的文档解析流程：
    下载文件 -> OCR/文本提取 -> 结构化解析 -> 分块向量化 -> 入库。

    Phase 1 仅提供任务骨架与进度上报，Phase 2 将填充具体解析逻辑。

    Args:
        self: Celery 任务实例（bind=True 绑定）。
        document_id: 待解析文档的唯一标识。
        schema_id: 解析模式/模板标识，None 表示使用默认模式。
        term_base_id: 术语库标识，None 表示不应用术语库对齐。

    Returns:
        str: 文档标识（document_id），表示任务接收成功。
    """
    logger.info(
        "开始解析文档",
        document_id=document_id,
        schema_id=schema_id,
        term_base_id=term_base_id,
    )
    # 更新任务状态为进行中，上报初始进度
    self.update_state(state="PROGRESS", meta={"progress": 0, "message": "开始解析"})

    # TODO: Phase 2 实现完整解析流程
    #   1. 从 MinIO 下载原始文档（storage_service.download）
    #   2. 调用 OCR 提取文本（PaddleOCR-VL）
    #   3. 按模板/模式结构化解析
    #   4. 文本分块并生成向量（bge-base-zh-v1.5）
    #   5. 写入向量数据库（Milvus）与关系数据库（PostgreSQL）
    #   6. 每个阶段通过 self.update_state 上报进度

    logger.info("文档解析任务骨架执行完成", document_id=document_id)
    return document_id


@celery_app.task(name="cleanup_expired_tasks")
def cleanup_expired_tasks() -> int:
    """清理过期任务结果。

    删除超过 7 天的 Celery 任务结果记录，避免结果后端无限增长。
    由 Beat 调度器每日凌晨 2 点触发执行。

    Returns:
        int: 本次清理的任务结果数量。
    """
    logger.info("开始清理过期任务结果，阈值 7 天")
    deleted_count = 0

    # TODO: Phase 2 接入关系数据库后，按 document 表的 created_at 字段
    #   精确清理关联的解析任务记录
    # 通过结果后端清理已过期的任务结果
    try:
        backend = celery_app.backend
        # 触发后端自带的过期结果清理机制
        if hasattr(backend, "cleanup"):
            backend.cleanup()
            logger.info("结果后端清理完成")
    except Exception as err:
        logger.error("清理过期任务结果失败", error=str(err))
        raise

    logger.info("过期任务结果清理完成", deleted_count=deleted_count)
    return deleted_count
