"""知识库内文档抽取端点模块（方案 §10.4）。

提供 KB 隔离的结构化抽取接口，所有端点强制 ``Depends(get_kb_context)`` /
``require_role(*EDIT_ROLES)``，借助 PostgreSQL RLS 自动按 ``kb_id`` 过滤
Document 与 SchemaConfig，实现知识库隔离：

- ``GET  /kbs/{kb_id}/extraction/documents``          KB 内可抽取文档列表（viewer+）
- ``GET  /kbs/{kb_id}/extraction/schemas``            KB 内父分类 Schema 列表（viewer+）
- ``POST /kbs/{kb_id}/extraction/stream``             SSE 流式抽取（editor+）
- ``POST /kbs/{kb_id}/extraction/``                   同步抽取（editor+）
- ``GET  /kbs/{kb_id}/extraction/results/{doc_id}``   文档抽取结果（viewer+）

知识库隔离要点：
- ``get_kb_context`` 已激活 RLS（``SET LOCAL app.current_kb``），后续对
  Document / SchemaConfig 的查询自动按 ``kb_id`` 过滤，无需额外条件。
- 抽取结果写入 ``document.structured_data``，该 Document 已属于当前 KB。
- 抽取服务 ``extraction_service`` 本身无 KB 概念，但仅消费当前 KB 的文档
  文本与 Schema 定义，天然不跨 KB。

与旧 ``extraction.py``（全局，向后兼容）共存，本模块为 KB 化主入口。
"""

import json
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    AI_LIMIT,
    DEFAULT_LIMIT,
    KBContext,
    get_db,
    get_kb_context,
    limiter,
    require_role,
)
from app.core.logging import get_logger
from app.core.response import success
from app.models.document import Document
from app.models.knowledge_base import EDIT_ROLES
from app.models.schema_model import SchemaConfig, SchemaTemplate
from app.services.infra.export_service import export_data
from app.services.extraction.extraction_pipeline import extraction_pipeline

# 复用全局抽取模块的请求模型与辅助函数，保持两端契约一致
from app.api.v1.endpoints.extraction import (
    ExtractionRequest,
    ExtractionStreamRequest,
    _load_document,
    _load_merged_schema,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/kbs/{kb_id}/extraction", tags=["知识库-文档抽取"])


async def _save_extraction_result_with_history(
    db: AsyncSession,
    doc: Document,
    result_data: dict,
    schema_id: UUID,
    schema_name: str,
) -> None:
    """将抽取结果持久化到 document.structured_data，支持历史版本归档。

    新结果保存到 latest_result，旧结果自动移入 history 数组。

    Args:
        db: 异步数据库会话。
        doc: 文档 ORM 实例。
        result_data: 抽取结果字典。
        schema_id: 关联的 Schema ID。
        schema_name: Schema 名称。
    """
    existing = doc.structured_data or {}
    now = datetime.utcnow().isoformat()

    history = existing.get("history", [])
    if not isinstance(history, list):
        history = []

    old_latest = existing.get("latest_result")
    old_schema_id = existing.get("latest_schema_id")
    old_schema_name = existing.get("latest_schema_name")
    old_extracted_at = existing.get("latest_extracted_at")

    if old_latest is not None:
        history.insert(0, {
            "result": old_latest,
            "schema_id": old_schema_id,
            "schema_name": old_schema_name,
            "extracted_at": old_extracted_at or now,
            "archived_at": now,
        })

    history = history[:50]

    existing.update({
        "latest_result": result_data,
        "latest_schema_id": str(schema_id),
        "latest_schema_name": schema_name,
        "latest_extracted_at": now,
        "history": history,
    })
    doc.structured_data = existing
    await db.commit()
    logger.info(
        "抽取结果已保存（含历史版本）",
        document_id=str(doc.id),
        schema_id=str(schema_id),
        history_count=len(history),
    )


@router.get("/documents")
@limiter.limit(DEFAULT_LIMIT)
async def list_kb_extractable_documents(
    request: Request,
    kb_ctx: KBContext = Depends(get_kb_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """查询 KB 内已完成 OCR 解析的文档列表（viewer+）。

    显式按 kb_id 过滤，纵深防御不依赖 RLS（superuser 绕过 RLS）。

    Returns:
        dict: 含 ``items`` 与 ``total`` 的可抽取文档列表。
    """
    # 显式按 kb_id 过滤，纵深防御不依赖 RLS（superuser 绕过 RLS）
    stmt = (
        select(Document)
        .where(
            Document.status == "completed",
            Document.parsed_text.isnot(None),
            Document.kb_id == kb_ctx.kb_id,
        )
        .order_by(Document.created_at.desc())
    )
    result = await db.execute(stmt)
    docs = result.scalars().all()

    items: list[dict] = []
    for doc in docs:
        structured = doc.structured_data or {}
        has_extraction = bool(
            structured.get("latest_result") or structured.get("records")
        )
        items.append({
            "id": str(doc.id),
            "filename": doc.filename,
            "file_size": doc.file_size,
            "file_type": doc.file_type,
            "status": doc.status,
            "text_length": len(doc.parsed_text or ""),
            "has_extraction": has_extraction,
            "latest_schema_id": structured.get("latest_schema_id"),
            "latest_schema_name": structured.get("latest_schema_name"),
            "latest_extracted_at": structured.get("latest_extracted_at"),
            "history_count": len(structured.get("history", []) or []),
            "created_at": doc.created_at.isoformat() if doc.created_at else "",
            "updated_at": doc.updated_at.isoformat() if doc.updated_at else "",
        })

    return success(data={"items": items, "total": len(items)})


@router.get("/schemas")
@limiter.limit(DEFAULT_LIMIT)
async def list_kb_extraction_schemas(
    request: Request,
    kb_ctx: KBContext = Depends(get_kb_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """查询 KB 内所有抽取 Schema 模板（viewer+）。

    新版 Schema 模板（SchemaTemplate，抽取配置中心配置）作为抽取的 Schema
    数据源，与旧版 SchemaConfig 父/子分类解耦。每个模板含若干类别节点。

    Returns:
        dict: 抽取 Schema 模板列表。
    """
    templates = (
        await db.execute(
            select(SchemaTemplate)
            .where(
                SchemaTemplate.kb_id == kb_ctx.kb_id,
                SchemaTemplate.is_active.is_(True),
            )
            .order_by(SchemaTemplate.created_at)
        )
    ).scalars().all()

    tpl_ids = [t.id for t in templates]
    cat_counts: dict[str, int] = {}
    field_counts: dict[str, int] = {}
    if tpl_ids:
        nodes = (
            await db.execute(
                select(SchemaConfig).where(SchemaConfig.template_id.in_(tpl_ids))
            )
        ).scalars().all()
        for n in nodes:
            tid = str(n.template_id)
            if n.node_type == "category":
                cat_counts[tid] = cat_counts.get(tid, 0) + 1
            elif n.node_type == "field":
                field_counts[tid] = field_counts.get(tid, 0) + 1

    items: list[dict] = []
    for t in templates:
        tid = str(t.id)
        items.append({
            "id": tid,
            "name": t.name,
            "description": t.description or "",
            "category_count": cat_counts.get(tid, 0),
            "field_count": field_counts.get(tid, 0),
        })

    return success(data=items)


@router.post("/stream")
@limiter.limit(AI_LIMIT)
async def kb_extraction_stream(
    request: Request,
    body: ExtractionStreamRequest,
    kb_ctx: KBContext = Depends(require_role(*EDIT_ROLES)),
) -> StreamingResponse:
    """KB 内 SSE 流式抽取（editor+）。

    接入 v3 抽取流水线（``extraction_pipeline.run``）：依据 KB 配置的
    Schema 模板 / Prompt 模板 / 术语集，执行 Phase 2 类别构建 → Phase 3
    检索 → Phase 4 LLM 抽取 + 后处理的完整流程，并将结果（含类别结构）
    保存到 ``document.structured_data.latest_result``。

    Args:
        body: 流式抽取请求体（document_id + schema_id[模板 id]）。
        kb_ctx: 知识库上下文（已校验 editor+ 角色 + 激活 RLS）。

    Returns:
        StreamingResponse: ``text/event-stream`` 类型的流式响应。
    """
    from app.core.exceptions import BusinessException, ErrorCode

    document_id = body.document_id
    schema_id = body.schema_id
    logger.info(
        "收到 KB 流式抽取请求（v3 流水线）",
        kb_id=str(kb_ctx.kb_id),
        document_id=document_id,
        schema_id=schema_id,
    )

    async def event_generator():
        """SSE 事件生成器（KB 隔离 + v3 流水线）。

        在生成器内部独立获取数据库会话，并显式激活 RLS，避免外部会话在
        流式响应期间失效，同时保证 KB 隔离在流式期间持续生效。
        """
        import asyncio
        import uuid
        from app.core.database import AsyncSessionLocal
        from app.api.deps import activate_rls

        try:
            async with AsyncSessionLocal() as stream_db:
                await activate_rls(stream_db, kb_ctx.kb_id)

                doc = await _load_document(
                    stream_db, UUID(document_id), kb_id=kb_ctx.kb_id
                )
                tpl = await stream_db.get(SchemaTemplate, UUID(schema_id))
                if tpl is None or tpl.kb_id != kb_ctx.kb_id or not tpl.is_active:
                    raise BusinessException(
                        code=ErrorCode.VALIDATION_ERROR,
                        message="Schema 模板不存在或不属于当前知识库",
                    )

                category_count = (
                    await stream_db.execute(
                        select(func.count())
                        .select_from(SchemaConfig)
                        .where(
                            SchemaConfig.template_id == tpl.id,
                            SchemaConfig.node_type == "category",
                            SchemaConfig.is_active.is_(True),
                        )
                    )
                ).scalar_one()

                yield "data: " + json.dumps({
                    "type": "schema_info",
                    "schema_name": tpl.name,
                    "schema_description": tpl.description or "",
                    "field_count": category_count,
                }, ensure_ascii=False) + "\n\n"

                yield "data: " + json.dumps({
                    "type": "progress",
                    "progress": 10,
                    "message": f"正在执行 v3 抽取流水线「{tpl.name}」（{category_count} 个类别）",
                    "chunk_index": 1,
                    "total_chunks": category_count,
                }, ensure_ascii=False) + "\n\n"

                # 调用 v3 抽取流水线（Phase 2-4 全流程）
                task_id = str(uuid.uuid4().hex[:24])
                result = await extraction_pipeline.run(
                    task_id=task_id,
                    doc_id=document_id,
                    kb_id=str(kb_ctx.kb_id),
                )

                yield "data: " + json.dumps({
                    "type": "progress",
                    "progress": 90,
                    "message": "抽取完成，正在保存结果",
                    "chunk_index": category_count,
                    "total_chunks": category_count,
                }, ensure_ascii=False) + "\n\n"

                latest = result.to_dict() if hasattr(result, "to_dict") else {}
                categories = latest.get("categories", []) or []
                total_records = sum(
                    len(c.get("records") or []) for c in categories
                )

                if body.save_result:
                    await _save_extraction_result_with_history(
                        stream_db, doc, latest, tpl.id, tpl.name
                    )

                yield "data: " + json.dumps({
                    "type": "done",
                    "data": latest,
                    "missing": [],
                    "progress": 100,
                    "message": f"抽取完成，共 {len(categories)} 个类别、{total_records} 条记录",
                }, ensure_ascii=False) + "\n\n"

        except Exception as err:
            logger.error(
                "KB 流式抽取未预期异常",
                kb_id=str(kb_ctx.kb_id),
                error=str(err),
                exc_info=True,
            )
            yield "data: " + json.dumps({
                "type": "error",
                "message": f"抽取过程中发生未预期错误：{err}",
            }, ensure_ascii=False) + "\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/")
@limiter.limit(AI_LIMIT)
async def kb_extract_document(
    request: Request,
    body: ExtractionRequest,
    kb_ctx: KBContext = Depends(require_role(*EDIT_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """KB 内同步抽取（editor+）。

    RLS 保证文档与 Schema 均属于当前 KB。适用于短文本或调试场景。

    Args:
        body: 同步抽取请求体。
        kb_ctx: 知识库上下文。
        db: 异步数据库会话。

    Returns:
        dict: 抽取结果。
    """
    doc = await _load_document(db, UUID(body.document_id), kb_id=kb_ctx.kb_id)
    parent, schema_definition, sample_fields = await _load_merged_schema(
        db, UUID(body.schema_id), kb_id=kb_ctx.kb_id
    )

    logger.info(
        "开始 KB 同步抽取",
        kb_id=str(kb_ctx.kb_id),
        document_id=str(doc.id),
        schema_id=str(parent.id),
        schema_name=parent.name,
    )

    # TODO: 适配新的extraction_pipeline接口
    from app.core.exceptions import BusinessException, ErrorCode
    raise BusinessException(
        code=ErrorCode.VALIDATION_ERROR,
        message="extraction_service已重构，KB同步抽取端点暂未适配新接口",
    )


@router.get("/results/{document_id}")
async def get_kb_extraction_results(
    document_id: UUID,
    kb_ctx: KBContext = Depends(get_kb_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取 KB 内指定文档已保存的抽取结果（viewer+）。

    RLS 已按 kb_id 过滤，跨 KB 文档查询返回 None。

    Raises:
        BusinessException: 文档不存在或不在当前 KB 时抛出。
    """
    from app.core.exceptions import BusinessException, ErrorCode

    doc = await db.get(Document, document_id)
    if doc is None or doc.kb_id != kb_ctx.kb_id:
        raise BusinessException(
            code=ErrorCode.BUSINESS_DOCUMENT_NOT_FOUND,
            message=f"文档 {document_id} 不存在",
        )

    structured = doc.structured_data or {}
    return success(data={
        "document_id": str(doc.id),
        "filename": doc.filename,
        "latest_schema_id": structured.get("latest_schema_id"),
        "latest_schema_name": structured.get("latest_schema_name"),
        "latest_result": structured.get("latest_result"),
        "latest_extracted_at": structured.get("latest_extracted_at"),
        "history": structured.get("history", []),
    })


@router.get("/history/{document_id}")
@limiter.limit(DEFAULT_LIMIT)
async def get_kb_extraction_history(
    request: Request,
    document_id: UUID,
    kb_ctx: KBContext = Depends(get_kb_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取 KB 内指定文档的抽取历史记录（viewer+）。

    返回历史版本列表，按时间倒序排列。

    Raises:
        BusinessException: 文档不存在或不在当前 KB 时抛出。
    """
    from app.core.exceptions import BusinessException, ErrorCode

    doc = await db.get(Document, document_id)
    if doc is None or doc.kb_id != kb_ctx.kb_id:
        raise BusinessException(
            code=ErrorCode.BUSINESS_DOCUMENT_NOT_FOUND,
            message=f"文档 {document_id} 不存在",
        )

    structured = doc.structured_data or {}
    history = structured.get("history", [])
    if not isinstance(history, list):
        history = []

    latest = None
    if structured.get("latest_result") is not None:
        latest = {
            "schema_id": structured.get("latest_schema_id"),
            "schema_name": structured.get("latest_schema_name"),
            "result": structured.get("latest_result"),
            "extracted_at": structured.get("latest_extracted_at"),
            "is_latest": True,
        }

    items = []
    if latest:
        items.append(latest)
    for h in history:
        items.append({
            "schema_id": h.get("schema_id"),
            "schema_name": h.get("schema_name"),
            "result": h.get("result"),
            "extracted_at": h.get("extracted_at"),
            "archived_at": h.get("archived_at"),
            "is_latest": False,
        })

    return success(data={"items": items, "total": len(items)})


@router.get("/export")
async def export_extraction_results(
    kb_ctx: KBContext = Depends(get_kb_context),
    db: AsyncSession = Depends(get_db),
    format: str = Query("excel", description="导出格式：excel/csv/json"),
) -> StreamingResponse:
    """导出 KB 内全部文档的抽取结果摘要（任意成员）。

    每个文档一行：文件名、类别数、总记录数、最新 Schema、抽取时间。
    显式按 kb_id 过滤，纵深防御不依赖 RLS（superuser 绕过 RLS）。
    如需导出完整 JSON 结果，format=json。
    """
    # 显式按 kb_id 过滤，纵深防御不依赖 RLS（superuser 绕过 RLS）
    docs = (
        await db.execute(
            select(Document)
            .where(
                Document.structured_data.isnot(None),
                Document.kb_id == kb_ctx.kb_id,
            )
            .order_by(Document.created_at.desc())
        )
    ).scalars().all()

    rows: list[dict] = []
    for d in docs:
        sd = d.structured_data or {}
        extractions = sd.get("extractions", {}) or {}
        category_count = len(extractions)
        total_records = sum(
            len(v) if isinstance(v, list) else 0 for v in extractions.values()
        )
        rows.append({
            "id": str(d.id),
            "filename": d.filename,
            "category_count": category_count,
            "total_records": total_records,
            "latest_schema_id": sd.get("latest_schema_id", "") or "",
            "extractions_json": json.dumps(extractions, ensure_ascii=False),
            "created_at": d.created_at.isoformat() if d.created_at else "",
        })

    columns = [
        {"key": "id", "label": "文档ID"},
        {"key": "filename", "label": "文件名"},
        {"key": "category_count", "label": "类别数"},
        {"key": "total_records", "label": "总记录数"},
        {"key": "latest_schema_id", "label": "最新Schema"},
        {"key": "extractions_json", "label": "抽取结果(JSON)"},
        {"key": "created_at", "label": "上传时间"},
    ]
    return export_data(rows, columns, format=format, sheet_name="抽取结果", filename_prefix="extraction")
