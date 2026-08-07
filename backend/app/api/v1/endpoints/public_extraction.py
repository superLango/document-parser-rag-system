"""一体化公开抽取接口（面向外部系统集成）。

提供免鉴权的端到端文档处理通道，外部系统只需：

1. ``POST /public/extraction/upload`` 上传 PDF → 返回 ``task_id``，后台异步执行
   OCR + Popo 重建 + 五维向量入库 + 结构化抽取全流程。
2. ``GET /public/extraction/{task_id}/status`` 凭 task_id 轮询处理状态。
3. ``GET /public/extraction/{task_id}/result`` 凭 task_id 获取抽取结果 JSON。

KB 归属：抽取强依赖 KB 配置（Schema/Prompt/术语集/LLM 端点），无法绕过。
接口接受可选 ``kb_id`` 参数，未传时使用 ``settings.PUBLIC_KB_ID`` 默认公共 KB。

安全缓解（免鉴权方案的必要补充）：
- task_id 使用雪花 ID，非自增整数，不可顺序枚举。
- 全部接口加 IP 限流（上传 10/分钟，查询 60/分钟）。
- 上传时 ``ensure_extraction_config_valid`` 校验 KB 抽取配置完备，避免无效任务。

RLS 处理：
- 上传接口已知 kb_id，插入记录前 ``activate_rls`` 激活 RLS。
- 查询接口仅有 task_id，凭主键查询需临时 ``SET LOCAL row_security = off`` 绕过 RLS
  （task_id 不可枚举，安全性由雪花 ID + 限流保证，不依赖 RLS 隔离）。
"""

import asyncio
import io
import uuid
from pathlib import Path
from urllib.parse import quote

from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    DEFAULT_LIMIT,
    UPLOAD_LIMIT,
    activate_rls,
    get_db,
    limiter,
)
from app.core.config import settings
from app.core.exceptions import BusinessException, ErrorCode
from app.core.logging import get_logger
from app.core.response import success
from app.core.snowflake import snowflake_generator
from app.models.document import Document
from app.models.task import Task as TaskModel
from app.services.infra.storage_service import storage_service

logger = get_logger(__name__)

router = APIRouter(prefix="/public/extraction", tags=["公开-一体化抽取"])

_arq_pool = None

# 一体化流程状态 → 中文消息映射
_PROCESS_STATUS_MSG: dict[str, str] = {
    "queued": "排队中",
    "ocr_processing": "OCR 解析中",
    "ocr_done": "OCR 完成，等待抽取",
    "extracting": "结构化抽取中",
    "completed": "处理完成",
    "failed": "处理失败",
}

# 终态集合（不再轮询）
_TERMINAL_STATUS = {"completed", "failed"}

# 文件扩展名 → MIME 类型映射
_MIME_MAP: dict[str, str] = {
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


async def _get_arq_pool():
    """获取 arq Redis 连接池（复用 kb_documents 的模式）。"""
    global _arq_pool
    if _arq_pool is None:
        from arq import create_pool
        from arq.connections import RedisSettings

        try:
            _arq_pool = await asyncio.wait_for(
                create_pool(
                    RedisSettings(host="localhost", port=6379, database=1, conn_timeout=3)
                ),
                timeout=5.0,
            )
        except (asyncio.TimeoutError, ConnectionError, OSError) as exc:
            logger.warning("arq Redis 连接失败", error=str(exc))
            raise BusinessException(
                code=ErrorCode.BUSINESS_TASK_FAILED,
                message="任务队列服务不可用，请稍后重试",
            )
    return _arq_pool


def _resolve_kb_id(kb_id_param: str | None) -> uuid.UUID:
    """解析 KB ID：参数优先，否则用 settings.PUBLIC_KB_ID。

    Args:
        kb_id_param: 请求传入的 kb_id（可选）。

    Returns:
        uuid.UUID: 解析后的 KB ID。

    Raises:
        BusinessException: 未提供 kb_id 且未配置 PUBLIC_KB_ID，或格式非法。
    """
    kb_id_str = kb_id_param or settings.PUBLIC_KB_ID
    if not kb_id_str:
        raise BusinessException(
            code=ErrorCode.BUSINESS_TASK_FAILED,
            message="未指定知识库（kb_id），且系统未配置默认公共知识库（PUBLIC_KB_ID）",
        )
    try:
        return uuid.UUID(kb_id_str)
    except (ValueError, TypeError):
        raise BusinessException(
            code=ErrorCode.BUSINESS_TASK_FAILED,
            message=f"知识库 ID 格式非法：{kb_id_str}",
        )


@router.post("/upload", status_code=201)
@limiter.limit(UPLOAD_LIMIT)
async def public_upload(
    request: Request,
    file: UploadFile = File(..., description="待上传的 PDF 文件"),
    kb_id: str | None = Query(None, description="知识库 ID（可选，未传用系统默认公共 KB）"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """一体化上传 PDF（免鉴权）。

    上传后自动入队 ``process_document_task``，后台串联 OCR + 结构化抽取。
    立即返回 ``task_id``，调用方凭此轮询状态与获取结果。

    Args:
        request: FastAPI 请求对象（限流所需）。
        file: 上传的文件。
        kb_id: 可选知识库 ID。
        db: 异步数据库会话。

    Returns:
        dict: ``{task_id, document_id, status: "queued"}``。
    """
    # 1. 解析 KB ID
    kb_uuid = _resolve_kb_id(kb_id)

    # 2. 校验文件大小与扩展名
    content: bytes = await file.read()
    file_size: int = len(content)
    if file_size > settings.MAX_FILE_SIZE:
        raise BusinessException(
            code=ErrorCode.BUSINESS_FILE_TOO_LARGE,
            message=f"文件大小 {file_size} 字节超过上限 {settings.MAX_FILE_SIZE} 字节",
        )
    filename: str = file.filename or "unknown"
    extension: str = Path(filename).suffix.lower()
    if extension not in settings.allowed_extensions_list:
        raise BusinessException(
            code=ErrorCode.BUSINESS_UNSUPPORTED_FILE_TYPE,
            message=f"不支持的文件类型：{extension}，允许：{', '.join(settings.allowed_extensions_list)}",
        )

    # 3. 上传到 KB 专属 bucket
    object_name: str = f"{uuid.uuid4()}{extension}"
    content_type: str = file.content_type or "application/octet-stream"
    await storage_service.upload(object_name, content, content_type, kb_id=kb_uuid)

    # 4. 激活 RLS + 校验 KB 抽取配置完备 + 创建 Document
    await activate_rls(db, kb_uuid)
    from app.services.extraction_config.config_validator import (
        ensure_extraction_config_valid,
    )

    await ensure_extraction_config_valid(db, kb_uuid)

    document = Document(
        kb_id=kb_uuid,
        filename=filename,
        file_size=file_size,
        file_type=extension.lstrip("."),
        status="pending",
        minio_object_name=object_name,
        process_status="queued",
    )
    db.add(document)
    await db.commit()
    await db.refresh(document)

    # 5. 入队一体化编排任务
    pool = await _get_arq_pool()
    job_id = snowflake_generator.generate_id_str()
    job = await pool.enqueue_job(
        "process_document_task",
        str(document.id),
        str(kb_uuid),
        _job_id=job_id,
    )
    if job is None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_TASK_FAILED,
            message="任务提交失败，可能已有相同任务在执行中",
        )

    # 6. 创建 Task 记录 + 回写 process_task_id
    task = TaskModel(
        id=job.job_id,
        kb_id=kb_uuid,
        document_id=document.id,
        task_type="process_document",
        status="pending",
        progress=0,
    )
    db.add(task)
    document.process_task_id = job.job_id
    await db.commit()

    logger.info(
        "公开一体化上传成功",
        kb_id=str(kb_uuid),
        document_id=str(document.id),
        task_id=job.job_id,
        filename=filename,
    )
    return success(
        data={
            "task_id": job.job_id,
            "document_id": str(document.id),
            "status": "queued",
        }
    )


@router.get("/{task_id}/status")
@limiter.limit(DEFAULT_LIMIT)
async def public_status(
    task_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """查询一体化处理状态（免鉴权）。

    Args:
        task_id: 一体化任务 ID（上传时返回）。
        request: FastAPI 请求对象（限流所需）。
        db: 异步数据库会话。

    Returns:
        dict: ``{task_id, document_id, process_status, progress, message, filename}``。
    """
    # 公开接口仅有 task_id，无 kb_id 无法激活 RLS；
    # 凭 task_id 主键查询，临时关闭 RLS（task_id 雪花 ID 不可枚举，安全性由限流保证）
    await db.execute(text("SET LOCAL row_security = off"))
    task = await db.get(TaskModel, task_id)
    if task is None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_TASK_FAILED,
            message=f"任务不存在：{task_id}",
        )

    document = await db.get(Document, task.document_id)
    if document is None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_TASK_FAILED,
            message=f"任务关联的文档不存在：{task_id}",
        )

    process_status = document.process_status or "queued"
    message = _PROCESS_STATUS_MSG.get(process_status, process_status)
    # 失败时优先展示 Task 记录的错误信息
    if process_status == "failed" and task.error_message:
        message = task.error_message

    return success(
        data={
            "task_id": task_id,
            "document_id": str(document.id),
            "process_status": process_status,
            "progress": task.progress or 0,
            "message": message,
            "filename": document.filename,
            "is_terminal": process_status in _TERMINAL_STATUS,
        }
    )


@router.get("/{task_id}/result")
@limiter.limit(DEFAULT_LIMIT)
async def public_result(
    task_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取抽取结果 JSON（免鉴权）。

    Args:
        task_id: 一体化任务 ID。
        request: FastAPI 请求对象（限流所需）。
        db: 异步数据库会话。

    Returns:
        dict: 抽取结果（``structured_data.latest_result``，含 categories/summary/timing）；
        未完成时返回 ``{status, message}``。
    """
    await db.execute(text("SET LOCAL row_security = off"))
    task = await db.get(TaskModel, task_id)
    if task is None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_TASK_FAILED,
            message=f"任务不存在：{task_id}",
        )

    document = await db.get(Document, task.document_id)
    if document is None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_TASK_FAILED,
            message=f"任务关联的文档不存在：{task_id}",
        )

    process_status = document.process_status or "queued"
    if process_status != "completed":
        return success(
            data={
                "status": process_status,
                "message": _PROCESS_STATUS_MSG.get(process_status, process_status),
                "result": None,
            }
        )

    structured = document.structured_data or {}
    latest_result = structured.get("latest_result")

    return success(
        data={
            "status": "completed",
            "task_id": task_id,
            "document_id": str(document.id),
            "filename": document.filename,
            "schema_name": structured.get("latest_schema_name"),
            "extracted_at": structured.get("latest_extracted_at"),
            "summary": structured.get("summary"),
            "timing": structured.get("timing"),
            "result": latest_result,
        }
    )


@router.get("/{task_id}/preview")
@limiter.limit(DEFAULT_LIMIT)
async def public_preview(
    task_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """预览文档原始文件（免鉴权，inline 内联显示）。

    凭 task_id 反查文档，从 KB 专属 bucket 下载原始文件并流式返回。
    PDF 文件在浏览器中内联显示，供嵌入预览页面的左侧 PDF 查看器使用。

    Args:
        task_id: 一体化任务 ID。
        request: FastAPI 请求对象（限流所需）。
        db: 异步数据库会话。

    Returns:
        StreamingResponse: 文件流，``Content-Disposition: inline``。
    """
    await db.execute(text("SET LOCAL row_security = off"))
    task = await db.get(TaskModel, task_id)
    if task is None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_TASK_FAILED,
            message=f"任务不存在：{task_id}",
        )

    document = await db.get(Document, task.document_id)
    if document is None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_TASK_FAILED,
            message=f"任务关联的文档不存在：{task_id}",
        )
    if not document.minio_object_name:
        raise BusinessException(
            code=ErrorCode.BUSINESS_TASK_FAILED,
            message="该文档未关联原始文件",
        )

    try:
        content: bytes = await storage_service.download(
            document.minio_object_name, kb_id=document.kb_id
        )
    except ClientError as err:
        logger.error(
            "公开预览文件下载失败",
            task_id=task_id,
            document_id=str(document.id),
            error=str(err),
        )
        raise BusinessException(
            code=ErrorCode.BUSINESS_TASK_FAILED,
            message="文件读取失败",
        )

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
