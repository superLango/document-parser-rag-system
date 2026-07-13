"""文档解析任务模块。

本模块定义 arq 异步任务，负责文档解析的完整流水线与过期任务清理：

1. ``parse_document_impl``：文档解析主任务，执行端到端的解析流程：
   - 从 MinIO 下载原始文档（``storage_service.download``）
   - 调用 OCR 服务识别文字与版面区域（``ocr_service.recognize_with_layout``）
   - 调用版面分析服务抽取结构化文本块（``layout_service.extract_text_blocks``），
     并与 OCR 版面结果合并
   - 若提供 ``schema_id``：加载 ``SchemaConfig`` 并调用
     ``extraction_service.extract`` 执行结构化字段抽取
   - 调用 ``term_service.standardize_text`` 对全文做术语标准化
   - 将解析文本、结构化数据与版面数据回写至 ``Document`` 记录
   - 每个阶段通过更新数据库 Task 记录上报进度

2. ``cleanup_expired_tasks_impl``：定时清理超过 7 天的 ``Task`` 记录

arq 任务原生为 async 函数，与服务层异步接口完美契合，无需 ``asyncio.run`` 包装。
数据库访问直接使用 ``AsyncSessionLocal`` 上下文管理器，而非 FastAPI 的 ``get_db`` 依赖。

错误处理策略：
    解析过程中任一阶段抛出异常时，将 ``Document.status`` 置为 ``failed``，
    记录错误信息，更新任务状态为 ``failed``，并重新抛出以由 arq 标记失败。
"""

import traceback
import uuid
from datetime import datetime, timedelta

from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.core.exceptions import BusinessException, ErrorCode
from app.core.logging import get_logger
from app.models.document import Document
from app.models.schema_model import SchemaConfig
from app.models.task import Task as TaskModel
from app.services.extraction_service import extraction_service
from app.services.layout_service import layout_service
from app.services.ocr_service import ocr_service
from app.services.popo_service import popo_service
from app.services.storage_service import storage_service
from app.services.term_service import term_service

logger = get_logger(__name__)

# 过期任务清理阈值：删除创建时间早于该天数前的 Task 记录
_TASK_EXPIRE_DAYS: int = 7


async def _update_progress(task_id: str | None, progress: int, message: str) -> None:
    """更新任务进度到数据库。

    在独立的 ``AsyncSessionLocal`` 会话中更新 Task 记录的 progress 与 status 字段。
    若 task_id 为 None 或任务记录不存在，则静默跳过（不影响主流程）。

    Args:
        task_id: 任务唯一标识（arq job_id），为 None 时跳过。
        progress: 进度百分比（0-100）。
        message: 进度描述信息（当前未持久化，预留扩展）。
    """
    if not task_id:
        return
    try:
        async with AsyncSessionLocal() as db:
            stmt = select(TaskModel).where(TaskModel.id == task_id)
            result = await db.execute(stmt)
            task = result.scalar_one_or_none()
            if task:
                task.progress = progress
                task.status = "progress"
                await db.commit()
    except Exception as exc:
        # 进度更新失败不应影响主流程，仅记录日志
        logger.warning("更新任务进度失败", task_id=task_id, error=str(exc))


async def parse_document_impl(
    document_id: str,
    schema_id: str | None,
    term_base_id: str | None,
    ctx: dict,
) -> dict:
    """文档解析主任务（arq 异步入口）。

    接收文档标识与可选的解析模式参数，执行完整的文档解析流程：
    下载文件 -> OCR/版面识别 -> 结构化抽取 -> 术语标准化 -> 入库。

    arq 任务原生为 async 函数，与服务层异步接口直接配合，无需 ``asyncio.run``。
    进度通过更新数据库 Task 记录上报，替代 Celery 的 ``self.update_state``。

    Args:
        document_id: 待解析文档的唯一标识（UUID 字符串）。
        schema_id: 结构化抽取模式标识，None 表示跳过结构化抽取。
        term_base_id: 术语库标识，None 表示使用全量术语库。
        ctx: arq 任务上下文，包含 ``job_id`` 等元数据。

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
    )
    # 上报初始进度
    await _update_progress(task_id, 10, "开始解析")

    doc_uuid: uuid.UUID = uuid.UUID(document_id)

    try:
        async with AsyncSessionLocal() as db:
            # 加载文档记录，不存在则直接失败
            document: Document | None = await db.get(Document, doc_uuid)
            if document is None:
                raise BusinessException(
                    message=f"文档不存在: {document_id}",
                    code=ErrorCode.BUSINESS_DOCUMENT_NOT_FOUND,
                )

            # 标记为处理中
            document.status = "processing"
            await db.commit()

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
                    document.minio_object_name
                )
                logger.info(
                    "文档下载完成",
                    document_id=document_id,
                    size=len(image_bytes),
                )

                # ----------------------------------------------------------
                # 阶段 2：OCR 识别（进度 20%）
                # ----------------------------------------------------------
                await _update_progress(task_id, 20, "OCR识别中")
                ocr_result: dict = await ocr_service.recognize_with_layout(image_bytes)
                full_text: str = ocr_result.get("text", "")
                ocr_layout: list = ocr_result.get("layout", [])
                logger.info(
                    "OCR 识别完成",
                    document_id=document_id,
                    text_len=len(full_text),
                    layout_blocks=len(ocr_layout),
                )

                # ----------------------------------------------------------
                # 阶段 3：版面分析（进度 40%）
                # ----------------------------------------------------------
                await _update_progress(task_id, 40, "版面分析中")
                text_blocks: list[dict] = await layout_service.extract_text_blocks(
                    image_bytes
                )
                # 将版面分析的文本块与 OCR 版面结果合并：
                # OCR layout 携带识别文本，layout_service 提供更精细的区域置信度
                merged_layout: list[dict] = _merge_layout(ocr_layout, text_blocks)
                logger.info(
                    "版面分析完成",
                    document_id=document_id,
                    text_blocks=len(text_blocks),
                    merged_blocks=len(merged_layout),
                )

                # ----------------------------------------------------------
                # 阶段 3.5：MinerU-Popo 后处理（进度 50%）
                # ----------------------------------------------------------
                # Popo 为非关键增强步骤：失败时静默跳过，不影响主流程
                await _update_progress(task_id, 50, "文档后处理中")
                try:
                    popo_result = await popo_service.post_process(
                        image_bytes,
                        merged_layout,
                        ocr_result.get(
                            "page_size", {"width": 1240, "height": 1754}
                        ),
                    )
                    if popo_result:
                        # 使用 Popo 的标题层级和跨页合并结果增强文本
                        # 如果 Popo 返回了 enriched_text，使用它替换 full_text
                        enriched_text = popo_result.get("enriched_text")
                        if enriched_text:
                            full_text = enriched_text
                        logger.info(
                            "Popo 后处理完成",
                            document_id=document_id,
                            title_count=len(popo_result.get("title_hierarchy", [])),
                            contd_count=len(
                                popo_result.get("text_continuations", [])
                            ),
                        )
                except Exception as popo_err:
                    logger.warning(
                        "Popo 后处理失败，跳过（不影响主流程）",
                        document_id=document_id,
                        error=str(popo_err),
                    )

                # ----------------------------------------------------------
                # 阶段 4：结构化抽取（进度 60%）
                # ----------------------------------------------------------
                await _update_progress(task_id, 60, "结构化抽取中")
                structured_data: dict | None = None
                if schema_id:
                    schema_uuid: uuid.UUID = uuid.UUID(schema_id)
                    schema_config: SchemaConfig | None = await db.get(
                        SchemaConfig, schema_uuid
                    )
                    if schema_config is None:
                        raise BusinessException(
                            message=f"SchemaConfig 不存在: {schema_id}",
                            code=ErrorCode.BUSINESS_TASK_FAILED,
                        )
                    structured_data = await extraction_service.extract(
                        full_text, schema_config.schema_definition
                    )
                    logger.info(
                        "结构化抽取完成",
                        document_id=document_id,
                        schema_id=schema_id,
                        fields=len(structured_data) if structured_data else 0,
                    )
                else:
                    logger.info(
                        "未提供 schema_id，跳过结构化抽取",
                        document_id=document_id,
                    )

                # ----------------------------------------------------------
                # 阶段 5：术语标准化（进度 80%）
                # ----------------------------------------------------------
                await _update_progress(task_id, 80, "术语标准化中")
                # 将 term_base_id 转为 UUID 传入（当前版本未启用，预留供未来按库过滤）
                term_base_uuid: uuid.UUID | None = (
                    uuid.UUID(term_base_id) if term_base_id else None
                )
                standard_result: dict = await term_service.standardize_text(
                    db, full_text, term_base_uuid
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
                # 阶段 6：保存结果（进度 90%）
                # ----------------------------------------------------------
                await _update_progress(task_id, 90, "保存结果中")
                document.status = "completed"
                document.parsed_text = standardized_text
                document.structured_data = structured_data
                document.layout_data = {
                    "ocr_layout": ocr_layout,
                    "text_blocks": text_blocks,
                    "merged": merged_layout,
                    "term_replacements": replacements,
                }
                await db.commit()
                logger.info(
                    "文档解析结果已保存",
                    document_id=document_id,
                )

                # ----------------------------------------------------------
                # 阶段 7：完成（进度 100%）
                # ----------------------------------------------------------
                await _update_progress(task_id, 100, "解析完成")
                logger.info("文档解析任务完成", document_id=document_id)

                return {
                    "document_id": document_id,
                    "status": "completed",
                    "parsed_text_length": len(standardized_text),
                    "layout_blocks": len(merged_layout),
                    "structured_fields": (
                        len(structured_data) if structured_data else 0
                    ),
                    "term_replacements": len(replacements),
                }

            except Exception as exc:
                # 异常处理：标记文档为失败，回滚后写入错误状态
                logger.error(
                    "解析过程中异常，标记文档为失败",
                    document_id=document_id,
                    error=str(exc),
                )
                # 回滚事务以丢弃半成品写入，再单独提交失败状态
                await db.rollback()
                try:
                    # 重新获取文档并标记失败（rollback 后原对象已过期）
                    failed_doc: Document | None = await db.get(Document, doc_uuid)
                    if failed_doc is not None:
                        failed_doc.status = "failed"
                        await db.commit()
                except Exception as mark_err:
                    logger.error(
                        "标记文档失败状态时再次异常",
                        document_id=document_id,
                        error=str(mark_err),
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


def _merge_layout(ocr_layout: list[dict], text_blocks: list[dict]) -> list[dict]:
    """合并 OCR 版面结果与版面分析文本块。

    OCR 版面项携带识别文本，版面分析文本块携带置信度与阅读顺序。此处
    以 OCR 版面为基础，附加版面分析提供的额外区域信息，去重后返回。

    Args:
        ocr_layout: OCR 输出的版面项列表，每项含 type/bbox/text。
        text_blocks: 版面分析输出的文本块列表，每项含 type/bbox/confidence。

    Returns:
        list[dict]: 合并后的版面项列表。
    """
    merged: list[dict] = []
    seen_bbox: set[tuple[int, int, int, int]] = set()

    # 先收录 OCR 版面项（携带识别文本）
    for item in ocr_layout:
        bbox = item.get("bbox") or []
        # 将 bbox 量化为整数元组用于去重
        key = _bbox_key(bbox)
        if key in seen_bbox:
            continue
        seen_bbox.add(key)
        merged.append(item)

    # 补充版面分析中未被 OCR 覆盖的区域
    for block in text_blocks:
        bbox = block.get("bbox") or []
        key = _bbox_key(bbox)
        if key in seen_bbox:
            continue
        seen_bbox.add(key)
        merged.append(
            {
                "type": block.get("type", "text"),
                "bbox": bbox,
                "text": block.get("text", ""),
                "confidence": block.get("confidence"),
            }
        )
    return merged


def _bbox_key(bbox: list) -> tuple[int, int, int, int]:
    """将 bbox 列表转换为可哈希的整数元组，用于去重比较。

    Args:
        bbox: 坐标列表 [x1, y1, x2, y2]。

    Returns:
        tuple[int, int, int, int]: 量化后的坐标元组。
    """
    if not bbox or len(bbox) < 4:
        return (0, 0, 0, 0)
    return (int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3]))


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
