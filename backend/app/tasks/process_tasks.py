"""一体化文档处理编排任务。

将 OCR（含 Popo 重建 + 五维向量入库）与结构化抽取串联为单一后台任务，
支撑公开一体化接口（上传 PDF → 异步 OCR+抽取 → 凭 task_id 查状态/取结果）。

编排策略：
- 复用 ``parse_document_impl``（阶段1：OCR + 向量入库）与 ``extract_document_impl``
  （阶段2：结构化抽取），不重复实现解析/抽取逻辑。
- 全程更新 ``Document.process_status`` 表达一体化流程状态，独立于 ``Task.status``。
  原因：``parse_document_impl`` 在 OCR 完成时会把 ``Task.status`` 置为 completed，
  ``extract_document_impl`` 又会改回 running，导致 Task.status 抖动；状态查询接口
  读 ``Document.process_status`` 避免抖动。

两个 impl 都只用 ``ctx.get("job_id")`` 取 task_id，编排任务构造
``ctx={"job_id": arq_job_id}`` 即可直接 await 串联。
"""

import traceback
import uuid

from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.models.document import Document

logger = get_logger(__name__)


async def process_document_impl(document_id: str, kb_id: str, ctx: dict) -> dict:
    """一体化编排：OCR+向量入库 → 结构化抽取。

    Args:
        document_id: 文档唯一标识（UUID 字符串）。
        kb_id: 知识库 ID 字符串（KB 隔离 + 抽取配置来源）。
        ctx: arq 任务上下文，需包含 ``job_id``（用作 OCR 输出目录名与进度更新 key）。

    Returns:
        dict: 编排结果摘要。

    Raises:
        Exception: OCR 或抽取任一阶段失败时重新抛出（由 arq 标记任务失败）。
    """
    # 延迟导入避免循环依赖（document_tasks/extraction_tasks 反向引用本模块的情况）
    from app.tasks.document_tasks import _activate_kb_rls, parse_document_impl
    from app.tasks.extraction_tasks import extract_document_impl

    arq_job_id = ctx.get("job_id") if isinstance(ctx, dict) else None
    doc_uuid = uuid.UUID(document_id)

    logger.info(
        "一体化编排任务开始",
        document_id=document_id,
        kb_id=kb_id,
        arq_job_id=arq_job_id,
    )

    async def _set_process_status(status: str) -> None:
        """在独立会话中更新 Document.process_status（激活 RLS）。"""
        try:
            async with AsyncSessionLocal() as db:
                await _activate_kb_rls(db, kb_id)
                doc = await db.get(Document, doc_uuid)
                if doc is not None:
                    doc.process_status = status
                    await db.commit()
        except Exception as exc:
            logger.warning(
                "更新 process_status 失败",
                document_id=document_id,
                status=status,
                error=str(exc),
            )

    try:
        # ── 阶段1：OCR + Popo 重建 + 五维向量入库 ──
        # parse_document_impl 内部已调用 reconstruction_service.reconstruct(build_vector_index=True)，
        # 完成后 document.status == "completed"、index_status == "completed"。
        await _set_process_status("ocr_processing")
        await parse_document_impl(document_id, None, None, ctx, kb_id=kb_id)

        # ── 阶段2：结构化抽取 ──
        # extract_document_impl 前置条件：document.status == "completed"（阶段1已满足）。
        # 结果落库到 document.structured_data.latest_result。
        await _set_process_status("extracting")
        extract_result = await extract_document_impl(document_id, kb_id, ctx)

        await _set_process_status("completed")
        logger.info(
            "一体化编排任务完成",
            document_id=document_id,
            kb_id=kb_id,
            total_records=(
                extract_result.get("total_records") if isinstance(extract_result, dict) else None
            ),
        )
        return {
            "document_id": document_id,
            "status": "completed",
            "total_records": extract_result.get("total_records") if isinstance(extract_result, dict) else None,
        }

    except Exception as exc:
        logger.error(
            "一体化编排任务失败",
            document_id=document_id,
            kb_id=kb_id,
            error=str(exc),
            traceback=traceback.format_exc(),
        )
        await _set_process_status("failed")
        raise


async def process_document_task(ctx: dict, document_id: str, kb_id: str) -> dict:
    """一体化文档处理任务（arq 入口）。

    Args:
        ctx: arq 任务上下文（含 job_id）。
        document_id: 文档唯一标识。
        kb_id: 知识库 ID 字符串。
    """
    return await process_document_impl(document_id, kb_id, ctx)
