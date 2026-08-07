"""文档解析任务模块。

本模块定义 arq 异步任务，负责文档解析的完整流水线与过期任务清理：

1. ``parse_document_impl``：文档解析主任务，执行端到端的解析流程：
   - 从 MinIO 下载原始文档（``storage_service.download``）
   - 调用 GLM-OCR 服务识别文字与版面区域（``ocr_service.parse_document``），
     包含 PP-DocLayoutV3 版面分析 + asyncio.gather 全并行 OCR
   - 若提供 ``schema_id``：加载 ``SchemaConfig`` 并调用
     ``extraction_service.extract`` 执行结构化字段抽取
   - 调用 ``term_service.standardize_text`` 对全文做术语标准化
   - 将解析文本、结构化数据与版面数据回写至 ``Document`` 记录
   - 每个阶段通过更新数据库 Task 记录上报进度

2. ``cleanup_expired_tasks_impl``：定时清理超过 7 天的 ``Task`` 记录

OCR 流程：GLM-OCR 自托管模式（PP-DocLayoutV3 版面分析 + GLM-OCR vLLM 全并行识别），
结果保存至 data/ocr_data/{task_id}/ 目录（source 文件 + result.md + merged.json）。

arq 任务原生为 async 函数，与服务层异步接口完美契合，无需 ``asyncio.run`` 包装。
数据库访问直接使用 ``AsyncSessionLocal`` 上下文管理器，而非 FastAPI 的 ``get_db`` 依赖。

错误处理策略：
    解析过程中任一阶段抛出异常时，将 ``Document.status`` 置为 ``failed``，
    记录错误信息，更新任务状态为 ``failed``，并重新抛出以由 arq 标记失败。
"""

import asyncio
import io
import traceback
import uuid
from datetime import datetime, timedelta

from sqlalchemy import delete, select, text, func
from sqlalchemy.ext.asyncio import AsyncSession
from arq.connections import ArqRedis

from app.core.database import AsyncSessionLocal
from app.core.config import settings
from app.core.exceptions import BusinessException, ErrorCode
from app.core.logging import get_logger
from app.models.document import Document
from app.models.knowledge_base import KnowledgeBase
from app.models.schema_model import SchemaConfig
from app.models.task import Task as TaskModel
# TODO: extraction_service已删除，结构化抽取改为后续通过extract_v3_task触发
# from app.services.extraction.extraction_pipeline import extraction_pipeline
from app.services.ocr import ocr_service
from app.services.ocr.postprocess import text_cleaner
from app.services.storage_service import storage_service
from app.services.term.term_service import term_service

logger = get_logger(__name__)

# 过期任务清理阈值：删除创建时间早于该天数前的 Task 记录
_TASK_EXPIRE_DAYS: int = 7


class TaskCancelledError(Exception):
    """任务已被用户取消的异常。"""
    pass


async def _check_task_cancelled(db: AsyncSession, task_id: str | None) -> None:
    """检查任务是否已被用户取消（状态为 failed），如果是则抛出 TaskCancelledError。"""
    if task_id is None:
        return
    task = await db.get(TaskModel, task_id)
    if task is not None and task.status == "failed":
        logger.info("任务已被用户取消，终止执行", task_id=task_id)
        raise TaskCancelledError("任务已被用户取消")


async def _activate_kb_rls(db: AsyncSession, kb_id: str | None) -> None:
    """在 worker 独立会话内激活 PostgreSQL RLS（方案 §9.1）。

    worker 不经过 FastAPI 的 ``get_kb_context`` 依赖，需手动执行
    ``SELECT set_config('app.current_kb', :kb_id, true)`` 激活 RLS，
    使后续 Document/Task 等业务表查询受 ``kb_id`` 行级安全策略约束。

    ``kb_id`` 为 None 时不激活（向后兼容旧端点，依赖 superuser 绕过 RLS
    或全局模式）。

    Args:
        db: 异步数据库会话。
        kb_id: 知识库 ID 字符串（UUID 标准格式，带连字符），None 时不激活。
    """
    if kb_id is None:
        return
    await db.execute(
        text("SELECT set_config('app.current_kb', :kb_id, true)"),
        {"kb_id": kb_id},
    )


async def _update_progress(
    task_id: str | None, progress: int, message: str, kb_id: str | None = None
) -> None:
    """更新任务进度到数据库。

    在独立的 ``AsyncSessionLocal`` 会话中更新 Task 记录的 progress 与 status 字段。
    若 task_id 为 None 或任务记录不存在，则静默跳过（不影响主流程）。

    知识库隔离：Task 表启用 RLS，``kb_id`` 非 None 时激活 RLS 才能查到任务记录。

    Args:
        task_id: 任务唯一标识（arq job_id），为 None 时跳过。
        progress: 进度百分比（0-100）。
        message: 进度描述信息（当前未持久化，预留扩展）。
        kb_id: 知识库 ID，None 时不激活 RLS（向后兼容）。
    """
    if not task_id:
        return
    try:
        async with AsyncSessionLocal() as db:
            await _activate_kb_rls(db, kb_id)
            stmt = select(TaskModel).where(TaskModel.id == task_id)
            result = await db.execute(stmt)
            task = result.scalar_one_or_none()
            if task:
                task.progress = progress
                task.status = "running"
                if task.started_at is None:
                    task.started_at = datetime.now()
                await db.commit()
    except Exception as exc:
        logger.warning("更新任务进度失败", task_id=task_id, error=str(exc))


async def _update_task_status(
    task_id: str | None,
    status: str,
    error: str | None = None,
    kb_id: str | None = None,
) -> None:
    """更新任务终态状态到数据库（completed / failed）。

    与 ``_update_progress`` 不同，本函数用于任务执行结束时的终态更新：
    成功时置 ``completed`` 并记录完成时间，失败时置 ``failed`` 并写入错误信息。
    在独立的 ``AsyncSessionLocal`` 会话中执行，失败时静默跳过不影响主流程。

    知识库隔离：Task 表启用 RLS，``kb_id`` 非 None 时激活 RLS 才能查到任务记录。

    Args:
        task_id: 任务唯一标识（arq job_id），为 None 时跳过。
        status: 终态状态，``completed`` 或 ``failed``。
        error: 失败时的错误信息（仅 status=failed 时使用，截断 2000 字符）。
        kb_id: 知识库 ID，None 时不激活 RLS（向后兼容）。
    """
    if not task_id:
        return
    try:
        async with AsyncSessionLocal() as db:
            await _activate_kb_rls(db, kb_id)
            stmt = select(TaskModel).where(TaskModel.id == task_id)
            result = await db.execute(stmt)
            task = result.scalar_one_or_none()
            if task:
                if status == "completed":
                    task.status = "success"
                    task.progress = 100
                    task.completed_at = datetime.now()
                else:
                    task.status = status
                    if status == "failed" and error:
                        task.error_message = error[:2000]
                await db.commit()
    except Exception as exc:
        logger.warning(
            "更新任务终态失败",
            task_id=task_id,
            status=status,
            error=str(exc),
        )


async def parse_document_impl(
    document_id: str,
    schema_id: str | None,
    term_base_id: str | None,
    ctx: dict,
    kb_id: str | None = None,
) -> dict:
    """文档解析主任务（arq 异步入口）。

    接收文档标识与可选的解析模式参数，执行完整的文档解析流程：
    下载文件 -> GLM-OCR 识别 -> 结构化抽取 -> 术语标准化 -> 入库。

    arq 任务原生为 async 函数，与服务层异步接口直接配合，无需 ``asyncio.run``。
    进度通过更新数据库 Task 记录上报，替代 Celery 的 ``self.update_state``。

    知识库隔离（方案 §9.3）：
    - ``kb_id`` 非 None 时，worker 会话内激活 RLS，下载走 KB 专属 bucket，
      OCR 输出到 KB 专属目录，术语标准化限定在 KB 范围。
    - ``kb_id`` 为 None 时向后兼容旧端点（全局模式，依赖 superuser 绕过 RLS）。

    Args:
        document_id: 待解析文档的唯一标识（UUID 字符串）。
        schema_id: 结构化抽取模式标识，None 表示跳过结构化抽取。
        term_base_id: 术语库标识，None 表示使用全量术语库。
        ctx: arq 任务上下文，包含 ``job_id`` 等元数据。
        kb_id: 知识库 ID 字符串，None 表示全局模式（向后兼容）。

    Returns:
        dict: 解析结果，包含 document_id、status、parsed_text 长度等摘要信息。

    Raises:
        Exception: 解析过程中任一阶段失败时重新抛出，由 arq 标记任务失败。
    """
    # 从 arq ctx 获取任务 ID，用于数据库进度更新
    task_id: str | None = ctx.get("job_id") if isinstance(ctx, dict) else None

    logger.info(
        "开始解析文档",
        document_id=document_id,
        schema_id=schema_id,
        term_base_id=term_base_id,
        task_id=task_id,
        kb_id=kb_id,
    )
    # 上报初始进度
    await _update_progress(task_id, 10, "开始解析", kb_id=kb_id)

    doc_uuid: uuid.UUID = uuid.UUID(document_id)
    # kb_id 转 UUID（供 service 层使用）
    kb_uuid: uuid.UUID | None = uuid.UUID(kb_id) if kb_id else None

    try:
        async with AsyncSessionLocal() as db:
            # 激活 RLS（kb_id 非 None 时），使 Document/Task 查询受 kb_id 约束
            await _activate_kb_rls(db, kb_id)
            # 加载文档记录，不存在则直接失败
            document: Document | None = await db.get(Document, doc_uuid)
            if document is None:
                raise BusinessException(
                    message=f"文档不存在: {document_id}",
                    code=ErrorCode.BUSINESS_DOCUMENT_NOT_FOUND,
                )

            # 【取消检查】任务开始前检查是否已被用户取消
            await _check_task_cancelled(db, task_id)

            # 标记为处理中
            document.status = "processing"
            await db.commit()

            # 读取 KB 配置，确定是否启用版面分析
            use_layout_analysis = True  # 默认启用
            if kb_uuid is not None:
                kb = await db.get(KnowledgeBase, kb_uuid)
                if kb is not None and kb.config:
                    ocr_cfg = kb.config.get("ocr", {}) if isinstance(kb.config, dict) else {}
                    # 默认启用版面分析（layout_analysis_enabled 未设置时为 True）
                    use_layout_analysis = ocr_cfg.get("layout_analysis_enabled", True)
                    logger.info(
                        "读取KB OCR配置",
                        kb_id=kb_id,
                        layout_analysis_enabled=use_layout_analysis,
                    )

            try:
                # ----------------------------------------------------------
                # 阶段 1：从 MinIO 下载原始文档（进度 10%）
                # ----------------------------------------------------------
                if not document.minio_object_name:
                    raise BusinessException(
                        message="文档缺少 MinIO 对象标识，无法下载",
                        code=ErrorCode.BUSINESS_TASK_FAILED,
                    )
                image_bytes: bytes = await storage_service.download(
                    document.minio_object_name, kb_id=kb_uuid
                )
                logger.info(
                    "文档下载完成",
                    document_id=document_id,
                    size=len(image_bytes),
                    kb_id=kb_id,
                )

                # ----------------------------------------------------------
                # 阶段 2：GLM-OCR 识别（进度 20%-50%）
                # ----------------------------------------------------------
                # GLM-OCR 自托管模式：PP-DocLayoutV3 版面分析 + asyncio.gather 全并行 OCR
                # 流程：PDF/图片 → 预处理 → 版面分析 → 全并行OCR → 格式化 → 保存文件
                await _update_progress(task_id, 20, "OCR识别中", kb_id=kb_id)
                ocr_result = await ocr_service.parse_document(
                    file_bytes=image_bytes,
                    task_id=task_id or document_id,
                    filename=document.minio_object_name,
                    kb_id=kb_uuid,
                    use_layout=use_layout_analysis,
                )
                full_text: str = ocr_result["text"]
                ocr_layout: list[dict] = ocr_result["layout"]
                ocr_json: str = ocr_result.get("json", "")
                total_pages: int = ocr_result["pages"]
                logger.info(
                    "OCR 识别完成",
                    document_id=document_id,
                    text_len=len(full_text),
                    layout_blocks=len(ocr_layout),
                    pages=total_pages,
                )

                # ----------------------------------------------------------
                # 阶段 3：版面数据准备（进度 50%）
                # ----------------------------------------------------------
                await _update_progress(task_id, 50, "版面数据处理中", kb_id=kb_id)
                merged_layout: list[dict] = list(ocr_layout)
                logger.info(
                    "版面数据准备完成",
                    document_id=document_id,
                    merged_blocks=len(merged_layout),
                )

                # ----------------------------------------------------------
                # 阶段 3.6：OCR 文本清洗（进度 55%）
                # ----------------------------------------------------------
                # 对 full_text 与 merged_layout 执行可配置清洗，移除空段落、
                # 冗余格式标记与乱码字符，下游抽取/标准化/存储均使用清洗后内容
                await _update_progress(task_id, 55, "文本清洗中", kb_id=kb_id)
                clean_level: str = getattr(settings, "OCR_CLEAN_LEVEL", "medium")
                original_len = len(full_text)
                full_text = text_cleaner.clean_text(full_text, clean_level)
                merged_layout = text_cleaner.clean_layout(
                    merged_layout, clean_level
                )
                logger.info(
                    "OCR 文本清洗完成",
                    document_id=document_id,
                    level=clean_level,
                    original_length=original_len,
                    cleaned_length=len(full_text),
                    layout_blocks=len(merged_layout),
                )

                # ----------------------------------------------------------
                # 阶段 3.8：术语标准化（进度 58%，KB 范围内标准化）
                # ----------------------------------------------------------
                await _update_progress(task_id, 58, "术语标准化中", kb_id=kb_id)
                term_base_uuid: uuid.UUID | None = (
                    uuid.UUID(term_base_id) if term_base_id else None
                )
                standard_result: dict = await term_service.standardize_text(
                    db, full_text, term_base_uuid, kb_id=kb_uuid
                )
                standardized_text: str = standard_result.get(
                    "standardized_text", full_text
                )
                replacements: list = standard_result.get("replacements", [])
                logger.info(
                    "术语标准化完成",
                    document_id=document_id,
                    replacement_count=len(replacements),
                )

                # ----------------------------------------------------------
                # 阶段 4：Popo重建 + 五维向量入库（进度 60%-90%）
                # ----------------------------------------------------------
                await _update_progress(task_id, 60, "文档结构重建中", kb_id=kb_id)

                from app.services.vector.reconstruction_service import reconstruction_service
                import json

                recon_result = await reconstruction_service.reconstruct(
                    task_id=task_id or document_id,
                    doc_id=document_id,
                    kb_id=kb_id,
                    build_vector_index=True,
                )

                task_dir = reconstruction_service._get_task_dir(task_id or document_id, kb_id=kb_id)
                markdown_content = ""
                popo_json_data = None
                md_path = task_dir / "reconstructed.md"
                if md_path.exists():
                    markdown_content = md_path.read_text(encoding="utf-8")
                popo_output_dir = task_dir / "popo_output"
                if popo_output_dir.exists():
                    json_files = list(popo_output_dir.glob("*.json"))
                    if json_files:
                        with json_files[0].open("r", encoding="utf-8") as f:
                            popo_json_data = json.load(f)

                await _update_progress(task_id, 90, "保存结果中", kb_id=kb_id)

                # ----------------------------------------------------------
                # 阶段 5：保存结果（进度 90%）
                # ----------------------------------------------------------
                vector_count = recon_result.get("stats", {}).get("向量入库数", 0)
                document.status = "completed"
                document.parsed_text = standardized_text
                document.markdown_content = markdown_content or None
                document.extraction_status = None  # 抽取由独立任务条件触发
                document.index_status = "completed" if vector_count > 0 else "completed"  # 五维向量已入库
                document.graph_status = None  # 图谱由"构建图谱"按钮独立触发
                document.graph_error = None
                document.layout_data = {
                    "ocr_layout": ocr_layout,
                    "merged": merged_layout,
                    "ocr_json": ocr_json,
                    "total_pages": total_pages,
                    "term_replacements": replacements,
                    "ocr_engine": "glmocr",
                    "use_layout": use_layout_analysis,
                    "output_dir": ocr_result.get("output_dir", ""),
                    "popo_stats": recon_result.get("stats", {}),
                    "popo_output_path": recon_result.get("popo_output_path", ""),
                }
                document.structured_data = None
                await db.commit()
                logger.info(
                    "文档解析结果已保存 (含Popo重建+五维向量入库)",
                    document_id=document_id,
                    vector_count=vector_count,
                )

                # ----------------------------------------------------------
                # 阶段 6：完成（进度 100%）
                # 注意：结构化抽取任务由用户在抽取页面手动触发，不在此处自动投递
                # 向量索引和图谱构建由"构建图谱"按钮独立触发
                # ----------------------------------------------------------
                await _update_progress(task_id, 100, "解析完成", kb_id=kb_id)
                # 标记任务终态为完成（前端据 status==='completed' 感知完成）
                await _update_task_status(task_id, "completed", kb_id=kb_id)
                logger.info("文档解析任务完成", document_id=document_id)

                # 通知钩子：任务完成通知文档所有者（阶段 4 - 通知中心）
                # Task 模型无 user_id，通过 document.owner_id 获取接收者；
                # 失败时静默，不影响主流程返回。
                if document.owner_id:
                    try:
                        from app.services.notification_service import (
                            create_notification,
                        )

                        await create_notification(
                            db,
                            document.owner_id,
                            "task_done",
                            title=f"文档解析完成：{document.filename}",
                            content=f"任务 {task_id} 已成功完成",
                            resource_type="task",
                            resource_id=task_id,
                            kb_id=kb_uuid,
                        )
                        await db.commit()
                    except Exception as notif_err:
                        logger.warning(
                            "创建任务完成通知失败",
                            document_id=document_id,
                            error=str(notif_err),
                        )

                return {
                    "document_id": document_id,
                    "status": "completed",
                    "parsed_text_length": len(standardized_text),
                    "layout_blocks": len(merged_layout),
                    "structured_fields": 0,  # 结构化抽取由独立的 extract_document_task 执行
                    "term_replacements": len(replacements),
                }

            except TaskCancelledError:
                # 任务被用户取消：不标记文档失败，优雅退出
                logger.info("任务被用户取消，终止解析流程", document_id=document_id, task_id=task_id)
                await db.rollback()
                # 文档状态恢复为 ready（取消前可能被设为 processing）
                try:
                    await _activate_kb_rls(db, kb_id)
                    cancelled_doc = await db.get(Document, doc_uuid)
                    if cancelled_doc is not None and cancelled_doc.status == "processing":
                        cancelled_doc.status = "ready"
                        await db.commit()
                except Exception:
                    pass
                return {"document_id": document_id, "status": "cancelled", "message": "任务已取消"}

            except Exception as exc:
                # 异常处理：标记文档为失败，回滚后写入错误状态
                logger.error(
                    "解析过程中异常，标记文档为失败",
                    document_id=document_id,
                    error=str(exc),
                )
                # 回滚事务以丢弃半成品写入，再单独提交失败状态
                await db.rollback()
                failed_doc: Document | None = None
                try:
                    # rollback 后 RLS 设置丢失，需重新激活
                    await _activate_kb_rls(db, kb_id)
                    # 重新获取文档并标记失败（rollback 后原对象已过期）
                    failed_doc = await db.get(Document, doc_uuid)
                    if failed_doc is not None:
                        failed_doc.status = "failed"
                        await db.commit()
                except Exception as mark_err:
                    logger.error(
                        "标记文档失败状态时再次异常",
                        document_id=document_id,
                        error=str(mark_err),
                    )
                # 标记任务终态为失败并记录错误信息
                await _update_task_status(task_id, "failed", str(exc), kb_id=kb_id)

                # 通知钩子：任务失败通知文档所有者（阶段 4 - 通知中心）
                # failed_doc 已在上方 try 块中获取（若存在），复用以读取
                # owner_id 与 filename；失败时静默，不影响 raise 传播。
                if failed_doc is not None and failed_doc.owner_id:
                    try:
                        from app.services.notification_service import (
                            create_notification,
                        )

                        await create_notification(
                            db,
                            failed_doc.owner_id,
                            "task_failed",
                            title=f"文档解析失败：{failed_doc.filename}",
                            content=(str(exc)[:200] if exc else "解析过程中发生错误"),
                            resource_type="task",
                            resource_id=task_id,
                            kb_id=kb_uuid,
                        )
                        await db.commit()
                    except Exception as notif_err:
                        logger.warning(
                            "创建任务失败通知失败",
                            document_id=document_id,
                            error=str(notif_err),
                        )
                raise

    except Exception as exc:
        # 记录完整错误堆栈，便于排障
        logger.error(
            "文档解析任务失败",
            document_id=document_id,
            error=str(exc),
            traceback=traceback.format_exc(),
        )
        raise


async def cleanup_expired_tasks_impl() -> dict:
    """清理过期任务记录。

    删除 ``tasks`` 表中创建时间早于 7 天的记录，避免结果无限增长。
    由 arq cron 调度器每日凌晨 2 点触发执行。

    Returns:
        dict: 包含 deleted_count 的清理结果摘要。
    """
    logger.info("开始清理过期任务记录", expire_days=_TASK_EXPIRE_DAYS)
    try:
        threshold: datetime = datetime.utcnow() - timedelta(days=_TASK_EXPIRE_DAYS)
        async with AsyncSessionLocal() as db:
            # 先查询待删除记录数量，便于日志记录与返回
            count_stmt = select(TaskModel).where(TaskModel.created_at < threshold)
            result = await db.execute(count_stmt)
            expired_tasks: list = list(result.scalars().all())
            if not expired_tasks:
                logger.info("无过期任务记录需要清理")
                return {"deleted_count": 0}

            deleted_count: int = len(expired_tasks)
            # 批量删除
            await db.execute(
                delete(TaskModel).where(TaskModel.created_at < threshold)
            )
            await db.commit()
            logger.info(
                "过期任务记录已删除",
                deleted_count=deleted_count,
                threshold=threshold.isoformat(),
            )
            return {"deleted_count": deleted_count}
    except Exception as err:
        logger.error("清理过期任务记录失败", error=str(err))
        raise
