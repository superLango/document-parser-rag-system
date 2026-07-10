"""RAG 知识库构建任务模块。

本模块定义 Celery 异步任务，负责将文档构建为 RAG 知识库的完整流水线：

1. ``index_document``：文档入库主任务，执行端到端的索引流程：
   - 从数据库加载 Document 记录
   - 获取已解析的文本（Document.parsed_text）
   - 调用结构感知分块器对文本进行章节分块
   - 使用 bge-m3 模型生成 Dense + Sparse 向量
   - 将分块与向量插入 Milvus 向量数据库
   - 更新 Document.status = "indexed"

2. ``rebuild_index``：重建整个知识库索引
   - 清空 Milvus 集合
   - 遍历所有已解析文档并重新入索引

3. ``remove_document``：从知识库移除指定文档
   - 按 doc_id 删除 Milvus 中的对应分块

异步处理说明：
    Celery 任务本身为同步函数，而项目中的服务（分块 / 嵌入 / 向量库）
    均为异步接口。本模块通过 ``asyncio.run`` 在同步任务内启动事件循环，
    并定义内部 async 函数执行实际工作。数据库访问直接使用
    ``AsyncSessionLocal`` 上下文管理器，而非 FastAPI 的 ``get_db`` 依赖。

错误处理策略：
    索引过程中任一阶段抛出异常时，将 ``Document.status`` 置为 ``failed``，
    记录错误信息，更新任务状态为 ``FAILURE``，并重新抛出以由 Celery 标记失败。
"""

import asyncio
import traceback
import uuid

from celery import Task
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.exceptions import BusinessException, ErrorCode
from app.core.logging import get_logger
from app.models.document import Document
from app.services.chunking_service import chunker
from app.services.embedding_service import embedding_service
from app.services.vector_store import vector_store
from app.tasks.celery_app import celery_app

logger = get_logger(__name__)


@celery_app.task(bind=True, name="rag.index_document")
def index_document(self: Task, doc_id: str) -> dict:
    """将文档加入知识库主任务。

    接收文档标识，执行完整的索引构建流程：
    加载文档 → 获取解析文本 → 结构分块 → bge-m3 嵌入 → Milvus 入库。

    由于 Celery 任务为同步函数，而服务层均为异步接口，此处通过
    ``asyncio.run`` 启动事件循环执行内部 async 逻辑。

    Args:
        self: Celery 任务实例（bind=True 绑定）。
        doc_id: 待索引文档的唯一标识（UUID 字符串）。

    Returns:
        dict: 索引结果，包含 doc_id、status、chunk_count 等摘要信息。

    Raises:
        Exception: 索引过程中任一阶段失败时重新抛出，由 Celery 标记任务失败。
    """
    logger.info("开始索引文档", doc_id=doc_id)
    # 上报初始进度
    self.update_state(state="PROGRESS", meta={"progress": 10, "message": "开始索引"})

    try:
        result = asyncio.run(_index_document_async(self, doc_id))
        return result
    except Exception as exc:
        # 记录完整错误堆栈，便于排障
        logger.error(
            "文档索引任务失败",
            doc_id=doc_id,
            error=str(exc),
            traceback=traceback.format_exc(),
        )
        # 更新任务状态为 FAILURE，供前端轮询感知
        self.update_state(
            state="FAILURE",
            meta={"error": str(exc), "message": "索引失败"},
        )
        raise


async def _index_document_async(task: Task, doc_id: str) -> dict:
    """文档索引的异步实现。

    在独立的 ``AsyncSessionLocal`` 会话中执行完整索引流水线，确保事务边界
    由本函数统一控制。任一阶段失败时将 Document 状态置为 failed 并回滚。

    Args:
        task: Celery 任务实例，用于上报进度。
        doc_id: 文档 UUID 字符串。

    Returns:
        dict: 索引结果摘要。

    Raises:
        Exception: 索引失败时重新抛出，由上层 ``index_document`` 处理。
    """
    doc_uuid: uuid.UUID = uuid.UUID(doc_id)

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
            task.update_state(
                state="PROGRESS",
                meta={"progress": 20, "message": "准备分块中"},
            )

            doc_meta: dict = {
                "doc_id": doc_id,
                "doc_title": document.filename or "未命名文档",
                "file_name": document.filename or "",
            }

            # ----------------------------------------------------------
            # 阶段 2：结构感知分块（进度 40%）
            # ----------------------------------------------------------
            task.update_state(
                state="PROGRESS",
                meta={"progress": 40, "message": "文本分块中"},
            )
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
            task.update_state(
                state="PROGRESS",
                meta={"progress": 70, "message": "向量嵌入中"},
            )
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
            task.update_state(
                state="PROGRESS",
                meta={"progress": 90, "message": "写入向量库中"},
            )
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

            task.update_state(
                state="PROGRESS",
                meta={"progress": 100, "message": "索引完成"},
            )
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


@celery_app.task(name="rag.rebuild_index")
def rebuild_index() -> dict:
    """重建整个知识库索引。

    处理流程：
        1. 清空 Milvus 集合（删除所有分块）
        2. 查询所有已解析（completed / indexed）的文档
        3. 逐个重新索引

    Returns:
        dict: 重建结果，包含 total_docs、success_count、failed_count。
    """
    logger.info("开始重建知识库索引")
    try:
        result = asyncio.run(_rebuild_index_async())
        return result
    except Exception as exc:
        logger.error(
            "知识库重建任务失败",
            error=str(exc),
            traceback=traceback.format_exc(),
        )
        raise


async def _rebuild_index_async() -> dict:
    """知识库重建的异步实现。

    先清空 Milvus 集合，再遍历所有已完成解析的文档逐一索引。

    Returns:
        dict: 重建结果摘要。
    """
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
            # 复用 _index_document_async 完成单文档索引
            await _index_document_async(rebuild_index, doc_id_str)
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


@celery_app.task(name="rag.remove_document")
def remove_document(doc_id: str) -> dict:
    """从知识库移除文档。

    按 ``doc_id`` 删除 Milvus 中该文档的所有分块向量。
    不删除 Document 数据库记录本身（由文档管理端点负责）。

    Args:
        doc_id: 待移除文档的唯一标识（UUID 字符串）。

    Returns:
        dict: 移除结果，包含 doc_id 与状态。
    """
    logger.info("从知识库移除文档", doc_id=doc_id)
    try:
        result = asyncio.run(_remove_document_async(doc_id))
        return result
    except Exception as exc:
        logger.error(
            "移除文档失败",
            doc_id=doc_id,
            error=str(exc),
            traceback=traceback.format_exc(),
        )
        raise


async def _remove_document_async(doc_id: str) -> dict:
    """文档移除的异步实现。

    Args:
        doc_id: 文档 UUID 字符串。

    Returns:
        dict: 移除结果摘要。
    """
    await vector_store.delete_by_doc_id(doc_id)
    logger.info("文档已从知识库移除", doc_id=doc_id)
    return {"doc_id": doc_id, "status": "removed"}
