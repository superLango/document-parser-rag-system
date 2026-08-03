"""资源清理任务（阶段 3 - 资源清理）。

提供系统级资源清理能力，由 arq cron 定时触发或通过管理端点手动触发：
- 过期任务记录（>30 天，复用 document_tasks.cleanup_expired_tasks_impl）
- 审计日志归档（>AUDIT_LOG_RETENTION_DAYS 天）
- 临时文件清理（OCR 临时目录中无关联任务的孤儿文件）
- 孤儿向量清理（Milvus 中 doc_id 不在 documents 表的分块）
- 孤儿图谱节点清理（NebulaGraph 中 doc_id 不在 documents 表的节点）

所有清理函数支持 dry_run 模式（仅统计不删除），便于预览。
"""

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.models.audit_log import AuditLog
from app.models.document import Document
from app.models.task import Task

logger = get_logger(__name__)

# 过期任务保留天数
_TASK_EXPIRE_DAYS = 30


async def cleanup_expired_tasks(dry_run: bool = False) -> dict:
    """清理过期任务记录（>30 天）。

    Args:
        dry_run: True 时仅统计不删除。

    Returns:
        dict: ``{"deleted_count": int, "dry_run": bool}``。
    """
    threshold = datetime.now(timezone.utc) - timedelta(days=_TASK_EXPIRE_DAYS)
    async with AsyncSessionLocal() as db:
        count_result = await db.execute(
            select(Task).where(Task.created_at < threshold)
        )
        expired = count_result.scalars().all()
        count = len(expired)

        if not dry_run and count > 0:
            await db.execute(delete(Task).where(Task.created_at < threshold))
            await db.commit()
            logger.info("过期任务记录已清理", deleted_count=count, threshold=threshold.isoformat())

    return {"deleted_count": count, "dry_run": dry_run}


async def cleanup_audit_logs(dry_run: bool = False) -> dict:
    """归档/清理过期审计日志（>AUDIT_LOG_RETENTION_DAYS 天）。

    Args:
        dry_run: True 时仅统计不删除。

    Returns:
        dict: ``{"deleted_count": int, "retention_days": int, "dry_run": bool}``。
    """
    retention_days = settings.AUDIT_LOG_RETENTION_DAYS
    if retention_days <= 0:
        return {"deleted_count": 0, "retention_days": retention_days, "dry_run": dry_run, "skipped": True}

    threshold = datetime.now(timezone.utc) - timedelta(days=retention_days)
    async with AsyncSessionLocal() as db:
        count_result = await db.execute(
            select(AuditLog).where(AuditLog.created_at < threshold)
        )
        expired = count_result.scalars().all()
        count = len(expired)

        if not dry_run and count > 0:
            await db.execute(delete(AuditLog).where(AuditLog.created_at < threshold))
            await db.commit()
            logger.info(
                "过期审计日志已清理",
                deleted_count=count,
                retention_days=retention_days,
                threshold=threshold.isoformat(),
            )

    return {"deleted_count": count, "retention_days": retention_days, "dry_run": dry_run}


async def cleanup_orphan_vectors(dry_run: bool = False) -> dict:
    """清理 Milvus 中的孤儿向量（doc_id 不在 documents 表）。

    遍历全局 Collection（doc_chunks / doc_v2_*），检查每个分块的 doc_id
    是否在 documents 表中存在，不存在则为孤儿。

    Args:
        dry_run: True 时仅统计不删除。

    Returns:
        dict: ``{"orphan_count": int, "collections_checked": list, "dry_run": bool}``。
    """
    orphan_total = 0
    collections_checked: list[str] = []

    try:
        from app.services.vector.chunk_vector_store import vector_store
    except ImportError:
        logger.warning("vector_store 不可用，跳过孤儿向量清理")
        return {"orphan_count": 0, "collections_checked": [], "dry_run": dry_run, "skipped": True}

    async with AsyncSessionLocal() as db:
        # 获取所有有效的 doc_id
        doc_ids_result = await db.execute(select(Document.id))
        valid_doc_ids = {str(r[0]) for r in doc_ids_result.all()}

        # 检查全局 Collection（旧架构，未按 KB 隔离）
        global_collections = ["doc_chunks", "doc_v2_items", "doc_v2_methods", "doc_v2_features", "doc_v2_projects", "doc_v2_standards"]
        for coll_name in global_collections:
            try:
                if not hasattr(vector_store, "_client") or vector_store._client is None:
                    break
                # 尝试查询 Collection 中的所有 doc_id
                # Milvus 查询：获取 distinct doc_id
                results = vector_store._client.query(
                    collection_name=coll_name,
                    output_fields=["doc_id"],
                    limit=16384,
                )
                collections_checked.append(coll_name)

                orphan_doc_ids: list[str] = []
                seen = set()
                for row in results:
                    doc_id = str(row.get("doc_id", ""))
                    if doc_id and doc_id not in valid_doc_ids and doc_id not in seen:
                        seen.add(doc_id)
                        orphan_doc_ids.append(doc_id)

                if orphan_doc_ids and not dry_run:
                    # 删除孤儿向量
                    try:
                        vector_store._client.delete(
                            collection_name=coll_name,
                            filter=f'doc_id in {orphan_doc_ids}',
                        )
                    except Exception as del_err:  # noqa: BLE001
                        logger.warning(
                            "删除孤儿向量失败",
                            collection=coll_name,
                            error=str(del_err),
                        )

                orphan_total += len(orphan_doc_ids)
            except Exception as err:  # noqa: BLE001
                logger.debug("Collection 检查跳过", collection=coll_name, error=str(err)[:100])

    logger.info("孤儿向量清理完成", orphan_count=orphan_total, collections=collections_checked, dry_run=dry_run)
    return {"orphan_count": orphan_total, "collections_checked": collections_checked, "dry_run": dry_run}


async def cleanup_orphan_graph_nodes(dry_run: bool = False) -> dict:
    """清理 NebulaGraph 中的孤儿图谱节点（doc_id 不在 documents 表）。

    Args:
        dry_run: True 时仅统计不删除。

    Returns:
        dict: ``{"orphan_count": int, "dry_run": bool}``。
    """
    try:
        from app.services.graph.graph_store import graph_store
    except ImportError:
        logger.warning("graph_store 不可用，跳过孤儿图谱清理")
        return {"orphan_count": 0, "dry_run": dry_run, "skipped": True}

    if not hasattr(graph_store, "cleanup_orphan_nodes"):
        logger.debug("graph_store 不支持 cleanup_orphan_nodes，跳过")
        return {"orphan_count": 0, "dry_run": dry_run, "skipped": True}

    async with AsyncSessionLocal() as db:
        doc_ids_result = await db.execute(select(Document.id))
        valid_doc_ids = [str(r[0]) for r in doc_ids_result.all()]

    try:
        orphan_count = await graph_store.cleanup_orphan_nodes(
            valid_doc_ids, dry_run=dry_run
        )
    except Exception as err:  # noqa: BLE001
        logger.warning("孤儿图谱节点清理失败", error=str(err))
        return {"orphan_count": 0, "dry_run": dry_run, "error": str(err)[:200]}

    return {"orphan_count": orphan_count, "dry_run": dry_run}


async def cleanup_temp_files(dry_run: bool = False) -> dict:
    """清理临时文件（OCR 输出目录中无关联任务的孤儿文件）。

    扫描 OCR 输出目录中按 task_id 命名的子目录，若 task_id 不在 tasks 表中
    且修改时间超过 7 天，则视为孤儿文件予以清理。

    Args:
        dry_run: True 时仅统计不删除。

    Returns:
        dict: ``{"deleted_count": int, "freed_bytes": int, "dry_run": bool}``。
    """
    ocr_output_dir = getattr(settings, "OCR_OUTPUT_DIR", None)
    if not ocr_output_dir or not os.path.isdir(ocr_output_dir):
        return {"deleted_count": 0, "freed_bytes": 0, "dry_run": dry_run, "skipped": True}

    threshold = datetime.now(timezone.utc) - timedelta(days=7)
    deleted_count = 0
    freed_bytes = 0

    async with AsyncSessionLocal() as db:
        # 获取所有有效 task_id
        task_ids_result = await db.execute(select(Task.id))
        valid_task_ids = {str(r[0]) for r in task_ids_result.all()}

    base_path = Path(ocr_output_dir)
    for item in base_path.iterdir():
        if not item.is_dir():
            continue
        task_id = item.name
        # 跳过有效任务目录
        if task_id in valid_task_ids:
            continue
        # 检查修改时间
        try:
            mtime = datetime.fromtimestamp(item.stat().st_mtime, tz=timezone.utc)
        except OSError:
            continue
        if mtime > threshold:
            continue

        # 统计目录大小
        dir_size = sum(f.stat().st_size for f in item.rglob("*") if f.is_file())

        if not dry_run:
            import shutil
            try:
                shutil.rmtree(item)
                deleted_count += 1
                freed_bytes += dir_size
            except Exception as err:  # noqa: BLE001
                logger.warning("删除临时目录失败", path=str(item), error=str(err))
        else:
            deleted_count += 1
            freed_bytes += dir_size

    logger.info("临时文件清理完成", deleted_count=deleted_count, freed_bytes=freed_bytes, dry_run=dry_run)
    return {"deleted_count": deleted_count, "freed_bytes": freed_bytes, "dry_run": dry_run}


async def run_full_cleanup(dry_run: bool = False) -> dict:
    """执行全量资源清理（所有清理项汇总）。

    Args:
        dry_run: True 时仅统计不删除。

    Returns:
        dict: 各清理项的结果汇总。
    """
    logger.info("开始全量资源清理", dry_run=dry_run)
    results = {
        "dry_run": dry_run,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "tasks": await cleanup_expired_tasks(dry_run=dry_run),
        "audit_logs": await cleanup_audit_logs(dry_run=dry_run),
        "orphan_vectors": await cleanup_orphan_vectors(dry_run=dry_run),
        "orphan_graph_nodes": await cleanup_orphan_graph_nodes(dry_run=dry_run),
        "temp_files": await cleanup_temp_files(dry_run=dry_run),
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    logger.info("全量资源清理完成", dry_run=dry_run, results=results)
    return results


# ============================================================
# arq 任务入口（供 cron 调度）
# ============================================================
async def scheduled_cleanup_task(ctx: dict) -> dict:
    """arq 定时清理任务入口（每日凌晨 3 点执行，非 dry_run）。"""
    return await run_full_cleanup(dry_run=False)
