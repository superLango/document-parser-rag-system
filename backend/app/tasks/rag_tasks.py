"""RAG 知识库构建任务模块。

本模块定义 arq 异步任务，负责将文档构建为 RAG 知识库的完整流水线：

1. ``index_document_impl``：文档入库主任务，执行端到端的索引流程：
   - 从数据库加载 Document 记录
   - 获取已解析的文本（Document.parsed_text）
   - 调用结构感知分块器对文本进行章节分块
   - 使用 bge-m3 模型生成 Dense + Sparse 向量
   - 将分块与向量插入 Milvus 向量数据库
   - 更新 Document.status = "indexed"

2. ``rebuild_index_impl``：重建整个知识库索引
   - 清空 Milvus 集合
   - 遍历所有已解析文档并重新入索引

3. ``remove_document_impl``：从知识库移除指定文档
   - 按 doc_id 删除 Milvus 中的对应分块

arq 任务原生为 async 函数，与服务层异步接口完美契合，无需 ``asyncio.run`` 包装。
数据库访问直接使用 ``AsyncSessionLocal`` 上下文管理器，而非 FastAPI 的 ``get_db`` 依赖。

错误处理策略：
    索引过程中任一阶段抛出异常时，将 ``Document.status`` 置为 ``failed``，
    记录错误信息，更新任务状态为 ``failed``，并重新抛出以由 arq 标记失败。
"""

import traceback
import uuid

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.exceptions import BusinessException, ErrorCode
from app.core.logging import get_logger
from app.models.document import Document
from app.models.task import Task as TaskModel
from app.services.chunking_service import chunker
from app.services.embedding_service import embedding_service
from app.services.vector_store import vector_store

logger = get_logger(__name__)


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


async def index_document_impl(doc_id: str, ctx: dict) -> dict:
    """将文档加入知识库主任务（arq 异步入口）。

    接收文档标识，执行完整的索引构建流程：
    加载文档 → 获取解析文本 → 结构分块 → bge-m3 嵌入 → Milvus 入库。

    arq 任务原生为 async 函数，与服务层异步接口直接配合，无需 ``asyncio.run``。
    进度通过更新数据库 Task 记录上报，替代 Celery 的 ``self.update_state``。

    Args:
        doc_id: 待索引文档的唯一标识（UUID 字符串）。
        ctx: arq 任务上下文，包含 ``job_id`` 等元数据。

    Returns:
        dict: 索引结果，包含 doc_id、status、chunk_count 等摘要信息。

    Raises:
        Exception: 索引过程中任一阶段失败时重新抛出，由 arq 标记任务失败。
    """
    # 从 arq ctx 获取任务 ID，用于数据库进度更新
    task_id: str | None = ctx.get("job_id") if isinstance(ctx, dict) else None

    logger.info("开始索引文档", doc_id=doc_id, task_id=task_id)
    # 上报初始进度
    await _update_progress(task_id, 10, "开始索引")

    doc_uuid: uuid.UUID = uuid.UUID(doc_id)

    try:
        async with AsyncSessionLocal() as db:
            # 加载文档记录，不存在则直接失败
            document: Document | None = await db.get(Document, doc_uuid)
            if document is None:
                raise BusinessException(
                    message=f"文档不存在: {doc_id}",
                    code=ErrorCode.BUSINESS_DOCUMENT_NOT_FOUND,
                )

            # 校验文档已解析完成
            if not document.parsed_text:
                raise BusinessException(
                    message="文档尚未解析完成，无法索引",
                    code=ErrorCode.BUSINESS_TASK_FAILED,
                )

            try:
                # ----------------------------------------------------------
                # 阶段 1：准备文档元数据（进度 20%）
                # ----------------------------------------------------------
                await _update_progress(task_id, 20, "准备分块中")

                doc_meta: dict = {
                    "doc_id": doc_id,
                    "doc_title": document.filename or "未命名文档",
                    "file_name": document.filename or "",
                }

                # ----------------------------------------------------------
                # 阶段 2：结构感知分块（进度 40%）
                # ----------------------------------------------------------
                await _update_progress(task_id, 40, "文本分块中")
                chunks: list[dict] = await chunker.chunk_document(
                    document.parsed_text, doc_meta
                )
                if not chunks:
                    raise BusinessException(
                        message="文档分块结果为空，无法索引",
                        code=ErrorCode.BUSINESS_TASK_FAILED,
                    )
                logger.info(
                    "文本分块完成",
                    doc_id=doc_id,
                    chunk_count=len(chunks),
                )

                # ----------------------------------------------------------
                # 阶段 3：bge-m3 嵌入（进度 70%）
                # ----------------------------------------------------------
                await _update_progress(task_id, 70, "向量嵌入中")
                texts: list[str] = [c["text"] for c in chunks]
                embed_result: dict = await embedding_service.embed_documents(texts)
                dense_vectors = embed_result["dense_vectors"]
                sparse_indices = embed_result["sparse_indices"]
                logger.info(
                    "向量嵌入完成",
                    doc_id=doc_id,
                    dense_shape=str(dense_vectors.shape),
                    sparse_count=len(sparse_indices),
                )

                # ----------------------------------------------------------
                # 阶段 4：组装分块向量并插入 Milvus（进度 90%）
                # ----------------------------------------------------------
                await _update_progress(task_id, 90, "写入向量库中")
                # 将嵌入向量合并到分块字典中，满足 vector_store.insert 的字段要求
                insert_chunks: list[dict] = []
                for idx, chunk in enumerate(chunks):
                    meta = chunk["metadata"]
                    insert_chunks.append(
                        {
                            "chunk_id": chunk["chunk_id"],
                            "text": chunk["text"],
                            "dense_vector": dense_vectors[idx],
                            "sparse_vector": sparse_indices[idx],
                            "doc_id": doc_id,
                            "title_chain": meta.get("title_chain", ""),
                            "metadata": meta,
                        }
                    )
                primary_keys: list[int] = await vector_store.insert(insert_chunks)
                logger.info(
                    "向量入库完成",
                    doc_id=doc_id,
                    inserted=len(primary_keys),
                )

                # ----------------------------------------------------------
                # 阶段 5：更新文档状态为 indexed（进度 100%）
                # ----------------------------------------------------------
                document.status = "indexed"
                await db.commit()

                await _update_progress(task_id, 100, "索引完成")
                logger.info("文档索引任务完成", doc_id=doc_id, chunk_count=len(chunks))

                return {
                    "doc_id": doc_id,
                    "status": "indexed",
                    "chunk_count": len(chunks),
                    "inserted": len(primary_keys),
                }

            except Exception as exc:
                # 异常处理：标记文档为失败，回滚后写入错误状态
                logger.error(
                    "索引过程中异常，标记文档为失败",
                    doc_id=doc_id,
                    error=str(exc),
                )
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
                        doc_id=doc_id,
                        error=str(mark_err),
                    )
                raise

    except Exception as exc:
        # 记录完整错误堆栈，便于排障
        logger.error(
            "文档索引任务失败",
            doc_id=doc_id,
            error=str(exc),
            traceback=traceback.format_exc(),
        )
        raise


async def rebuild_index_impl(ctx: dict) -> dict:
    """重建整个知识库索引（arq 异步入口）。

    处理流程：
        1. 清空 Milvus 集合（删除所有分块）
        2. 查询所有已解析（completed / indexed）的文档
        3. 逐个重新索引

    Args:
        ctx: arq 任务上下文，包含 ``job_id`` 等元数据。

    Returns:
        dict: 重建结果，包含 total_docs、success_count、failed_count。
    """
    # 从 arq ctx 获取任务 ID，用于数据库进度更新
    task_id: str | None = ctx.get("job_id") if isinstance(ctx, dict) else None

    logger.info("开始重建知识库索引", task_id=task_id)
    try:
        # 阶段 1：清空 Milvus 集合
        logger.info("清空 Milvus 集合")
        await vector_store.delete_all()

        # 阶段 2：查询所有已解析文档
        async with AsyncSessionLocal() as db:
            stmt = select(Document).where(
                Document.status.in_(["completed", "indexed"])
            )
            result = await db.execute(stmt)
            documents: list[Document] = list(result.scalars().all())

        total_docs: int = len(documents)
        success_count: int = 0
        failed_count: int = 0
        failed_docs: list[str] = []

        logger.info("开始逐一重建索引", total_docs=total_docs)

        # 阶段 3：逐个重建索引
        for doc in documents:
            doc_id_str = str(doc.id)
            try:
                # 复用 index_document_impl 完成单文档索引
                # 传入空 ctx 以跳过进度上报（重建过程不单独更新进度）
                await index_document_impl(doc_id_str, {})
                success_count += 1
                logger.info(
                    "文档重建索引成功",
                    doc_id=doc_id_str,
                    progress=f"{success_count}/{total_docs}",
                )
            except Exception as exc:
                failed_count += 1
                failed_docs.append(doc_id_str)
                logger.error(
                    "文档重建索引失败",
                    doc_id=doc_id_str,
                    error=str(exc),
                )

        logger.info(
            "知识库重建完成",
            total_docs=total_docs,
            success_count=success_count,
            failed_count=failed_count,
        )
        return {
            "total_docs": total_docs,
            "success_count": success_count,
            "failed_count": failed_count,
            "failed_docs": failed_docs,
        }
    except Exception as exc:
        logger.error(
            "知识库重建任务失败",
            error=str(exc),
            traceback=traceback.format_exc(),
        )
        raise


async def remove_document_impl(doc_id: str, ctx: dict) -> dict:
    """从知识库移除文档（arq 异步入口）。

    按 ``doc_id`` 删除 Milvus 中该文档的所有分块向量。
    不删除 Document 数据库记录本身（由文档管理端点负责）。

    Args:
        doc_id: 待移除文档的唯一标识（UUID 字符串）。
        ctx: arq 任务上下文，包含 ``job_id`` 等元数据。

    Returns:
        dict: 移除结果，包含 doc_id 与状态。
    """
    logger.info("从知识库移除文档", doc_id=doc_id)
    try:
        await vector_store.delete_by_doc_id(doc_id)
        logger.info("文档已从知识库移除", doc_id=doc_id)
        return {"doc_id": doc_id, "status": "removed"}
    except Exception as exc:
        logger.error(
            "移除文档失败",
            doc_id=doc_id,
            error=str(exc),
            traceback=traceback.format_exc(),
        )
        raise
