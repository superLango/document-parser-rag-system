"""结构化抽取异步任务模块。

定义 arq 异步任务：
1. ``extract_document_impl``：文档结构化抽取主任务（"抽取"按钮触发）
2. ``extract_v3_impl``：旧版v3抽取入口（向后兼容，转发到extract_document_impl）

前置条件：
    - 文档已通过 OCR + Popo 层级重建 + 五维向量入库（``reconstruction_service``）
    - 基础表已同步到 PostgreSQL + Milvus（``sync_project_dict_task``）
"""

import traceback
import uuid

from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.models.document import Document
from app.services.extraction.extraction_pipeline import extraction_pipeline

logger = get_logger(__name__)


async def extract_document_impl(document_id: str, kb_id: str | None, ctx: dict) -> dict:
    """文档结构化抽取任务（arq异步入口，"抽取"按钮触发）。

    前置条件：document.status == "completed"（已完成OCR+Popo+五维入库）

    Args:
        document_id: 文档唯一标识（UUID字符串）。
        kb_id: 知识库 ID 字符串，None 表示全局模式。
        ctx: arq 任务上下文，包含 ``job_id`` 等元数据。

    Returns:
        dict: 抽取结果摘要。

    Raises:
        Exception: 抽取过程中失败时重新抛出。
    """
    from app.tasks.document_tasks import _activate_kb_rls, _update_progress, _update_task_status

    arq_job_id = ctx.get("job_id") if isinstance(ctx, dict) else None

    logger.info(
        "开始结构化抽取",
        document_id=document_id,
        kb_id=kb_id,
        arq_job_id=arq_job_id,
    )

    try:
        doc_uuid = uuid.UUID(document_id)

        async with AsyncSessionLocal() as db:
            await _activate_kb_rls(db, kb_id)
            document = await db.get(Document, doc_uuid)
            if not document:
                raise Exception(f"文档不存在: {document_id}")
            if document.status != "completed":
                raise Exception(f"文档未完成解析，当前状态: {document.status}")

        await _update_progress(arq_job_id, 10, "开始抽取", kb_id=kb_id)

        result = await extraction_pipeline.run(
            task_id=arq_job_id or document_id,
            doc_id=document_id,
            kb_id=kb_id,
        )

        await _update_progress(arq_job_id, 80, "保存抽取结果", kb_id=kb_id)

        async with AsyncSessionLocal() as db:
            await _activate_kb_rls(db, kb_id)
            document = await db.get(Document, doc_uuid)
            if document:
                records = []
                if hasattr(result, 'categories'):
                    for cat in result.categories:
                        if hasattr(cat, 'records'):
                            for r in cat.records:
                                if isinstance(r, dict):
                                    records.append(r)
                                elif hasattr(r, 'model_dump'):
                                    records.append(r.model_dump())
                                elif hasattr(r, '__dict__'):
                                    records.append(r.__dict__)
                                else:
                                    records.append(r)
                    if hasattr(result, 'heat_treatment') and hasattr(result.heat_treatment, 'records'):
                        for r in result.heat_treatment.records:
                            if isinstance(r, dict):
                                records.append(r)
                            elif hasattr(r, 'model_dump'):
                                records.append(r.model_dump())
                            elif hasattr(r, '__dict__'):
                                records.append(r.__dict__)
                            else:
                                records.append(r)
                elif hasattr(result, 'records'):
                    records = []
                    for r in result.records:
                        if isinstance(r, dict):
                            records.append(r)
                        elif hasattr(r, 'model_dump'):
                            records.append(r.model_dump())
                        elif hasattr(r, '__dict__'):
                            records.append(r.__dict__)
                        else:
                            records.append(r)

                document.structured_data = {
                    "records": records,
                    "doc_info": result.doc_info if hasattr(result, 'doc_info') else None,
                    "summary": result.summary if hasattr(result, 'summary') else {},
                    "timing": result.timing if hasattr(result, 'timing') else {},
                }
                if hasattr(document, 'extraction_status'):
                    document.extraction_status = "completed"
                await db.commit()

        await _update_progress(arq_job_id, 100, "抽取完成", kb_id=kb_id)
        await _update_task_status(arq_job_id, "completed", kb_id=kb_id)

        logger.info(
            "结构化抽取完成",
            document_id=document_id,
            total_records=result.summary.get("total_records", 0) if hasattr(result, 'summary') else 0,
            total_elapsed=result.timing.get("total", 0) if hasattr(result, 'timing') else 0,
        )

        return {
            "document_id": document_id,
            "status": "completed",
            "total_records": result.summary.get("total_records", 0) if hasattr(result, 'summary') else 0,
            "timing": result.timing if hasattr(result, 'timing') else {},
        }

    except Exception as exc:
        logger.error(
            "结构化抽取失败",
            document_id=document_id,
            error=str(exc),
            traceback=traceback.format_exc(),
        )
        try:
            async with AsyncSessionLocal() as db:
                await _activate_kb_rls(db, kb_id)
                document = await db.get(Document, doc_uuid)
                if document and hasattr(document, 'extraction_status'):
                    document.extraction_status = "failed"
                    await db.commit()
        except Exception:
            pass
        await _update_task_status(arq_job_id, "failed", str(exc), kb_id=kb_id)
        raise


async def extract_v3_impl(task_id: str, ctx: dict) -> dict:
    """v3 结构化抽取任务（向后兼容入口，转发到extract_document_impl）。

    Args:
        task_id: 任务 ID（即文档ID）。
        ctx: arq 任务上下文。

    Returns:
        dict: 抽取结果摘要。
    """
    return await extract_document_impl(task_id, None, ctx)
