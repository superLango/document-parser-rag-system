"""RAG向量索引 + 图谱构建任务（"构建图谱"按钮触发）。"""

import traceback
import uuid
from pathlib import Path
from app.core.logging import get_logger
from app.core.database import AsyncSessionLocal
from app.models.document import Document

logger = get_logger(__name__)


async def build_index_graph_impl(document_id: str, kb_id: str | None, ctx: dict) -> dict:
    """构建RAG向量索引和图谱。

    流程：
    1. 加载Popo child_chunks和document.parsed_text
    2. RAG向量索引：Popo child_chunks入chunk_vector_store（dense+sparse）
    3. 图谱构建：用parsed_text调用entity_extractor做LLM实体抽取→写入NebulaGraph

    RAG索引用Popo chunks（含overlap），图谱用parsed_text（OCR纯文本）+ LLM实体抽取。
    图谱构建失败不阻断RAG索引。

    Args:
        document_id: 文档唯一标识（UUID字符串）。
        kb_id: 知识库 ID 字符串，None 表示全局模式。
        ctx: arq 任务上下文，包含 ``job_id`` 等元数据。

    Returns:
        dict: 构建结果摘要。

    Raises:
        Exception: 构建过程中失败时重新抛出。
    """
    from app.tasks.document_tasks import _activate_kb_rls, _update_progress, _update_task_status

    arq_job_id = ctx.get("job_id") if isinstance(ctx, dict) else None

    doc_uuid: uuid.UUID = uuid.UUID(document_id)

    logger.info(
        "开始构建RAG索引和图谱",
        document_id=document_id,
        kb_id=kb_id,
        arq_job_id=arq_job_id,
    )

    try:
        async with AsyncSessionLocal() as db:
            await _activate_kb_rls(db, kb_id)
            document = await db.get(Document, doc_uuid)
            if not document:
                raise Exception(f"文档不存在: {document_id}")
            if document.status != "completed":
                raise Exception(f"文档未完成解析，当前状态: {document.status}")
            document.index_status = "indexing"
            await db.commit()
            # 从layout_data中获取OCR输出目录（包含task_id）
            layout_data = document.layout_data or {}
            ocr_output_dir = layout_data.get("output_dir", "")

        await _update_progress(arq_job_id, 10, "构建RAG向量索引", kb_id=kb_id)

        from app.services.vector.chunk_vector_store import chunk_vector_store
        import json as _json

        child_chunks: list = []
        # 从OCR输出目录查找child_chunks.json
        if ocr_output_dir:
            chunks_path = Path(ocr_output_dir) / "child_chunks.json"
            if not chunks_path.exists():
                # fallback: 尝试task_dir（兼容旧路径）
                from app.services.vector.reconstruction_service import reconstruction_service
                chunks_path = reconstruction_service._get_task_dir(
                    Path(ocr_output_dir).name if ocr_output_dir else document_id,
                    kb_id=kb_id,
                ) / "child_chunks.json"
        else:
            # 无output_dir时从kb目录下按document查找
            chunks_path = None
            kb_base = Path("data/ocr_data") / (kb_id or "")
            if kb_base.exists():
                for task_dir in kb_base.iterdir():
                    if task_dir.is_dir() and (task_dir / "child_chunks.json").exists():
                        # 检查source.pdf的mtime或merged.json是否属于该文档（简化：取最新的）
                        chunks_path = task_dir / "child_chunks.json"
                        break

        if chunks_path and chunks_path.exists():
            with chunks_path.open("r", encoding="utf-8") as f:
                child_chunks = _json.load(f)
            logger.info(
                "从child_chunks.json加载子块",
                document_id=document_id,
                chunk_count=len(child_chunks),
                path=str(chunks_path),
            )
        else:
            logger.warning("未找到child_chunks.json，跳过RAG向量索引", document_id=document_id)

        if child_chunks:
            await chunk_vector_store.insert_chunks_from_popochunks(
                child_chunks, document_id, kb_id=kb_id
            )

        await _update_progress(arq_job_id, 50, "构建图谱中", kb_id=kb_id)

        graph_status = "completed"
        graph_error = None
        try:
            from app.services.graph.entity_extractor import graph_entity_extractor
            from app.services.graph.graph_store import graph_store

            async with AsyncSessionLocal() as db:
                await _activate_kb_rls(db, kb_id)
                document = await db.get(Document, doc_uuid)
                parsed_text = document.parsed_text if document else ""

            if parsed_text:
                entities, relations = await graph_entity_extractor.extract_entities_and_relations(
                    parsed_text, doc_id=document_id, kb_id=kb_id
                )
                await graph_store.insert_document_graph(document_id, kb_id, entities, relations)
                logger.info(
                    "图谱构建完成",
                    document_id=document_id,
                    entities=len(entities),
                    relations=len(relations),
                )
        except Exception as ge:
            logger.warning(
                "图谱构建失败（不阻断RAG索引）",
                document_id=document_id,
                error=str(ge),
            )
            graph_status = "failed"
            graph_error = str(ge)

        await _update_progress(arq_job_id, 90, "保存状态", kb_id=kb_id)

        async with AsyncSessionLocal() as db:
            await _activate_kb_rls(db, kb_id)
            document = await db.get(Document, doc_uuid)
            if document:
                document.index_status = "completed"  # RAG向量索引已完成
                document.graph_status = graph_status
                if graph_error:
                    document.graph_error = graph_error[:500]
                await db.commit()

        await _update_progress(arq_job_id, 100, "构建完成", kb_id=kb_id)
        await _update_task_status(arq_job_id, "completed", kb_id=kb_id)

        logger.info(
            "RAG索引和图谱构建完成",
            document_id=document_id,
            graph_status=graph_status,
        )

        return {
            "status": "completed",
            "document_id": document_id,
            "graph_status": graph_status,
        }

    except Exception as e:
        logger.error(
            "构建索引/图谱失败",
            document_id=document_id,
            error=str(e),
            traceback=traceback.format_exc(),
        )
        try:
            async with AsyncSessionLocal() as db:
                await _activate_kb_rls(db, kb_id)
                document = await db.get(Document, doc_uuid)
                if document:
                    document.index_status = "failed"
                    document.graph_status = "failed"
                    document.graph_error = str(e)[:500]
                    await db.commit()
        except Exception:
            pass
        await _update_task_status(arq_job_id, "failed", str(e), kb_id=kb_id)
        raise
