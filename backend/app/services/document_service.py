"""文档服务：上传记录、任务/Outbox、parsekit 解析流水线、删除与重解析。"""

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.document import Document, DocumentTask, TaskDeadLetter, TaskOutbox
from app.services import storage
from app.services.parsekit import ParseOptions, parse_pdf

logger = get_logger(__name__)

PARSE_STAGES = ["rendering", "layout", "ocr", "rebuild"]
INDEX_STAGES = ["chunking", "embedding", "storing"]
INDEX_TASK_TYPE = "document_index"
PARSE_TASK_TYPE = "document_parse"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ocr_base_from_object_key(object_key: str) -> str | None:
    """从原始对象键推导 ocr 产物目录前缀。"""
    parts = object_key.split("/")
    if len(parts) >= 4 and parts[1] == "originals":
        return f"{parts[0]}/ocr/{parts[2]}/"
    return None


def _ocr_base_from_document(document) -> str | None:
    """推导文档 ocr 产物目录前缀（优先用文档自身产物路径，其次回退对象键）。

    注意：originals/{上传任务id} 与 ocr/{解析任务id} 可能不是同一个 id
    （一站式对接上传时 originals 路径用的是对接任务 id，解析任务另建 task_id），
    因此必须以 layout_path / markdown_path 所在目录为准，否则页面预览取不到图。
    """
    for path in (
        getattr(document, "layout_path", None),
        getattr(document, "markdown_path", None),
    ):
        if path and "/ocr/" in path:
            return path.rsplit("/", 1)[0] + "/"
    return _ocr_base_from_object_key(document.object_key)


def _artifact_keys(kb_id: uuid.UUID, task_id: str) -> dict:
    base = f"kb-{kb_id.hex}/ocr/{task_id}"
    return {
        "base": base,
        "markdown": f"{base}/result.md",
        "layout": f"{base}/layout.json",
    }


async def create_document(
    db: AsyncSession,
    kb_id: uuid.UUID,
    *,
    filename: str,
    file_type: str | None,
    file_size: int,
    sha256: str,
    object_key: str,
    task_id: str | None = None,
) -> tuple[Document, DocumentTask]:
    task_id = task_id or str(uuid.uuid4())
    document = Document(
        kb_id=kb_id,
        filename=filename,
        file_type=file_type,
        file_size=file_size,
        object_key=object_key,
        sha256=sha256,
        status="queued",
        process_status="queued",
    )
    db.add(document)
    await db.flush()
    task = DocumentTask(
        kb_id=kb_id,
        document_id=document.id,
        task_id=task_id,
        type="document_parse",
        status="queued",
        checkpoint={},
    )
    db.add(task)
    # 上传仅登记任务，不写 outbox；由 start_document_parse 手动触发解析
    await db.commit()
    await db.refresh(document)
    await db.refresh(task)
    return document, task


async def start_document_parse(
    db: AsyncSession,
    kb_id: uuid.UUID,
    document_id: uuid.UUID,
) -> DocumentTask:
    """手动开始解析（上传后默认待解析；行内“开始解析”触发）。

    幂等：同一文档只允许一个 queued 任务存在，重复调用返回现有 queued 任务。
    """
    from app.core.exceptions import BusinessException, ErrorCode

    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
        {"key": f"start-parse:{document_id}"},
    )
    document = (
        await db.execute(
            select(Document)
            .where(
                Document.id == document_id,
                Document.kb_id == kb_id,
                Document.deleted_at.is_(None),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if document is None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_NOT_FOUND, message="文档不存在"
        )
    active_task = (
        await db.execute(
            select(DocumentTask)
            .where(
                DocumentTask.document_id == document_id,
                DocumentTask.type == PARSE_TASK_TYPE,
                DocumentTask.status.in_(("queued", "running")),
            )
            .order_by(DocumentTask.created_at.desc())
            .limit(1)
        )
    ).scalars().first()

    if active_task is not None:
        outbox = (
            await db.execute(
                select(TaskOutbox).where(TaskOutbox.task_id == active_task.task_id)
            )
        ).scalar_one_or_none()

        if active_task.status == "queued":
            if outbox is None:
                # 上传创建的任务可能尚未写 outbox，补写后返回
                db.add(
                    TaskOutbox(
                        task_id=active_task.task_id,
                        type=PARSE_TASK_TYPE,
                        payload={
                            "document_id": str(document.id),
                            "kb_id": str(kb_id),
                        },
                        status="pending",
                    )
                )
                await db.commit()
                return active_task
            if outbox.status in ("pending", "claimed"):
                # 派发器（每 TASK_DISPATCH_INTERVAL_SECONDS 秒）即将处理
                return active_task
            if outbox.status == "done":
                # 作业已完成但任务未收尾（历史上 run_parse_task 取错行导致）：关闭僵尸任务后重建
                logger.warning(
                    "关闭僵尸解析任务并重建",
                    task_id=active_task.task_id,
                    document_id=str(document_id),
                )
                active_task.status = "completed"
                active_task.updated_at = _now()
                await db.flush()
            elif outbox.status == "enqueued":
                enqueued_at = outbox.enqueued_at
                waited = (
                    (_now() - enqueued_at).total_seconds()
                    if enqueued_at is not None
                    else float("inf")
                )
                retry_after = max(10, int(settings.PARSE_DISPATCH_RETRY_AFTER_SECONDS))
                if waited < retry_after:
                    return active_task
                # 已派发但 worker 从未认领（任务仍是 queued）→ 重置为 pending 让派发器重投
                logger.warning(
                    "解析任务派发超时，重置 outbox 等待重投",
                    task_id=active_task.task_id,
                    document_id=str(document_id),
                    waited_seconds=round(waited, 1),
                )
                outbox.status = "pending"
                outbox.enqueued_at = None
                await db.commit()
                return active_task
            else:
                return active_task
        else:  # running
            heartbeat = active_task.heartbeat_at
            idle = (
                (_now() - heartbeat).total_seconds()
                if heartbeat is not None
                else float("inf")
            )
            if idle < max(60, int(settings.TASK_STUCK_REAPER_SECONDS)):
                raise BusinessException(
                    code=ErrorCode.BUSINESS_NOT_FOUND,
                    message="文档正在解析中，请稍后重试",
                )
            # 心跳超时的僵尸 running 任务：关闭后重建
            logger.warning(
                "解析任务心跳超时，关闭僵尸任务并重建",
                task_id=active_task.task_id,
                document_id=str(document_id),
                idle_seconds=round(idle, 1),
            )
            active_task.status = "failed"
            active_task.error = {"message": "解析任务心跳超时，已由重解析重建"}
            await db.flush()

    task = DocumentTask(
        kb_id=kb_id,
        document_id=document.id,
        task_id=str(uuid.uuid4()),
        type="document_parse",
        status="queued",
        checkpoint={},
    )
    db.add(task)
    await db.flush()
    db.add(
        TaskOutbox(
            task_id=task.task_id,
            type="document_parse",
            payload={
                "document_id": str(document.id),
                "kb_id": str(kb_id),
            },
            status="pending",
        )
    )
    await db.commit()
    await db.refresh(task)
    return task


async def reset_document_for_reparse(
    db: AsyncSession,
    kb_id: uuid.UUID,
    document_id: uuid.UUID,
    task_id: str,
) -> tuple[Document, DocumentTask]:
    """重置文档并创建新解析任务（幂等：咨询锁 + 活动任务检查）。"""
    from app.core.exceptions import BusinessException, ErrorCode

    # 咨询锁串行化同一文档的重解析，避免并发创建两个任务
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
        {"key": f"reparse:{document_id}"},
    )
    document = (
        await db.execute(
            select(Document)
            .where(
                Document.id == document_id,
                Document.kb_id == kb_id,
                Document.deleted_at.is_(None),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if document is None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_NOT_FOUND, message="文档不存在"
        )
    active = (
        await db.execute(
            select(func.count())
            .select_from(DocumentTask)
            .where(
                DocumentTask.document_id == document_id,
                DocumentTask.status.in_(("queued", "running")),
            )
        )
    ).scalar_one()
    if active > 0:
        raise BusinessException(
            code=ErrorCode.BUSINESS_NOT_FOUND,
            message="文档已有解析任务进行中，请稍后重试",
        )

    document.status = "queued"
    document.process_status = "queued"
    document.progress_page = None
    document.progress_total = None
    document.page_count = 0
    document.markdown_path = None
    document.layout_path = None
    document.error = None
    document.updated_at = _now()
    task = DocumentTask(
        kb_id=kb_id,
        document_id=document.id,
        task_id=task_id,
        type="document_parse",
        status="queued",
        checkpoint={},
    )
    db.add(task)
    # 上传仅登记任务，不写 outbox；由 start_document_parse 手动触发解析
    await db.commit()
    await db.refresh(document)
    await db.refresh(task)
    return document, task


async def list_documents(
    db: AsyncSession,
    kb_id: uuid.UUID,
    keyword: str | None,
    page: int,
    page_size: int,
) -> tuple[list[Document], int]:
    base = select(Document).where(Document.kb_id == kb_id, Document.deleted_at.is_(None))
    count_base = (
        select(func.count())
        .select_from(Document)
        .where(Document.kb_id == kb_id, Document.deleted_at.is_(None))
    )
    if keyword:
        like = f"%{keyword}%"
        cond = or_(Document.filename.ilike(like), Document.sha256.ilike(like))
        base = base.where(cond)
        count_base = count_base.where(cond)
    total = (await db.execute(count_base)).scalar_one()
    rows = (
        await db.execute(
            base.order_by(Document.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()
    return list(rows), total


async def get_document(
    db: AsyncSession, kb_id: uuid.UUID, document_id: uuid.UUID
) -> Document:
    doc = (
        await db.execute(
            select(Document).where(
                Document.id == document_id,
                Document.kb_id == kb_id,
                Document.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if doc is None:
        from app.core.exceptions import BusinessException, ErrorCode

        raise BusinessException(
            code=ErrorCode.BUSINESS_NOT_FOUND, message="文档不存在"
        )
    return doc


async def get_page_image(
    db: AsyncSession,
    kb_id: uuid.UUID,
    document_id: uuid.UUID,
    page_index: int,
) -> bytes:
    """读取页面预览 PNG（Phase 4；已清理/越界时抛业务异常）。"""
    from app.core.exceptions import BusinessException, ErrorCode, ValidationException

    document = await get_document(db, kb_id, document_id)
    if document.pages_cleaned_at is not None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_NOT_FOUND,
            message="页面中间产物已按保留策略清理",
        )
    if page_index < 1 or page_index > document.page_count:
        raise ValidationException(message="页码越界")
    base = _ocr_base_from_document(document)
    if not base:
        raise ValidationException(message="页面产物路径缺失")
    key = f"{base}pages/page-{page_index:04d}.png"
    try:
        return storage.get_object(key)
    except Exception as exc:
        raise ValidationException(message="页面图片不存在或已清理") from exc


async def cleanup_expired_pages(
    db: AsyncSession,
    retention_days: int | None = None,
) -> int:
    """U14：清理超过保留期的 pages 中间产物（保留 result.md/layout.json）。"""
    from app.core.config import settings

    days = (
        settings.PARSEKIT_INTERMEDIATE_RETENTION_DAYS
        if retention_days is None
        else retention_days
    )
    if days <= 0:
        raise ValueError("中间产物保留天数必须大于 0")
    cutoff = _now() - timedelta(days=days)
    rows = (
        await db.execute(
            select(Document)
            .where(
                Document.status == "completed",
                Document.pages_cleaned_at.is_(None),
                Document.updated_at < cutoff,
                Document.deleted_at.is_(None),
            )
            .with_for_update(skip_locked=True)
        )
    ).scalars().all()
    cleaned = 0
    for document in rows:
        base = _ocr_base_from_document(document)
        if not base:
            continue
        try:
            storage.delete_prefix(f"{base}pages/")
            layout_key = f"{base}layout.json"
            layout = json.loads(storage.get_object(layout_key).decode("utf-8"))
            for page in layout.get("pages", []):
                page["path"] = None
                page["cleaned"] = True
            storage.put_object(
                layout_key,
                json.dumps(layout, ensure_ascii=False).encode("utf-8"),
                "application/json",
            )
            document.pages_cleaned_at = _now()
            document.updated_at = _now()
            cleaned += 1
        except Exception as exc:  # noqa: BLE001 - 单文档清理失败跳过不中断（U14）
            logger.warning(
                "页面中间产物清理失败，跳过",
                document_id=str(document.id),
                error=str(exc)[:200],
            )
    await db.commit()
    logger.info("页面中间产物清理完成", cleaned=cleaned, retention_days=days)
    return cleaned


async def enqueue_index_task(
    db: AsyncSession, kb_id: uuid.UUID, document_id: uuid.UUID
) -> DocumentTask | None:
    """创建独立索引任务（D8）：解析完成后自动触发或手动重索引。

    幂等：咨询锁串行化，同一文档同时只允许一个 queued/running 索引任务；
    已有活动任务时返回 None（调用方按 409 处理）。
    仅允许已解析完成（layout 产物存在）的文档进入索引。
    """
    from app.core.exceptions import BusinessException, ErrorCode

    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
        {"key": f"index-trigger:{document_id}"},
    )
    document = (
        await db.execute(
            select(Document)
            .where(
                Document.id == document_id,
                Document.kb_id == kb_id,
                Document.deleted_at.is_(None),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if document is None:
        raise BusinessException(code=ErrorCode.BUSINESS_NOT_FOUND, message="文档不存在")
    if document.status != "completed" or not document.layout_path:
        raise BusinessException(
            code=ErrorCode.BUSINESS_INVALID_STATE,
            message="文档尚未解析完成，无法索引",
        )

    active = (
        await db.execute(
            select(func.count())
            .select_from(DocumentTask)
            .where(
                DocumentTask.document_id == document_id,
                DocumentTask.type == INDEX_TASK_TYPE,
                DocumentTask.status.in_(("queued", "running")),
            )
        )
    ).scalar_one()
    if active > 0:
        return None

    task = DocumentTask(
        kb_id=kb_id,
        document_id=document.id,
        task_id=f"idx-{uuid.uuid4()}",
        type=INDEX_TASK_TYPE,
        status="queued",
        checkpoint={},
    )
    db.add(task)
    await db.flush()
    db.add(
        TaskOutbox(
            task_id=task.task_id,
            type=INDEX_TASK_TYPE,
            payload={
                "document_id": str(document.id),
                "kb_id": str(kb_id),
            },
            status="pending",
        )
    )
    await db.commit()
    await db.refresh(task)
    logger.info("索引任务已创建", document_id=str(document.id), kb_id=str(kb_id))
    return task


async def run_index_task(
    db: AsyncSession, document_id: uuid.UUID, kb_id: uuid.UUID
) -> dict:
    """独立索引流水线：分块 → 嵌入 → 幂等入库（D8）。

    - 失败仅置 document.index_status=index_failed，不影响解析状态；
    - 重跑幂等：先删除该文档旧块再批量插入；
    - checkpoint 记录 stages 与块数，供任务列表/进度展示。
    """
    from app.models.indexing import DocumentChunk, TextChunk
    from app.services.embedding.embedding_service import embedding_service
    from app.services.indexing.bm25 import chunk_token_counts, kb_bm25_service
    from app.services.indexing.chunker import hierarchy_chunker

    document = await get_document(db, kb_id, document_id)
    task = (
        await db.execute(
            select(DocumentTask).where(
                DocumentTask.document_id == document_id,
                DocumentTask.kb_id == kb_id,
                DocumentTask.type == INDEX_TASK_TYPE,
            )
            .order_by(DocumentTask.created_at.desc())
            .limit(1)
        )
    ).scalars().first()
    if task is None:
        raise RuntimeError(f"索引任务不存在：document={document_id}")

    task.attempts += 1
    task.status = "running"
    task.heartbeat_at = _now()
    document.index_status = "indexing"
    document.index_error = None
    document.index_progress = 0
    document.index_total = 0
    document.updated_at = _now()
    await db.commit()

    checkpoint_meta = {"engine": "hierarchy-chunker-v1", "embedding": "bge-m3"}
    done_stages: list[str] = []

    try:
        # ---- stage 1: chunking ----
        if document.layout_path is None:
            raise RuntimeError("文档缺少 layout.json 产物，无法分块")
        layout_bytes = storage.get_object(document.layout_path)
        layout = json.loads(layout_bytes.decode("utf-8"))
        _, children = hierarchy_chunker.chunk(layout, str(document_id))
        if not children:
            raise RuntimeError("分块结果为空，无内容可索引")
        done_stages.append("chunking")
        task.checkpoint = {**checkpoint_meta, "stages": list(done_stages)}
        task.heartbeat_at = _now()
        document.index_total = len(children)
        await db.commit()

        # ---- stage 2: embedding（title/content 双路，D3） ----
        title_texts = [
            f"{c.hierarchy_path} {c.title}".strip() or "文档根节点" for c in children
        ]
        content_texts = [c.content_for_embedding for c in children]
        title_vectors = await asyncio.wait_for(
            embedding_service.embed(title_texts), timeout=settings.INDEX_EMBED_TIMEOUT
        )
        content_vectors = await asyncio.wait_for(
            embedding_service.embed(content_texts), timeout=settings.INDEX_EMBED_TIMEOUT
        )
        done_stages.append("embedding")
        task.checkpoint = {**checkpoint_meta, "stages": list(done_stages)}
        task.heartbeat_at = _now()
        await db.commit()

        # ---- stage 3: storing（幂等：回退旧统计→删旧块→插入新块→增统计） ----
        old_rows = (
            await db.execute(
                text(
                    "SELECT bm25_tokens FROM document_chunks "
                    "WHERE document_id = :doc_id"
                ).bindparams(doc_id=document_id)
            )
        ).scalars().all()
        old_tokens = [dict(r) for r in old_rows if r]
        await kb_bm25_service.remove_document_stats(db, kb_id, old_tokens)
        await db.execute(
            text("DELETE FROM document_chunks WHERE document_id = :doc_id"),
            {"doc_id": document_id},
        )
        await db.execute(
            text("DELETE FROM text_chunks WHERE document_id = :doc_id"),
            {"doc_id": document_id},
        )
        chunk_rows: list[DocumentChunk] = []
        text_rows: list[TextChunk] = []
        new_tokens: list[dict[str, int]] = []
        for i, child in enumerate(children):
            tokens = chunk_token_counts(f"{child.title} {child.content}")
            new_tokens.append(tokens)
            chunk_rows.append(
                DocumentChunk(
                    kb_id=kb_id,
                    document_id=document_id,
                    chunk_id=child.chunk_id,
                    parent_chunk_id=child.parent_chunk_id,
                    chunk_index=child.chunk_index,
                    hierarchy_path=child.hierarchy_path,
                    title=child.title,
                    level=child.level,
                    has_table=child.has_table,
                    semantic_label=child.semantic_label,
                    source_pages=child.source_pages,
                    content=child.content,
                    content_for_embedding=child.content_for_embedding,
                    parent_text=child.parent_text,
                    tokens=child.tokens,
                    bm25_tokens=tokens,
                    title_vector=title_vectors[i],
                    content_vector=content_vectors[i],
                )
            )
        db.add_all(chunk_rows)
        await db.flush()
        for child, row in zip(children, chunk_rows):
            text_rows.append(
                TextChunk(
                    kb_id=kb_id,
                    document_id=document_id,
                    document_chunk_id=row.id,
                    chunk_id=child.chunk_id,
                    content=child.content,
                    heading=child.hierarchy_path,
                    tokens=child.tokens,
                    metadata_json={
                        "page": child.source_pages,
                        "has_table": child.has_table,
                        "semantic_label": child.semantic_label,
                    },
                )
            )
        db.add_all(text_rows)
        await kb_bm25_service.add_document_stats(db, kb_id, new_tokens)
        done_stages.append("storing")

        # ---- 完成 ----
        document.index_status = "indexed"
        document.index_progress = len(children)
        document.index_total = len(children)
        document.updated_at = _now()
        task.status = "completed"
        task.error = None
        task.checkpoint = {
            **checkpoint_meta,
            "stages": INDEX_STAGES,
            "chunk_count": len(children),
            "completed_at": _now().isoformat(),
        }
        task.heartbeat_at = _now()
        task.updated_at = _now()
        await db.commit()
        await db.refresh(document)
        await db.refresh(task)
        logger.info(
            "索引任务完成",
            document_id=str(document_id),
            kb_id=str(kb_id),
            chunk_count=len(children),
        )
        return {"task_id": task.task_id, "status": task.status, "chunk_count": len(children)}
    except Exception as exc:
        await db.rollback()
        await fail_index_task(db, kb_id, document_id, str(exc))
        raise


async def fail_index_task(
    db: AsyncSession, kb_id: uuid.UUID, document_id: uuid.UUID, error: str
) -> None:
    """索引失败：只影响索引状态，解析状态/产物不受影响（D8）。"""
    document = await get_document(db, kb_id, document_id)
    task = (
        await db.execute(
            select(DocumentTask).where(
                DocumentTask.document_id == document_id,
                DocumentTask.kb_id == kb_id,
                DocumentTask.type == INDEX_TASK_TYPE,
            )
            .order_by(DocumentTask.created_at.desc())
            .limit(1)
        )
    ).scalars().first()
    document.index_status = "index_failed"
    document.index_error = {"message": error[:500]}
    document.updated_at = _now()
    if task is not None:
        task.status = "failed"
        task.error = {"message": error[:500]}
        task.updated_at = _now()
    await db.commit()


async def delete_document(
    db: AsyncSession, kb_id: uuid.UUID, document_id: uuid.UUID
) -> None:
    """软删文档记录，同时硬删索引块并回退 BM25 统计（S5/D4）。"""
    from app.services.indexing.bm25 import kb_bm25_service

    doc = await get_document(db, kb_id, document_id)
    old_rows = (
        await db.execute(
            text(
                "SELECT bm25_tokens FROM document_chunks WHERE document_id = :doc_id"
            ).bindparams(doc_id=document_id)
        )
    ).scalars().all()
    old_tokens = [dict(r) for r in old_rows if r]
    await kb_bm25_service.remove_document_stats(db, kb_id, old_tokens)
    await db.execute(
        text("DELETE FROM text_chunks WHERE document_id = :doc_id"),
        {"doc_id": document_id},
    )
    await db.execute(
        text("DELETE FROM document_chunks WHERE document_id = :doc_id"),
        {"doc_id": document_id},
    )
    doc.deleted_at = _now()
    doc.status = "deleted"
    await db.commit()
    await storage.delete_document_objects(kb_id, doc.object_key)


async def list_tasks(
    db: AsyncSession,
    kb_id: uuid.UUID,
    page: int,
    page_size: int,
    task_type: str | None = None,
) -> tuple[list[DocumentTask], int, dict[str, str]]:
    base = select(DocumentTask).where(DocumentTask.kb_id == kb_id)
    count_base = (
        select(func.count())
        .select_from(DocumentTask)
        .where(DocumentTask.kb_id == kb_id)
    )
    if task_type:
        base = base.where(DocumentTask.type == task_type)
        count_base = count_base.where(DocumentTask.type == task_type)
    total = (await db.execute(count_base)).scalar_one()
    rows = (
        await db.execute(
            base.order_by(DocumentTask.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()
    doc_ids = {str(t.document_id) for t in rows}
    filenames: dict[str, str] = {}
    if doc_ids:
        docs = (
            await db.execute(
                select(Document.id, Document.filename).where(
                    Document.id.in_(doc_ids)
                )
            )
        ).all()
        filenames = {str(d.id): d.filename for d in docs}
    return list(rows), total, filenames


async def claim_outbox(db: AsyncSession, limit: int = 10) -> list[TaskOutbox]:
    rows = (
        await db.execute(
            select(TaskOutbox)
            .where(TaskOutbox.status == "pending")
            .order_by(TaskOutbox.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    ).scalars().all()
    for row in rows:
        row.status = "claimed"
    await db.commit()
    return list(rows)


async def mark_outbox(
    db: AsyncSession, outbox: TaskOutbox, status: str, error: str | None = None
) -> None:
    outbox.status = status
    if status == "enqueued":
        outbox.enqueued_at = _now()
    if error:
        outbox.error = error[:500]
    await db.commit()


async def requeue_stale_outbox(
    db: AsyncSession, older_than_seconds: int | None = None
) -> int:
    """把"已派发/已认领但 worker 从未开工"的 outbox 行重置为 pending，交派发器重投。

    触发场景：Redis 作业丢失、worker 重启、或 dispatcher 在 claim 与 enqueue 之间中断，
    会让 outbox 行永久停在 claimed/enqueued，`claim_outbox` 只捞 pending → 永不重投，
    表现为"接口返回已触发，任务却一动不动"。

    安全前提：三条执行链路开工时都会先把对应 DocumentTask 置为 running
    （run_parse_task / run_index_task / extraction_task_service.run_extract_task），
    因此"关联任务仍为 queued"的行一定是没被认领的作业，不会重投正在跑的任务。
    """
    seconds = int(
        older_than_seconds
        if older_than_seconds is not None
        else settings.TASK_STUCK_REAPER_SECONDS
    )
    result = await db.execute(
        text(
            """
            UPDATE task_outbox o
               SET status = 'pending', enqueued_at = NULL
             WHERE o.status IN ('claimed', 'enqueued')
               AND COALESCE(o.enqueued_at, o.created_at)
                   < now() - make_interval(secs => cast(:secs as double precision))
               AND EXISTS (
                     SELECT 1 FROM document_tasks t
                      WHERE t.task_id = o.task_id AND t.status = 'queued'
                   )
            RETURNING o.id, o.type
            """
        ),
        {"secs": seconds},
    )
    rows = result.fetchall()
    await db.commit()
    if rows:
        logger.warning(
            "重投卡住的 outbox 任务",
            count=len(rows),
            older_than_seconds=seconds,
            types=sorted({r[1] for r in rows}),
        )
    return len(rows)


async def run_parse_task(
    db: AsyncSession, document_id: uuid.UUID, kb_id: uuid.UUID
) -> dict:
    """Phase 2 解析流水线：渲染→擦除→版面→顺序→拼装→产物落库。"""
    document = await get_document(db, kb_id, document_id)
    # 必须按 type 过滤并取最新一条：否则会更新到同文档的 index/extraction 任务或历史旧任务，
    # 导致真正待执行的 parse 任务永远停留在 queued（僵尸任务）。
    task = (
        await db.execute(
            select(DocumentTask)
            .where(
                DocumentTask.document_id == document_id,
                DocumentTask.kb_id == kb_id,
                DocumentTask.type == PARSE_TASK_TYPE,
            )
            .order_by(DocumentTask.created_at.desc())
            .limit(1)
        )
    ).scalars().first()
    if task is None:
        raise RuntimeError(f"任务不存在：document={document_id}")

    task.attempts += 1
    task.status = "running"
    task.heartbeat_at = _now()
    await db.commit()

    options = ParseOptions.from_settings()
    checkpoint_meta = {
        "engine": "ppdoclayoutv3",
        "header_footer_mode": options.header_footer_mode,
        "dpi": options.dpi,
    }
    document.status = "parsing"
    document.process_status = "queued"
    document.updated_at = _now()
    await db.commit()

    try:
        pdf_bytes = storage.get_object(document.object_key)
    except Exception as exc:
        raise RuntimeError(f"读取原始 PDF 失败：{exc}") from exc

    stage_holder: dict[str, str | int | None] = {
        "stage": None,
        "page": None,
        "total": None,
    }

    def _on_stage(
        stage: str, page: int | None = None, total: int | None = None
    ) -> None:
        stage_holder["stage"] = stage
        stage_holder["page"] = page
        stage_holder["total"] = total

    parse_task = asyncio.create_task(
        asyncio.to_thread(parse_pdf, pdf_bytes, options=options, progress=_on_stage)
    )
    done_stages: list[str] = []
    last_stage: str | None = None
    last_page: int | None = None
    while not parse_task.done():
        stage = stage_holder["stage"]
        page = stage_holder["page"]
        total = stage_holder["total"]
        if stage is not None and (stage != last_stage or page != last_page):
            if stage != last_stage:
                done_stages.append(stage)
            last_stage = stage
            last_page = page
            document.process_status = stage
            document.status = "parsing"
            if page is not None:
                document.progress_page = page
            if total is not None:
                document.progress_total = total
            task.checkpoint = {**checkpoint_meta, "stages": list(done_stages)}
            task.heartbeat_at = _now()
            task.updated_at = _now()
            document.updated_at = _now()
            await db.commit()
        await asyncio.sleep(0.2)
    try:
        result = parse_task.result()
    except Exception as exc:
        raise RuntimeError(str(exc)) from exc

    keys = _artifact_keys(kb_id, task.task_id)
    try:
        storage.put_object(
            keys["markdown"], result.markdown.encode("utf-8"), "text/markdown"
        )
        storage.put_object(
            keys["layout"],
            json.dumps(result.layout, ensure_ascii=False).encode("utf-8"),
            "application/json",
        )
        for page in result.pages:
            storage.put_object(
                f"{keys['base']}/{page['path']}",
                page["image_bytes"],
                "image/png",
            )
    except Exception as exc:
        raise RuntimeError(f"解析产物落库失败：{exc}") from exc

    partial = (
        bool(result.page_failures) and options.partial_on_page_failure
    ) or (
        bool(result.ocr_failures) and options.ocr_failure_policy == "partial"
    )
    document.page_count = len(result.pages)
    document.progress_page = len(result.pages)
    document.progress_total = len(result.pages)
    document.markdown_path = keys["markdown"]
    document.layout_path = keys["layout"]
    document.status = "completed"
    document.process_status = "partial" if partial else "completed"
    document.error = None
    task.status = "completed"
    task.error = None
    task.checkpoint = {
        **checkpoint_meta,
        "stages": PARSE_STAGES,
        "page_count": len(result.pages),
        "blocks": result.stats.get("blocks", 0),
        "erased_blocks": result.stats.get("erased_blocks", 0),
        "page_failures": result.page_failures,
        "ocr_failures": result.ocr_failures,
        "ocr_blocks": result.stats.get("ocr_blocks", 0),
        "partial": partial,
        "completed_at": _now().isoformat(),
    }
    task.heartbeat_at = _now()
    task.updated_at = _now()
    document.updated_at = _now()
    await db.commit()
    await db.refresh(document)
    await db.refresh(task)
    return {
        "task_id": task.task_id,
        "status": task.status,
        "partial": partial,
    }


async def fail_task(
    db: AsyncSession,
    kb_id: uuid.UUID,
    document_id: uuid.UUID,
    error: str,
    task_type: str = PARSE_TASK_TYPE,
) -> None:
    document = await get_document(db, kb_id, document_id)
    # 与 run_parse_task 一致：按 type 过滤 + 取最新，避免把失败状态写到别的任务上
    task = (
        await db.execute(
            select(DocumentTask)
            .where(
                DocumentTask.document_id == document_id,
                DocumentTask.kb_id == kb_id,
                DocumentTask.type == task_type,
            )
            .order_by(DocumentTask.created_at.desc())
            .limit(1)
        )
    ).scalars().first()
    document.status = "failed"
    document.process_status = "failed"
    document.error = {"message": error[:500]}
    if task is not None:
        task.status = "failed"
        task.error = {"message": error[:500]}
        db.add(
            TaskDeadLetter(
                task_id=task.task_id,
                type=task.type,
                error=error[:1000],
                attempts=task.attempts,
            )
        )
    await db.commit()
