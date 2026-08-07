"""知识库内文档管理端点模块（方案 §10.2）。

提供 KB 内文档资源的 CRUD 接口，所有端点强制 ``Depends(get_kb_context)``
实现知识库隔离与 RBAC 权限校验：

- POST   /kbs/{kb_id}/documents                         上传文件到 KB 专属 bucket（editor+）
- GET    /kbs/{kb_id}/documents                         分页查询 KB 内文档（任意成员）
- GET    /kbs/{kb_id}/documents/{document_id}           文档详情
- GET    /kbs/{kb_id}/documents/{document_id}/download  下载原始文件
- GET    /kbs/{kb_id}/documents/{document_id}/preview   预览原始文件
- GET    /kbs/{kb_id}/documents/{document_id}/ocr-text  获取OCR文本
- POST   /kbs/{kb_id}/documents/{document_id}/extract   触发结构化抽取（editor+）
- POST   /kbs/{kb_id}/documents/{document_id}/build-index-graph  构建索引和图谱（editor+）
- GET    /kbs/{kb_id}/documents/{document_id}/viewer-data       文档查看器数据（任意成员）
- DELETE /kbs/{kb_id}/documents/{document_id}           删除文档（editor+，含向量/图谱清理）

知识库隔离要点：
- 文件存储：上传/下载/删除均通过 ``storage_service`` 的 ``kb_id`` 参数路由到
  KB 专属 MinIO bucket（``kb-{kb_id_hex}``）。
- 数据库：``get_kb_context`` 已激活 PostgreSQL RLS（``SET LOCAL app.current_kb``），
  Document/Task 查询自动按 ``kb_id`` 过滤；Document.kb_id 显式设置为当前 KB。
- 向量库：删除文档时调用 ``vector_store.delete_by_doc_id(doc_id, kb_id=...)``
  清理 KB 专属 Collection 内的分块。

与旧 ``documents.py``（全局，向后兼容）共存，本模块为 KB 化主入口。
"""

import asyncio
import io
import json
import uuid
from pathlib import Path
from urllib.parse import quote
from uuid import UUID

from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    AI_LIMIT,
    DEFAULT_LIMIT,
    KBContext,
    UPLOAD_LIMIT,
    get_kb_context,
    get_pagination_params,
    limiter,
    require_role,
)
from app.core.config import settings
from app.core.database import get_db
from app.core.exceptions import BusinessException, ErrorCode, SystemException
from app.core.logging import get_logger
from app.core.response import paginated, success
from app.core.snowflake import snowflake_generator
from app.models.document import Document
from app.models.knowledge_base import EDIT_ROLES
from app.models.task import Task as TaskModel
from app.schemas.document import DocumentResponse
from app.services.infra.storage_service import storage_service
from app.services.infra.export_service import export_data

logger = get_logger(__name__)

router = APIRouter(prefix="/kbs/{kb_id}/documents", tags=["知识库-文档管理"])

_arq_pool = None


async def _get_arq_pool():
    global _arq_pool
    if _arq_pool is None:
        from arq import create_pool
        from arq.connections import RedisSettings
        try:
            _arq_pool = await asyncio.wait_for(
                create_pool(RedisSettings(host="localhost", port=6379, database=1, conn_timeout=3)),
                timeout=5.0,
            )
        except (asyncio.TimeoutError, ConnectionError, OSError) as exc:
            logger.warning("arq Redis 连接失败", error=str(exc))
            raise BusinessException(
                code=ErrorCode.BUSINESS_TASK_FAILED,
                message="任务队列服务不可用，请稍后重试",
            )
    return _arq_pool


@router.post("", status_code=201)
@limiter.limit(UPLOAD_LIMIT)
async def upload_document(
    request: Request,
    file: UploadFile = File(..., description="待上传的文件"),
    kb_ctx: KBContext = Depends(require_role(*EDIT_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """上传文件到知识库专属 bucket 并创建文档记录（editor+）。

    处理流程：
        1. 校验文件大小与扩展名。
        2. 生成对象名，上传到 KB 专属 MinIO bucket。
        3. 创建 Document 记录（kb_id = 当前 KB，owner_id = 当前用户）。
        4. 返回文档元信息。

    Args:
        request: FastAPI 请求对象（slowapi 限流所需）。
        file: 上传的文件对象。
        kb_ctx: 知识库上下文（已校验角色 + 激活 RLS）。
        db: 异步数据库会话。

    Returns:
        dict: 包含文档元信息的统一成功响应。
    """
    content: bytes = await file.read()
    file_size: int = len(content)

    # 校验文件大小
    if file_size > settings.MAX_FILE_SIZE:
        raise BusinessException(
            code=ErrorCode.BUSINESS_FILE_TOO_LARGE,
            message=f"文件大小 {file_size} 字节超过上限 {settings.MAX_FILE_SIZE} 字节",
        )

    # 校验文件扩展名
    filename: str = file.filename or "unknown"
    extension: str = Path(filename).suffix.lower()
    if extension not in settings.allowed_extensions_list:
        raise BusinessException(
            code=ErrorCode.BUSINESS_UNSUPPORTED_FILE_TYPE,
            message=f"不支持的文件类型：{extension}，允许：{', '.join(settings.allowed_extensions_list)}",
        )

    # 上传到 KB 专属 bucket
    object_name: str = f"{uuid.uuid4()}{extension}"
    content_type: str = file.content_type or "application/octet-stream"
    await storage_service.upload(object_name, content, content_type, kb_id=kb_ctx.kb_id)

    # 创建文档记录（kb_id 显式设置，RLS 亦强制隔离）
    document = Document(
        kb_id=kb_ctx.kb_id,
        filename=filename,
        file_size=file_size,
        file_type=extension.lstrip("."),
        status="pending",
        minio_object_name=object_name,
        owner_id=kb_ctx.user.id,
    )
    db.add(document)
    await db.commit()
    await db.refresh(document)

    logger.info(
        "KB 文档上传成功",
        kb_id=str(kb_ctx.kb_id),
        document_id=str(document.id),
        filename=filename,
        object_name=object_name,
    )
    return success(data=DocumentResponse.model_validate(document).model_dump())


@router.get("")
@limiter.limit(DEFAULT_LIMIT)
async def list_documents(
    request: Request,
    kb_ctx: KBContext = Depends(get_kb_context),
    pagination: dict = Depends(get_pagination_params),
    db: AsyncSession = Depends(get_db),
    status: str | None = Query(None, description="按状态过滤：pending/processing/completed/failed"),
) -> dict:
    """分页查询知识库内文档列表（任意成员）。

    RLS 已按 kb_id 过滤，此处查询自动限定在当前 KB。

    Args:
        kb_ctx: 知识库上下文。
        pagination: 分页参数。
        db: 异步数据库会话。
        status: 可选状态过滤。

    Returns:
        dict: 分页文档列表。
    """
    page: int = pagination["page"]
    page_size: int = pagination["page_size"]

    # 显式按 kb_id 过滤，纵深防御不依赖 RLS（superuser 绕过 RLS）
    base_stmt = select(Document).where(Document.kb_id == kb_ctx.kb_id)
    count_stmt = (
        select(func.count()).select_from(Document).where(Document.kb_id == kb_ctx.kb_id)
    )
    if status:
        base_stmt = base_stmt.where(Document.status == status)
        count_stmt = count_stmt.where(Document.status == status)

    total: int = (await db.execute(count_stmt)).scalar_one()

    offset: int = (page - 1) * page_size
    list_stmt = (
        base_stmt.order_by(Document.created_at.desc()).offset(offset).limit(page_size)
    )
    documents = (await db.execute(list_stmt)).scalars().all()

    items = [DocumentResponse.model_validate(doc).model_dump() for doc in documents]
    return paginated(items, total, page, page_size)


@router.get("/export")
async def export_documents(
    kb_ctx: KBContext = Depends(get_kb_context),
    db: AsyncSession = Depends(get_db),
    format: str = Query("excel", description="导出格式：excel/csv/json"),
    status: str | None = Query(None, description="按状态过滤"),
) -> StreamingResponse:
    """导出 KB 内文档列表为 Excel/CSV/JSON（任意成员）。

    RLS 已按 kb_id 过滤，导出当前 KB 全部文档元数据（不含文件内容）。
    """
    # 显式按 kb_id 过滤，纵深防御不依赖 RLS（superuser 绕过 RLS）
    stmt = (
        select(Document)
        .where(Document.kb_id == kb_ctx.kb_id)
        .order_by(Document.created_at.desc())
    )
    if status:
        stmt = stmt.where(Document.status == status)
    documents = (await db.execute(stmt)).scalars().all()

    rows = [
        {
            "id": str(d.id),
            "filename": d.filename,
            "file_size": d.file_size,
            "file_type": d.file_type or "",
            "status": d.status,
            "owner_id": str(d.owner_id) if d.owner_id else "",
            "created_at": d.created_at.isoformat() if d.created_at else "",
            "updated_at": d.updated_at.isoformat() if d.updated_at else "",
        }
        for d in documents
    ]
    columns = [
        {"key": "id", "label": "文档ID"},
        {"key": "filename", "label": "文件名"},
        {"key": "file_size", "label": "大小(字节)"},
        {"key": "file_type", "label": "类型"},
        {"key": "status", "label": "状态"},
        {"key": "owner_id", "label": "上传者ID"},
        {"key": "created_at", "label": "上传时间"},
        {"key": "updated_at", "label": "更新时间"},
    ]
    return export_data(rows, columns, format=format, sheet_name="文档列表", filename_prefix="documents")


@router.get("/{document_id}")
async def get_document(
    document_id: UUID,
    kb_ctx: KBContext = Depends(get_kb_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取文档详情。

    RLS 已按 kb_id 过滤，跨 KB 文档查询返回 None。

    Raises:
        BusinessException: 文档不存在或不在当前 KB 时抛出。
    """
    document = await db.get(Document, document_id)
    if document is None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_DOCUMENT_NOT_FOUND,
            message=f"文档 {document_id} 不存在",
        )
    # RLS 已保证 document 属于当前 KB；额外防御性校验
    if document.kb_id != kb_ctx.kb_id:
        logger.warning(
            "跨 KB 文档访问被拒",
            kb_id=str(kb_ctx.kb_id),
            document_id=str(document_id),
            doc_kb_id=str(document.kb_id),
        )
        raise BusinessException(
            code=ErrorCode.BUSINESS_DOCUMENT_NOT_FOUND,
            message=f"文档 {document_id} 不存在",
        )
    return success(data=DocumentResponse.model_validate(document).model_dump())


# 文件扩展名 → MIME 类型映射
_MIME_MAP = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".tiff": "image/tiff",
    ".tif": "image/tiff",
    ".bmp": "image/bmp",
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".webp": "image/webp",
}


@router.get("/{document_id}/download")
async def download_document(
    document_id: UUID,
    kb_ctx: KBContext = Depends(get_kb_context),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """下载文档原始文件（从 KB 专属 bucket）。

    Raises:
        BusinessException: 文档不存在或未关联原始文件时抛出。
        SystemException: 文件读取失败时抛出。
    """
    document = await db.get(Document, document_id)
    if document is None or document.kb_id != kb_ctx.kb_id:
        raise BusinessException(
            code=ErrorCode.BUSINESS_DOCUMENT_NOT_FOUND,
            message=f"文档 {document_id} 不存在",
        )

    if not document.minio_object_name:
        raise BusinessException(
            code=ErrorCode.BUSINESS_DOCUMENT_NOT_FOUND,
            message="该文档未关联原始文件，可能为历史数据，请重新上传后再试",
        )

    try:
        content: bytes = await storage_service.download(
            document.minio_object_name, kb_id=kb_ctx.kb_id
        )
    except ClientError as err:
        logger.error(
            "KB 文档下载失败",
            kb_id=str(kb_ctx.kb_id),
            document_id=str(document_id),
            error=str(err),
        )
        raise SystemException(message="文件读取失败")

    ascii_filename = document.filename.encode("ascii", "ignore").decode("ascii") or "document.pdf"
    utf8_filename = quote(document.filename, safe="")
    ext = f".{document.file_type}" if document.file_type else ""
    media_type = _MIME_MAP.get(ext.lower(), "application/octet-stream")
    return StreamingResponse(
        io.BytesIO(content),
        media_type=media_type,
        headers={
            "Content-Disposition": (
                f"inline; filename=\"{ascii_filename}\"; filename*=UTF-8''{utf8_filename}"
            ),
        },
    )


@router.get("/{document_id}/preview")
async def preview_document(
    document_id: UUID,
    kb_ctx: KBContext = Depends(get_kb_context),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """预览文档原始文件（inline，浏览器内联显示，任意成员）。

    根据 file_type 设置正确 MIME 类型，支持 PDF/图片/文本预览。
    """
    document = await db.get(Document, document_id)
    if document is None or document.kb_id != kb_ctx.kb_id:
        raise BusinessException(
            code=ErrorCode.BUSINESS_DOCUMENT_NOT_FOUND,
            message=f"文档 {document_id} 不存在",
        )
    if not document.minio_object_name:
        raise BusinessException(
            code=ErrorCode.BUSINESS_DOCUMENT_NOT_FOUND,
            message="该文档未关联原始文件",
        )
    try:
        content: bytes = await storage_service.download(
            document.minio_object_name, kb_id=kb_ctx.kb_id
        )
    except ClientError as err:
        logger.error("KB 文档预览失败", kb_id=str(kb_ctx.kb_id), document_id=str(document_id), error=str(err))
        raise SystemException(message="文件读取失败")

    ext = (Path(document.filename).suffix or "").lower()
    media_type = _MIME_MAP.get(ext, "application/octet-stream")
    ascii_filename = document.filename.encode("ascii", "ignore").decode("ascii") or "document"
    utf8_filename = quote(document.filename, safe="")
    return StreamingResponse(
        io.BytesIO(content),
        media_type=media_type,
        headers={
            "Content-Disposition": f"inline; filename=\"{ascii_filename}\"; filename*=UTF-8''{utf8_filename}",
            "Cache-Control": "private, max-age=3600",
        },
    )


@router.get("/{document_id}/ocr-text")
async def get_ocr_text(
    document_id: UUID,
    kb_ctx: KBContext = Depends(get_kb_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取文档 OCR 解析文本与 Popo 后处理 JSON（任意成员）。

    返回 parsed_text（Markdown）、layout_data（版面块）、popo_json（Popo 处理后的完整 JSON），
    structured_data 保留兼容但文档查看页优先展示 popo_json。
    """
    document = await db.get(Document, document_id)
    if document is None or document.kb_id != kb_ctx.kb_id:
        raise BusinessException(
            code=ErrorCode.BUSINESS_DOCUMENT_NOT_FOUND,
            message=f"文档 {document_id} 不存在",
        )

    # 读取 Popo 处理后的 JSON（与 viewer-data 逻辑一致）
    popo_json = None
    markdown_content = document.markdown_content or document.parsed_text or ""
    layout_data = document.layout_data or {}
    try:
        from app.services.vector.reconstruction_service import reconstruction_service

        ocr_output_dir = layout_data.get("output_dir", "")
        if ocr_output_dir:
            task_dir = Path(ocr_output_dir)
        else:
            task_dir = reconstruction_service._get_task_dir(
                str(document_id), kb_id=str(kb_ctx.kb_id)
            )

        if not markdown_content:
            md_path = task_dir / "reconstructed.md"
            if md_path.exists():
                markdown_content = md_path.read_text(encoding="utf-8")

        popo_output_dir = task_dir / "popo_output"
        if popo_output_dir.exists():
            json_files = list(popo_output_dir.glob("*.json"))
            if json_files:
                with json_files[0].open("r", encoding="utf-8") as f:
                    popo_json = json.load(f)
    except Exception as exc:
        logger.warning("读取 Popo 输出失败", document_id=str(document_id), error=str(exc))

    return success(data={
        "document_id": str(document.id),
        "filename": document.filename,
        "parsed_text": markdown_content,
        "layout_data": layout_data,
        "popo_json": popo_json,
        "structured_data": document.structured_data,
        "status": document.status,
        "file_type": document.file_type,
    })


@router.post("/{document_id}/extract", status_code=201)
@limiter.limit(AI_LIMIT)
async def extract_document(
    document_id: UUID,
    request: Request,
    kb_ctx: KBContext = Depends(require_role(*EDIT_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """触发文档结构化抽取任务（editor+）。

    投递 extract_document_task 到 arq 队列，执行 Popo Markdown 结构化抽取。
    """
    document = await db.get(Document, document_id)
    if document is None or document.kb_id != kb_ctx.kb_id:
        raise BusinessException(
            code=ErrorCode.BUSINESS_DOCUMENT_NOT_FOUND,
            message=f"文档 {document_id} 不存在",
        )
    if document.status != "completed":
        raise BusinessException(
            code=ErrorCode.BUSINESS_TASK_FAILED,
            message=f"文档未完成解析，当前状态: {document.status}",
        )

    # 提交抽取前对知识库抽取配置做完整校验（任一配置缺失/无效即报错，直到全部通过）
    from app.services.extraction_config.config_validator import ensure_extraction_config_valid

    await ensure_extraction_config_valid(db, kb_ctx.kb_id)

    document.extraction_status = None
    await db.commit()

    pool = await _get_arq_pool()
    job_id = snowflake_generator.generate_id_str()
    job = await pool.enqueue_job(
        "extract_document_task",
        str(document_id),
        str(kb_ctx.kb_id),
        _job_id=job_id,
    )
    if job is None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_TASK_FAILED,
            message="抽取任务提交失败，可能已有相同任务在执行中",
        )

    task = TaskModel(
        id=job.job_id,
        kb_id=kb_ctx.kb_id,
        document_id=document_id,
        task_type="extract_document",
        status="pending",
        progress=0,
    )
    db.add(task)
    await db.commit()

    logger.info(
        "KB 文档抽取任务已提交",
        kb_id=str(kb_ctx.kb_id),
        document_id=str(document_id),
        job_id=job.job_id,
    )
    return success(data={"task_id": job.job_id, "status": "pending"})


@router.post("/{document_id}/build-index-graph", status_code=201)
@limiter.limit(AI_LIMIT)
async def build_index_graph(
    document_id: UUID,
    request: Request,
    kb_ctx: KBContext = Depends(require_role(*EDIT_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """触发RAG向量索引构建和图谱构建任务（editor+）。

    投递 build_index_graph_task 到 arq 队列，执行向量入库和知识图谱构建。
    """
    document = await db.get(Document, document_id)
    if document is None or document.kb_id != kb_ctx.kb_id:
        raise BusinessException(
            code=ErrorCode.BUSINESS_DOCUMENT_NOT_FOUND,
            message=f"文档 {document_id} 不存在",
        )
    if document.status != "completed":
        raise BusinessException(
            code=ErrorCode.BUSINESS_TASK_FAILED,
            message=f"文档未完成解析，当前状态: {document.status}",
        )

    document.index_status = "indexing"
    document.graph_status = None
    document.graph_error = None
    await db.commit()

    pool = await _get_arq_pool()
    job_id = snowflake_generator.generate_id_str()
    job = await pool.enqueue_job(
        "build_index_graph_task",
        str(document_id),
        str(kb_ctx.kb_id),
        _job_id=job_id,
    )
    if job is None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_TASK_FAILED,
            message="索引构建任务提交失败，可能已有相同任务在执行中",
        )

    task = TaskModel(
        id=job.job_id,
        kb_id=kb_ctx.kb_id,
        document_id=document_id,
        task_type="build_index_graph",
        status="pending",
        progress=0,
    )
    db.add(task)
    await db.commit()

    logger.info(
        "KB 文档索引/图谱构建任务已提交",
        kb_id=str(kb_ctx.kb_id),
        document_id=str(document_id),
        job_id=job.job_id,
    )
    return success(data={"task_id": job.job_id, "status": "pending"})


@router.get("/{document_id}/viewer-data")
async def get_viewer_data(
    document_id: UUID,
    kb_ctx: KBContext = Depends(get_kb_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取文档查看器数据（任意成员）。

    返回文档解析状态、原始文件URL、bbox版面数据、Markdown内容、结构化数据等。
    """
    document = await db.get(Document, document_id)
    if document is None or document.kb_id != kb_ctx.kb_id:
        raise BusinessException(
            code=ErrorCode.BUSINESS_DOCUMENT_NOT_FOUND,
            message=f"文档 {document_id} 不存在",
        )

    original_file_url = document.minio_object_name
    if document.minio_object_name:
        try:
            original_file_url = await storage_service.get_presigned_url(
                document.minio_object_name, expires=3600, kb_id=kb_ctx.kb_id
            )
        except Exception as exc:
            logger.warning("生成预签名URL失败", error=str(exc))
            original_file_url = document.minio_object_name

    markdown_content = document.markdown_content
    popo_json = None
    total_pages = None
    layout_data = document.layout_data or {}

    try:
        from app.services.vector.reconstruction_service import reconstruction_service

        # 从layout_data.output_dir获取正确的任务目录（包含task_id）
        ocr_output_dir = layout_data.get("output_dir", "")
        if ocr_output_dir:
            task_dir = Path(ocr_output_dir)
        else:
            # fallback: 通过kb_id+document_id查找
            task_dir = reconstruction_service._get_task_dir(str(document_id), kb_id=str(kb_ctx.kb_id))

        if not markdown_content:
            md_path = task_dir / "reconstructed.md"
            if md_path.exists():
                markdown_content = md_path.read_text(encoding="utf-8")

        popo_output_dir = task_dir / "popo_output"
        if popo_output_dir.exists():
            json_files = list(popo_output_dir.glob("*.json"))
            if json_files:
                with json_files[0].open("r", encoding="utf-8") as f:
                    popo_json = json.load(f)
    except Exception as exc:
        logger.warning("读取任务目录文件失败", document_id=str(document_id), error=str(exc))

    if layout_data.get("total_pages"):
        total_pages = layout_data["total_pages"]
    elif popo_json and isinstance(popo_json, dict):
        if "total_pages" in popo_json:
            total_pages = popo_json["total_pages"]
        elif "pages" in popo_json:
            total_pages = len(popo_json.get("pages", []))

    # 构建bbox_data：从layout_data.merged提取版面块坐标，供前端渲染
    merged_blocks = layout_data.get("merged", []) or []
    bbox_blocks = []
    for block in merged_blocks:
        bbox_blocks.append({
            "page": block.get("page_index") or block.get("page", 0),
            "bbox": block.get("bbox", []),
            "type": block.get("block_type", ""),
            "text": block.get("text", "") or block.get("block_content", ""),
            "block_id": block.get("block_id", ""),
        })

    return success(data={
        "document_id": str(document.id),
        "filename": document.filename,
        "status": document.status,
        "extraction_status": document.extraction_status,
        "index_status": document.index_status,
        "graph_status": document.graph_status,
        "graph_error": document.graph_error,
        "original_file_url": original_file_url,
        "bbox_data": bbox_blocks,
        "markdown_content": markdown_content,
        "structured_data": document.structured_data,
        "popo_json": popo_json,
        "total_pages": total_pages,
    })


async def _async_cleanup_document_resources(
    doc_id_str: str,
    obj_name: str | None,
    kb_id: uuid.UUID,
) -> None:
    """异步后台清理文档关联资源（MinIO + 向量库 + 图谱）。

    在 DB 记录删除后以后台任务方式执行，不阻塞用户请求。
    各步骤独立容错且带超时保护，单步失败仅记录警告。
    """
    # 1. 删除 MinIO 对象（超时 10s）
    if obj_name:
        try:
            await asyncio.wait_for(
                storage_service.delete(obj_name, kb_id=kb_id),
                timeout=10.0,
            )
            logger.info("后台清理：MinIO 对象删除完成", document_id=doc_id_str)
        except asyncio.TimeoutError:
            logger.warning("后台清理：MinIO 对象删除超时（10s）", document_id=doc_id_str)
        except Exception as err:  # noqa: BLE001
            logger.warning("后台清理：MinIO 对象删除失败", document_id=doc_id_str, error=str(err)[:200])

    # 2. 删除向量库分块（超时 15s，后台可稍长）
    try:
        from app.services.vector.chunk_vector_store import vector_store
        await asyncio.wait_for(
            vector_store.delete_by_doc_id(doc_id_str, kb_id=kb_id),
            timeout=15.0,
        )
        logger.info("后台清理：向量库分块删除完成", document_id=doc_id_str)
    except asyncio.TimeoutError:
        logger.warning("后台清理：向量库分块删除超时（15s）", document_id=doc_id_str)
    except Exception as err:  # noqa: BLE001
        logger.warning("后台清理：向量库分块删除失败", document_id=doc_id_str, error=str(err)[:200])

    # 3. 删除图谱节点（超时 10s）
    try:
        from app.services.graph.graph_store import graph_store
        if hasattr(graph_store, "delete_by_doc"):
            await asyncio.wait_for(
                graph_store.delete_by_doc(doc_id_str, kb_id=kb_id),
                timeout=10.0,
            )
            logger.info("后台清理：图谱节点删除完成", document_id=doc_id_str)
    except asyncio.TimeoutError:
        logger.warning("后台清理：图谱节点删除超时（10s）", document_id=doc_id_str)
    except Exception as err:  # noqa: BLE001
        logger.warning("后台清理：图谱节点删除失败", document_id=doc_id_str, error=str(err)[:200])


@router.delete("/{document_id}")
async def delete_document(
    document_id: UUID,
    kb_ctx: KBContext = Depends(require_role(*EDIT_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """删除文档（editor+）。

    优化策略：先快速删除 DB 记录（Task + Document，<100ms），
    然后异步后台清理资源（MinIO + 向量库 + 图谱），用户无需等待。

    Args:
        document_id: 文档唯一标识。
        kb_ctx: 知识库上下文（已校验 editor+ 角色）。
        db: 异步数据库会话。

    Returns:
        dict: 删除结果。
    """
    document = await db.get(Document, document_id)
    if document is None or document.kb_id != kb_ctx.kb_id:
        raise BusinessException(
            code=ErrorCode.BUSINESS_DOCUMENT_NOT_FOUND,
            message=f"文档 {document_id} 不存在",
        )

    doc_id_str = str(document_id)
    obj_name = document.minio_object_name

    # 1. 删除关联的 Task 记录（外键约束，必须先于 Document 删除）
    try:
        await db.execute(
            delete(TaskModel).where(TaskModel.document_id == document_id)
        )
    except Exception as err:  # noqa: BLE001
        logger.warning(
            "删除文档时关联 Task 清理失败（继续）",
            kb_id=str(kb_ctx.kb_id), document_id=doc_id_str, error=str(err),
        )

    # 2. 删除 Document 记录（用户最关心的，快速完成）
    await db.execute(
        delete(Document).where(
            Document.id == document_id,
            Document.kb_id == kb_ctx.kb_id,
        )
    )
    await db.commit()

    logger.info(
        "KB 文档删除成功（DB 记录已删，资源后台清理中）",
        kb_id=str(kb_ctx.kb_id),
        document_id=doc_id_str,
        user_id=str(kb_ctx.user.id),
    )

    # 3. 异步后台清理资源（不阻塞响应）
    asyncio.create_task(
        _async_cleanup_document_resources(
            doc_id_str=doc_id_str,
            obj_name=obj_name,
            kb_id=kb_ctx.kb_id,
        )
    )

    return success(message="删除成功")


# ============================================================
# 批量操作（阶段 2.3）
# ============================================================
class BatchDeleteRequest(BaseModel):
    """批量删除请求体。"""
    document_ids: list[UUID]


@router.post("/batch-delete")
@limiter.limit(UPLOAD_LIMIT)
async def batch_delete_documents(
    request: Request,
    body: BatchDeleteRequest,
    kb_ctx: KBContext = Depends(require_role(*EDIT_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """批量删除文档（editor+）。

    优化策略：先快速删除 DB 记录（Task + Document），然后异步后台清理资源。
    单条失败不阻断其余，返回每条结果。RLS 已按 kb_id 过滤。
    """
    results: list[dict] = []
    pending_cleanups: list[tuple[str, str | None, uuid.UUID]] = []
    for doc_id in body.document_ids:
        try:
            document = await db.get(Document, doc_id)
            if document is None or document.kb_id != kb_ctx.kb_id:
                results.append({"id": str(doc_id), "ok": False, "error": "不存在"})
                continue
            obj_name = document.minio_object_name
            # 删除关联的 Task 记录（外键约束，必须先于 Document 删除）
            try:
                await db.execute(
                    delete(TaskModel).where(TaskModel.document_id == doc_id)
                )
            except Exception as err:  # noqa: BLE001
                logger.warning("批量删除 Task 清理失败", document_id=str(doc_id), error=str(err))
            # 删除 Document 记录
            await db.execute(
                delete(Document).where(
                    Document.id == doc_id,
                    Document.kb_id == kb_ctx.kb_id,
                )
            )
            # 收集待清理资源（稍后异步执行）
            pending_cleanups.append((str(doc_id), obj_name, kb_ctx.kb_id))
            results.append({"id": str(doc_id), "ok": True, "error": None})
        except Exception as err:  # noqa: BLE001
            results.append({"id": str(doc_id), "ok": False, "error": str(err)[:200]})
    await db.commit()

    # 异步后台清理所有文档的资源（不阻塞响应）
    for doc_id_str, obj_name, kb_id in pending_cleanups:
        asyncio.create_task(
            _async_cleanup_document_resources(doc_id_str, obj_name, kb_id)
        )

    ok_count = sum(1 for r in results if r["ok"])
    return success(data={"results": results, "total": len(results), "success": ok_count, "failed": len(results) - ok_count})


@router.post("/batch-upload", status_code=201)
@limiter.limit(UPLOAD_LIMIT)
async def batch_upload_documents(
    request: Request,
    files: list[UploadFile] = File(..., description="待上传的文件列表"),
    kb_ctx: KBContext = Depends(require_role(*EDIT_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """批量上传文件到知识库专属 bucket（editor+）。

    处理流程：
        1. 校验文件数量和每个文件的大小/扩展名。
        2. 逐个上传到 KB 专属 MinIO bucket。
        3. 为每个成功上传的文件创建 Document 记录。
        4. 返回每个文件的上传结果（成功/失败+原因）。

    Args:
        request: FastAPI 请求对象（slowapi 限流所需）。
        files: 上传的文件列表。
        kb_ctx: 知识库上下文（已校验角色 + 激活 RLS）。
        db: 异步数据库会话。

    Returns:
        dict: 包含每个文件上传结果的统一成功响应。
    """
    results: list[dict] = []
    uploaded_docs: list[Document] = []

    for file in files:
        filename = file.filename or "unknown"
        try:
            content: bytes = await file.read()
            file_size = len(content)

            if file_size > settings.MAX_FILE_SIZE:
                results.append({
                    "filename": filename,
                    "ok": False,
                    "error": f"文件大小超过上限 {settings.MAX_FILE_SIZE} 字节",
                })
                continue

            extension = Path(filename).suffix.lower()
            if extension not in settings.allowed_extensions_list:
                results.append({
                    "filename": filename,
                    "ok": False,
                    "error": f"不支持的文件类型：{extension}",
                })
                continue

            object_name = f"{uuid.uuid4()}{extension}"
            content_type = file.content_type or "application/octet-stream"
            await storage_service.upload(object_name, content, content_type, kb_id=kb_ctx.kb_id)

            document = Document(
                kb_id=kb_ctx.kb_id,
                filename=filename,
                file_size=file_size,
                file_type=extension.lstrip("."),
                status="pending",
                minio_object_name=object_name,
                owner_id=kb_ctx.user.id,
            )
            db.add(document)
            uploaded_docs.append(document)
            results.append({
                "filename": filename,
                "ok": True,
                "error": None,
            })
        except Exception as err:  # noqa: BLE001
            logger.warning("批量上传文件失败", filename=filename, error=str(err))
            results.append({
                "filename": filename,
                "ok": False,
                "error": str(err)[:200],
            })

    await db.commit()
    for doc in uploaded_docs:
        await db.refresh(doc)

    ok_count = sum(1 for r in results if r["ok"])
    logger.info(
        "KB 批量上传完成",
        kb_id=str(kb_ctx.kb_id),
        total=len(files),
        success=ok_count,
        failed=len(files) - ok_count,
    )
    return success(data={
        "results": results,
        "total": len(files),
        "success": ok_count,
        "failed": len(files) - ok_count,
    })
