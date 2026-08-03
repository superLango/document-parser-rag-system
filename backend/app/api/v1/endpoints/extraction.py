"""文档抽取端点模块。

提供基于 LangExtract 的结构化抽取接口，包括：

- ``GET /extraction/documents``：查询已完成 OCR 解析的文档列表（供抽取页面使用）
- ``GET /extraction/schemas``：查询所有父分类 Schema（用于抽取页面 Schema 选择器）
- ``POST /extraction/stream``：SSE 流式抽取，逐块推送进度与增量结果
- ``POST /extraction/``：同步抽取（一次性返回完整结果）
- ``GET /extraction/results/{document_id}``：获取指定文档已保存的抽取结果

抽取流程：
    1. 加载文档（含 parsed_text）
    2. 加载合并 Schema（父分类下所有启用子 Schema 的字段合并）
    3. 切分长文本为多个 chunk
    4. 逐块调用 LangExtract 抽取
    5. 合并结果并校验必填字段
    6. 持久化抽取结果到 document.structured_data
"""

import json
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user
from app.core.database import get_db
from app.core.exceptions import BusinessException, ErrorCode
from app.core.logging import get_logger
from app.core.response import success
from app.models.document import Document
from app.models.schema_model import SchemaConfig
from app.models.user import User
# TODO: extraction_service已删除，需适配新的extraction_pipeline接口
# from app.services.extraction.extraction_pipeline import extraction_pipeline as extraction_service

logger = get_logger(__name__)

router = APIRouter(prefix="/extraction", tags=["文档抽取"])


# ---------------------------------------------------------------
# 请求与响应模型
# ---------------------------------------------------------------
class ExtractionStreamRequest(BaseModel):
    """流式抽取请求体。

    Attributes:
        document_id: 待抽取的文档 ID。
        schema_id: 父分类 Schema ID（用于加载合并后的整体 Schema）。
        chunk_size: 单个 chunk 的目标字符数，默认 4000。
        overlap: 相邻 chunk 之间的重叠字符数，默认 200。
        save_result: 是否将抽取结果保存到 document.structured_data，默认 True。
    """

    document_id: str = Field(..., description="待抽取的文档 ID")
    schema_id: str = Field(..., description="父分类 Schema ID")
    chunk_size: int = Field(default=4000, ge=500, le=20000, description="单块字符数")
    overlap: int = Field(default=200, ge=0, le=1000, description="重叠字符数")
    save_result: bool = Field(default=True, description="是否持久化抽取结果")


class ExtractionRequest(BaseModel):
    """同步抽取请求体。"""

    document_id: str = Field(..., description="待抽取的文档 ID")
    schema_id: str = Field(..., description="父分类 Schema ID")
    save_result: bool = Field(default=True, description="是否持久化抽取结果")


# ---------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------
async def _load_document(
    db: AsyncSession,
    document_id: UUID,
    kb_id: UUID | None = None,
) -> Document:
    """加载文档并校验存在性与解析状态。

    Args:
        db: 异步数据库会话。
        document_id: 文档 ID。
        kb_id: 知识库 ID。提供时显式按 kb_id 过滤（纵深防御不依赖 RLS，
            因 PostgreSQL superuser 绕过 RLS）；为 None 时依赖 RLS（全局端点）。

    Returns:
        Document: 文档 ORM 实例。

    Raises:
        BusinessException: 文档不存在或未完成解析时抛出。
    """
    stmt = select(Document).where(Document.id == document_id)
    # 显式按 kb_id 过滤，纵深防御不依赖 RLS（superuser 绕过 RLS）
    if kb_id is not None:
        stmt = stmt.where(Document.kb_id == kb_id)
    result = await db.execute(stmt)
    doc = result.scalar_one_or_none()
    if doc is None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_DOCUMENT_NOT_FOUND,
            message=f"文档 {document_id} 不存在",
        )
    if doc.status != "completed":
        raise BusinessException(
            code=ErrorCode.VALIDATION_ERROR,
            message=f"文档未完成 OCR 解析（当前状态：{doc.status}），请先完成解析",
        )
    if not doc.parsed_text or not doc.parsed_text.strip():
        raise BusinessException(
            code=ErrorCode.VALIDATION_ERROR,
            message="文档 OCR 解析文本为空，无法抽取",
        )
    return doc


async def _load_merged_schema(
    db: AsyncSession,
    schema_id: UUID,
    kb_id: UUID | None = None,
) -> tuple[SchemaConfig, dict, dict]:
    """加载父分类并合并子 Schema 字段。

    Args:
        db: 异步数据库会话。
        schema_id: 父分类 Schema ID。
        kb_id: 知识库 ID。提供时显式按 kb_id 过滤（纵深防御不依赖 RLS，
            因 PostgreSQL superuser 绕过 RLS）；为 None 时依赖 RLS（全局端点）。

    Returns:
        tuple: (parent_schema_config, schema_definition, sample_fields)
            - parent_schema_config: 父分类 ORM 实例
            - schema_definition: 合并后的字段定义 {"fields": [...]}
            - sample_fields: 合并后的示例字段

    Raises:
        BusinessException: Schema 不存在或不是父分类时抛出。
    """
    parent_stmt = select(SchemaConfig).where(SchemaConfig.id == schema_id)
    # 显式按 kb_id 过滤，纵深防御不依赖 RLS（superuser 绕过 RLS）
    if kb_id is not None:
        parent_stmt = parent_stmt.where(SchemaConfig.kb_id == kb_id)
    parent_result = await db.execute(parent_stmt)
    parent = parent_result.scalar_one_or_none()
    if parent is None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_DOCUMENT_NOT_FOUND,
            message=f"Schema {schema_id} 不存在",
        )
    if parent.parent_id is not None:
        raise BusinessException(
            code=ErrorCode.VALIDATION_ERROR,
            message=f"Schema {schema_id} 不是父分类，请选择父分类节点",
        )

    # 加载启用的子 Schema
    children_stmt = (
        select(SchemaConfig)
        .where(SchemaConfig.parent_id == schema_id)
        .where(SchemaConfig.is_active.is_(True))
    )
    if kb_id is not None:
        children_stmt = children_stmt.where(SchemaConfig.kb_id == kb_id)
    children_stmt = children_stmt.order_by(
        SchemaConfig.sort_order, SchemaConfig.created_at
    )
    children_result = await db.execute(children_stmt)
    children = children_result.scalars().all()

    if not children:
        raise BusinessException(
            code=ErrorCode.VALIDATION_ERROR,
            message=f"父分类「{parent.name}」下没有启用的子 Schema",
        )

    # 合并字段（去重同名字段）
    merged_fields: list[dict] = []
    seen_names: set[str] = set()
    merged_samples: dict = {}
    for child in children:
        for field in (child.schema_definition or []):
            if not isinstance(field, dict):
                continue
            name = field.get("name")
            if not name or name in seen_names:
                continue
            seen_names.add(name)
            merged_fields.append(field)
        for k, v in (child.sample_fields or {}).items():
            if k not in merged_samples:
                merged_samples[k] = v

    schema_definition = {"fields": merged_fields}
    return parent, schema_definition, merged_samples


async def _save_extraction_result(
    db: AsyncSession,
    doc: Document,
    result_data: dict,
    schema_id: UUID,
) -> None:
    """将抽取结果持久化到 document.structured_data。

    保留原有结构化数据，新增/更新当前 schema_id 对应的抽取结果。

    Args:
        db: 异步数据库会话。
        doc: 文档 ORM 实例。
        result_data: 抽取结果字典。
        schema_id: 关联的 Schema ID。
    """
    existing = doc.structured_data or {}
    # 按 schema_id 索引存储抽取结果，便于后续查询
    extraction_history = existing.get("extractions", {}) if isinstance(existing.get("extractions"), dict) else {}
    extraction_history[str(schema_id)] = {
        "result": result_data,
        "schema_name": None,  # 由调用方填充
    }
    existing.update({
        "extractions": extraction_history,
        "latest_schema_id": str(schema_id),
        "latest_result": result_data,
    })
    doc.structured_data = existing
    await db.commit()
    logger.info(
        "抽取结果已保存",
        document_id=str(doc.id),
        schema_id=str(schema_id),
        field_count=len(result_data),
    )


# ---------------------------------------------------------------
# 端点定义
# ---------------------------------------------------------------
@router.get("/documents")
async def list_extractable_documents(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """查询已完成 OCR 解析的文档列表（供抽取页面使用）。

    返回所有 status='completed' 且 parsed_text 不为空的文档。
    每个文档额外附带：
    - text_length: 解析文本长度
    - has_extraction: 是否已有抽取结果
    """
    stmt = (
        select(Document)
        .where(Document.status == "completed")
        .where(Document.parsed_text.isnot(None))
        .order_by(Document.created_at.desc())
    )
    result = await db.execute(stmt)
    docs = result.scalars().all()

    items: list[dict] = []
    for doc in docs:
        structured = doc.structured_data or {}
        has_extraction = bool(
            structured.get("latest_result")
            or (
                isinstance(structured.get("extractions"), dict)
                and structured["extractions"]
            )
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
            "created_at": doc.created_at.isoformat() if doc.created_at else "",
            "updated_at": doc.updated_at.isoformat() if doc.updated_at else "",
        })

    return success(data={"items": items, "total": len(items)})


@router.get("/schemas")
async def list_extraction_schemas(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """查询所有父分类 Schema（用于抽取页面 Schema 选择器）。

    只返回含启用子 Schema 的父分类，并附带：
    - children_count: 启用子 Schema 数量
    - total_fields: 合并后的字段总数
    """
    # 查询所有父分类
    parent_stmt = (
        select(SchemaConfig)
        .where(SchemaConfig.parent_id.is_(None))
        .where(SchemaConfig.is_active.is_(True))
        .order_by(SchemaConfig.sort_order, SchemaConfig.created_at)
    )
    parent_result = await db.execute(parent_stmt)
    parents = parent_result.scalars().all()

    # 批量查询每个父分类的启用子 Schema 数量
    parent_ids = [p.id for p in parents]
    children_counts: dict[str, int] = {}
    if parent_ids:
        count_stmt = (
            select(SchemaConfig.parent_id, func.count(SchemaConfig.id))
            .where(SchemaConfig.parent_id.in_(parent_ids))
            .where(SchemaConfig.is_active.is_(True))
            .group_by(SchemaConfig.parent_id)
        )
        count_result = await db.execute(count_stmt)
        for pid, cnt in count_result.all():
            children_counts[str(pid)] = cnt

    items: list[dict] = []
    for p in parents:
        cnt = children_counts.get(str(p.id), 0)
        if cnt == 0:
            continue  # 跳过没有启用子 Schema 的父分类
        items.append({
            "id": str(p.id),
            "name": p.name,
            "description": p.description or "",
            "children_count": cnt,
        })

    return success(data=items)


@router.post("/stream")
async def extraction_stream(
    body: ExtractionStreamRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> StreamingResponse:
    """SSE 流式抽取。

    通过 Server-Sent Events 协议逐块推送抽取进度与增量结果。

    事件格式：
    - 进度事件: ``data: {"type":"progress","progress":0-100,"message":"...","chunk_index":N,"total_chunks":M}\\n\\n``
    - 单块完成: ``data: {"type":"chunk_result","data":{...},"chunk_index":N,"progress":N}``\\n\\n``
    - 单块失败: ``data: {"type":"chunk_error","chunk_index":N,"error":"...","message":"..."}``\\n\\n``
    - 完成: ``data: {"type":"done","data":{...合并结果...},"missing":[...],"progress":100}``\\n\\n``
    - 错误: ``data: {"type":"error","message":"..."}``\\n\\n``
    """
    document_id = body.document_id
    schema_id = body.schema_id
    logger.info(
        "收到流式抽取请求",
        document_id=document_id,
        schema_id=schema_id,
        chunk_size=body.chunk_size,
        overlap=body.overlap,
    )

    async def event_generator():
        """SSE 事件生成器。

        在生成器内部独立获取数据库会话，避免外部会话在流式响应期间失效。
        """
        from app.core.database import AsyncSessionLocal

        try:
            # 在流式生成器内创建独立的数据库会话
            async with AsyncSessionLocal() as stream_db:
                # 1. 加载文档
                doc = await _load_document(stream_db, UUID(document_id))

                # 2. 加载合并 Schema
                parent, schema_definition, sample_fields = await _load_merged_schema(
                    stream_db, UUID(schema_id)
                )

                # 推送 Schema 信息事件
                yield "data: " + json.dumps({
                    "type": "schema_info",
                    "schema_name": parent.name,
                    "schema_description": parent.description or "",
                    "field_count": len(schema_definition.get("fields", [])),
                    "has_samples": bool(sample_fields),
                }, ensure_ascii=False) + "\n\n"

                # 3. 流式抽取 (TODO: 适配新的extraction_pipeline)
                yield "data: " + json.dumps({
                    "type": "error",
                    "message": "extraction_service已重构，端点暂未适配新接口",
                }, ensure_ascii=False) + "\n\n"
                return

        except BusinessException as err:
            logger.warning("流式抽取业务异常", message=err.message)
            yield "data: " + json.dumps({
                "type": "error",
                "message": err.message,
                "code": err.code,
            }, ensure_ascii=False) + "\n\n"
        except Exception as err:
            logger.error("流式抽取未预期异常", error=str(err), exc_info=True)
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
            "X-Accel-Buffering": "no",  # 禁用 Nginx 缓冲，确保实时推送
        },
    )


@router.post("/")
async def extract_document(
    body: ExtractionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """同步抽取（一次性返回完整结果）。

    适用于短文本或调试场景。长文档请使用 ``POST /extraction/stream`` 流式接口。
    """
    doc = await _load_document(db, UUID(body.document_id))
    parent, schema_definition, sample_fields = await _load_merged_schema(
        db, UUID(body.schema_id)
    )

    logger.info(
        "开始同步抽取",
        document_id=str(doc.id),
        schema_id=str(parent.id),
        schema_name=parent.name,
    )

    # TODO: 适配新的extraction_pipeline接口
    raise BusinessException(
        code=ErrorCode.VALIDATION_ERROR,
        message="extraction_service已重构，同步抽取端点暂未适配新接口",
    )


@router.get("/results/{document_id}")
async def get_extraction_results(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """获取指定文档已保存的抽取结果。"""
    stmt = select(Document).where(Document.id == document_id)
    result = await db.execute(stmt)
    doc = result.scalar_one_or_none()
    if doc is None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_DOCUMENT_NOT_FOUND,
            message=f"文档 {document_id} 不存在",
        )

    structured = doc.structured_data or {}
    return success(data={
        "document_id": str(doc.id),
        "filename": doc.filename,
        "extractions": structured.get("extractions", {}),
        "latest_schema_id": structured.get("latest_schema_id"),
        "latest_result": structured.get("latest_result"),
    })
