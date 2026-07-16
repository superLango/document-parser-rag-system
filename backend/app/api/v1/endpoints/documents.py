"""文档管理端点模块。

本模块定义文档资源的 CRUD 接口，包括：

- ``POST /documents/``：上传文件到 MinIO 并创建文档记录
- ``GET /documents/``：分页查询文档列表
- ``GET /documents/{document_id}``：获取文档详情
- ``GET /documents/{document_id}/download``：下载文档文件内容（PDF 预览）
- ``DELETE /documents/{document_id}``：删除文档（同时清理 MinIO 对象）

所有接口均需 Bearer Token 鉴权，并通过 slowapi 对上传接口实施限流。
统一响应体由 ``app.core.response`` 中的 ``success`` / ``paginated`` 构造。
"""

import io
import uuid
from pathlib import Path
from uuid import UUID

from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, get_pagination_params, limiter
from app.core.config import settings
from app.core.database import get_db
from app.core.exceptions import BusinessException, ErrorCode, SystemException
from app.core.logging import get_logger
from app.core.response import paginated, success
from app.models.document import Document
from app.models.user import User
from app.schemas.document import DocumentResponse
from app.services.storage_service import storage_service

logger = get_logger(__name__)

router = APIRouter(prefix="/documents", tags=["文件管理"])


@router.post("/")
@limiter.limit("10/minute")
async def upload_document(
    request: Request,
    file: UploadFile = File(..., description="待上传的文件"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """上传文件并创建文档记录。

    处理流程：
        1. 读取上传文件内容并校验大小与扩展名。
        2. 生成 UUID 作为对象名，上传到 MinIO 存储桶。
        3. 在数据库中创建文档记录，初始状态为 ``pending``。
        4. 返回文档元信息。

    限流：每分钟最多 10 次请求。

    Args:
        request: FastAPI 请求对象（slowapi 限流所需）。
        file: 上传的文件对象。
        db: 异步数据库会话。
        current_user: 当前已认证用户。

    Returns:
        dict: 包含文档元信息的统一成功响应。

    Raises:
        BusinessException: 文件过大或不支持的扩展名时抛出。
    """
    # 读取文件内容
    content: bytes = await file.read()
    file_size: int = len(content)

    # 校验文件大小
    if file_size > settings.MAX_FILE_SIZE:
        logger.warning(
            "文件大小超限",
            file_size=file_size,
            max_size=settings.MAX_FILE_SIZE,
        )
        raise BusinessException(
            code=ErrorCode.BUSINESS_FILE_TOO_LARGE,
            message=f"文件大小 {file_size} 字节超过上限 "
            f"{settings.MAX_FILE_SIZE} 字节",
        )

    # 校验文件扩展名
    filename: str = file.filename or "unknown"
    extension: str = Path(filename).suffix.lower()
    if extension not in settings.allowed_extensions_list:
        logger.warning("不支持的文件类型", filename=filename, extension=extension)
        raise BusinessException(
            code=ErrorCode.BUSINESS_UNSUPPORTED_FILE_TYPE,
            message=f"不支持的文件类型：{extension}，"
            f"允许的类型：{', '.join(settings.allowed_extensions_list)}",
        )

    # 生成对象名（UUID + 扩展名）并上传到 MinIO
    object_name: str = f"{uuid.uuid4()}{extension}"
    content_type: str = file.content_type or "application/octet-stream"
    await storage_service.upload(object_name, content, content_type)

    # 创建文档记录
    document = Document(
        filename=filename,
        file_size=file_size,
        file_type=extension.lstrip("."),
        status="pending",
        minio_object_name=object_name,
    )
    db.add(document)
    await db.commit()
    await db.refresh(document)

    logger.info(
        "文档上传成功",
        document_id=str(document.id),
        filename=filename,
        object_name=object_name,
    )
    return success(data=DocumentResponse.model_validate(document).model_dump())


@router.get("/")
async def list_documents(
    pagination: dict = Depends(get_pagination_params),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """分页查询文档列表。

    Args:
        pagination: 分页参数字典，包含 ``page`` 与 ``page_size``。
        db: 异步数据库会话。
        current_user: 当前已认证用户。

    Returns:
        dict: 包含分页文档列表的统一成功响应。
    """
    page: int = pagination["page"]
    page_size: int = pagination["page_size"]

    # 查询总数
    count_stmt = select(func.count()).select_from(Document)
    total_result = await db.execute(count_stmt)
    total: int = total_result.scalar_one()

    # 查询当前页数据（按创建时间降序）
    offset: int = (page - 1) * page_size
    list_stmt = (
        select(Document)
        .order_by(Document.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    result = await db.execute(list_stmt)
    documents = result.scalars().all()

    items: list[dict] = [
        DocumentResponse.model_validate(doc).model_dump() for doc in documents
    ]
    return paginated(items, total, page, page_size)


@router.get("/{document_id}")
async def get_document(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """获取文档详情。

    Args:
        document_id: 文档唯一标识。
        db: 异步数据库会话。
        current_user: 当前已认证用户。

    Returns:
        dict: 包含文档详情的统一成功响应。

    Raises:
        BusinessException: 文档不存在时抛出 ``BUSINESS_DOCUMENT_NOT_FOUND``。
    """
    stmt = select(Document).where(Document.id == document_id)
    result = await db.execute(stmt)
    document = result.scalar_one_or_none()

    if document is None:
        logger.warning("文档不存在", document_id=str(document_id))
        raise BusinessException(
            code=ErrorCode.BUSINESS_DOCUMENT_NOT_FOUND,
            message=f"文档 {document_id} 不存在",
        )

    return success(data=DocumentResponse.model_validate(document).model_dump())


@router.get("/{document_id}/download")
async def download_document(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> StreamingResponse:
    """下载文档文件内容（供前端 PDF 预览组件使用）。

    根据文档 ID 查询记录，从 S3兼容存储(SeaweedFS) 读取对象内容，
    以 ``application/pdf`` 流形式返回，前端可直接用于 PDF 预览。
    该端点直接返回文件流，不包装在统一响应体中。

    Args:
        document_id: 文档唯一标识。
        db: 异步数据库会话。
        current_user: 当前已认证用户。

    Returns:
        StreamingResponse: 以 ``application/pdf`` 形式返回的文件流。

    Raises:
        BusinessException: 文档不存在时抛出 ``BUSINESS_DOCUMENT_NOT_FOUND``。
        SystemException: 文件读取失败时抛出。
    """
    # 查询文档记录，确认存在
    stmt = select(Document).where(Document.id == document_id)
    result = await db.execute(stmt)
    document = result.scalar_one_or_none()

    if document is None:
        logger.warning("文档不存在", document_id=str(document_id))
        raise BusinessException(
            code=ErrorCode.BUSINESS_DOCUMENT_NOT_FOUND,
            message=f"文档 {document_id} 不存在",
        )

    # 从存储服务下载文件内容
    try:
        content: bytes = await storage_service.download(document.minio_object_name)
    except ClientError as err:
        logger.error(
            "文件下载失败",
            document_id=str(document_id),
            object_name=document.minio_object_name,
            error=str(err),
        )
        raise SystemException(message="文件读取失败")

    logger.info(
        "文档下载成功",
        document_id=str(document_id),
        filename=document.filename,
        size=len(content),
    )
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{document.filename}"',
        },
    )


@router.delete("/{document_id}")
async def delete_document(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """删除文档。

    同时清理 MinIO 中的对象文件与数据库中的文档记录。

    Args:
        document_id: 文档唯一标识。
        db: 异步数据库会话。
        current_user: 当前已认证用户。

    Returns:
        dict: 包含删除成功消息的统一成功响应。

    Raises:
        BusinessException: 文档不存在时抛出 ``BUSINESS_DOCUMENT_NOT_FOUND``。
    """
    stmt = select(Document).where(Document.id == document_id)
    result = await db.execute(stmt)
    document = result.scalar_one_or_none()

    if document is None:
        logger.warning("文档不存在", document_id=str(document_id))
        raise BusinessException(
            code=ErrorCode.BUSINESS_DOCUMENT_NOT_FOUND,
            message=f"文档 {document_id} 不存在",
        )

    # 先删除 MinIO 对象（幂等，对象不存在也视为成功）
    if document.minio_object_name:
        await storage_service.delete(document.minio_object_name)

    # 再删除数据库记录
    delete_stmt = delete(Document).where(Document.id == document_id)
    await db.execute(delete_stmt)
    await db.commit()

    logger.info("文档删除成功", document_id=str(document_id))
    return success(message="删除成功")
