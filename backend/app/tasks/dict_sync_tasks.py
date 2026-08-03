"""检测项目基础三表同步定时任务（v3，迁移至 base_data 服务）。

由 arq worker 按定时计划触发，调用 ``base_table_sync_service.sync_all`` 完成基础表
全量同步：外部接口拉取 → PostgreSQL 三表更新 → Milvus 向量索引重建。

同步策略：
- 全量替换：每次同步删除旧数据后全量插入，简单可靠
- 容错：任一步骤失败记录日志不抛出，避免 arq 任务重试风暴
- 幂等：重复执行结果一致，适合定时调度

定时配置（默认每天凌晨 2:00，可通过环境变量调整）：
    cron(
        sync_project_dict_task,
        hour=settings.PROJECT_DICT_SYNC_CRON_HOUR,    # 默认 2
        minute=settings.PROJECT_DICT_SYNC_CRON_MINUTE, # 默认 0
    )

注意：与 cleanup_expired_tasks_task（原 2:00）时间冲突，cleanup 已调整至 1:00。

手动触发方式：
1. 直接调用 impl 函数（调试用）：
       from app.tasks.dict_sync_tasks import sync_project_dict_impl
       result = await sync_project_dict_impl()
2. 通过 arq enqueue_job（生产用，进入任务队列）：
       await pool.enqueue_job("sync_project_dict_task")
3. 仅重建 Milvus 向量索引（PG 数据已手动修改）：
       from app.tasks.dict_sync_tasks import rebuild_dict_vector_index_impl
       result = await rebuild_dict_vector_index_impl()
"""

from __future__ import annotations

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


async def sync_project_dict_impl() -> dict:
    """基础表同步实现（arq 任务与手动触发的统一入口）。

    委托给 ``base_table_sync_service.sync_all``，完成：
    1. 调用 ``PROJECT_DICT_SYNC_URL`` 拉取三张基础表全量数据
       （sm_feature / sm_item / sm_method）
    2. 全量更新 PostgreSQL 三张表
    3. 重新向量化 sm_item → 重建 Milvus base_data 集合

    Returns:
        dict: 同步结果统计，包含：
            - fetched: 各表拉取记录数
            - pg_inserted: 各表 PG 插入数
            - milvus_inserted: Milvus 向量插入数
            - status: success / failed / skipped
            - error: 失败时的错误信息
    """
    from app.services.base_data import base_table_sync_service

    # 前置校验：接口未配置时跳过（不视为失败）
    if not settings.PROJECT_DICT_SYNC_URL:
        logger.warning("基础表同步跳过：PROJECT_DICT_SYNC_URL 未配置")
        return {
            "fetched": {"feature": 0, "item": 0, "method": 0},
            "pg_inserted": {"feature": 0, "item": 0, "method": 0},
            "milvus_inserted": 0,
            "status": "skipped",
            "error": "PROJECT_DICT_SYNC_URL 未配置",
        }

    logger.info("基础表定时同步任务开始")
    result = await base_table_sync_service.sync_all()
    logger.info(
        "基础表定时同步任务完成",
        status=result["status"],
        pg_inserted=result.get("pg_inserted"),
        milvus_inserted=result.get("milvus_inserted"),
    )
    return result


async def rebuild_dict_vector_index_impl() -> dict:
    """仅重建 Milvus 向量索引（不拉取外部数据）。

    用于以下场景：
    - 基础表 PG 数据已手动修改，需同步到 Milvus
    - 向量索引损坏需重建
    - bge-m3 模型升级后重新向量化

    Returns:
        dict: 重建结果统计。
    """
    from app.services.base_data import base_table_sync_service

    logger.info("基础表向量索引重建任务开始")
    inserted = await base_table_sync_service.rebuild_vector_index()
    logger.info("基础表向量索引重建任务完成", inserted=inserted)
    return {
        "milvus_inserted": inserted,
        "status": "success" if inserted >= 0 else "failed",
    }
