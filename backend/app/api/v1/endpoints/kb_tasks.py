"""知识库内任务管理端点模块（方案 §10.3）。

提供 KB 内异步解析任务的提交、查询与重试接口，所有端点强制
``Depends(get_kb_context)`` 实现知识库隔离与 RBAC 权限校验：

- POST /kbs/{kb_id}/documents/{document_id}/parse  提交文档解析任务（editor+）
- GET  /kbs/{kb_id}/tasks                          任务列表（任意成员）
- GET  /kbs/{kb_id}/tasks/{task_id}                任务详情
- POST /kbs/{kb_id}/tasks/{task_id}/retry          重试任务（editor+）

知识库隔离要点：
- 任务提交时 ``enqueue_job`` 将 ``kb_id`` 作为参数透传给 worker，
  worker 在执行时激活 RLS 并路由到 KB 专属资源（bucket/目录/向量库）。
- Task 表启用 RLS，查询自动按 ``kb_id`` 过滤。
- Task 记录创建时显式设置 ``kb_id``。

与旧 ``tasks.py``（全局，向后兼容）共存。
"""

import asyncio
import base64
import io
from datetime import datetime, timezone
from uuid import UUID

import httpx
from arq import create_pool
from arq.connections import RedisSettings
from fastapi import APIRouter, Depends, Request
from PIL import Image
from pydantic import BaseModel
from sqlalchemy import func, select
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
from app.core.database import get_db
from app.core.config import settings
from app.core.exceptions import BusinessException, ErrorCode
from app.core.logging import get_logger
from app.core.response import paginated, success
from app.core.snowflake import snowflake_generator
from app.models.document import Document
from app.models.knowledge_base import EDIT_ROLES
from app.models.task import Task

logger = get_logger(__name__)

# arq 连接池单例（懒加载，与 tasks.py 独立但指向同一 Redis）
_arq_pool = None


async def get_arq_pool():
    """获取 arq Redis 连接池单例（带超时保护）。
    复用 REDIS_URL 中的主机/端口/密码，固定使用 database=1 作为任务队列（与缓存 db=0 分离）。
    """
    global _arq_pool
    if _arq_pool is None:
        try:
            # 从 REDIS_URL 解析连接参数，任务队列固定使用 database=1
            from urllib.parse import urlparse
            parsed = urlparse(settings.REDIS_URL)
            host = parsed.hostname or "localhost"
            port = parsed.port or 6379
            password = parsed.password

            redis_settings_kwargs = {
                "host": host,
                "port": port,
                "database": 1,  # arq 任务队列固定使用 db=1
                "conn_timeout": 3,
            }
            if password:
                redis_settings_kwargs["password"] = password

            _arq_pool = await asyncio.wait_for(
                create_pool(RedisSettings(**redis_settings_kwargs)),
                timeout=5.0,
            )
        except (asyncio.TimeoutError, ConnectionError, OSError) as exc:
            logger.warning("arq Redis 连接失败", error=str(exc))
            raise BusinessException(
                code=ErrorCode.BUSINESS_TASK_FAILED,
                message="任务队列服务不可用，请稍后重试",
            )
    return _arq_pool


async def _sync_ocr_parse(document: Document, db: AsyncSession) -> dict:
    """同步 OCR 解析（直接调用 vLLM GLM-OCR 服务，不依赖 arq worker）。

    流程：下载文件 → PDF 转图片/直接读图片 → base64 编码 → 调用 9977 vLLM → 保存结果。
    """
    from app.services.infra.storage_service import storage_service

    try:
        document.status = "processing"
        await db.commit()

        # 从 MinIO 下载文件
        file_bytes = await storage_service.download(document.minio_object_name, kb_id=document.kb_id)
        ext = f".{document.file_type}" if document.file_type else ""
        images_base64: list[str] = []

        if ext.lower() == ".pdf":
            # PDF 转图片（使用 PyMuPDF）
            import fitz
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            for page_num in range(min(len(doc), 5)):  # 最多处理前5页
                page = doc[page_num]
                mat = fitz.Matrix(2, 2)  # 2x 缩放提高清晰度
                pix = page.get_pixmap(matrix=mat)
                img_bytes = pix.tobytes("png")
                b64 = base64.b64encode(img_bytes).decode()
                images_base64.append(b64)
            doc.close()
        elif ext.lower() in (".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".webp"):
            # 直接读取图片
            b64 = base64.b64encode(file_bytes).decode()
            images_base64.append(b64)
        else:
            raise BusinessException(
                code=ErrorCode.BUSINESS_TASK_FAILED,
                message=f"暂不支持的文件类型: {ext}",
            )

        # 调用 GLM-OCR vLLM 服务
        all_texts: list[str] = []
        layout_blocks: list[dict] = []

        async with httpx.AsyncClient(timeout=60.0) as client:
            for idx, img_b64 in enumerate(images_base64):
                try:
                    resp = await client.post(
                        "http://localhost:9977/v1/chat/completions",
                        json={
                            "model": "GLM-OCR",
                            "messages": [{
                                "role": "user",
                                "content": [
                                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
                                    {"type": "text", "text": "请识别图片中的所有文字内容，保持原始排版格式，直接输出文字，不要添加额外说明。"},
                                ],
                            }],
                            "max_tokens": 8192,
                            "temperature": 0.1,
                        },
                    )
                    if resp.status_code == 200:
                        result = resp.json()
                        text = result["choices"][0]["message"]["content"] if result.get("choices") else ""
                        all_texts.append(f"--- 第 {idx+1} 页 ---\n{text}" if len(images_base64) > 1 else text)
                    else:
                        logger.warning("OCR 请求失败", page=idx, status=resp.status_code)
                except Exception as page_err:
                    logger.warning("单页 OCR 失败", page=idx, error=str(page_err))

        full_text = "\n\n".join(all_texts)

        # 保存结果
        document.parsed_text = full_text
        document.layout_data = layout_blocks if layout_blocks else None
        document.status = "completed"
        document.parsed_at = datetime.now(timezone.utc)
        await db.commit()

        logger.info(
            "同步 OCR 解析完成",
            document_id=str(document.id),
            text_len=len(full_text),
            pages=len(images_base64),
        )
        return {"status": "completed", "text_length": len(full_text), "pages": len(images_base64)}

    except Exception as exc:
        document.status = "failed"
        document.error_message = str(exc)[:500]
        await db.commit()
        logger.error("同步 OCR 解析失败", document_id=str(document.id), error=str(exc))
        raise


class KbParseRequest(BaseModel):
    """KB 内文档解析任务提交请求。

    Attributes:
        schema_id: 结构化抽取模式标识，可选。
        term_base_id: 术语库标识，可选。
    """

    schema_id: str | None = None
    term_base_id: str | None = None


router = APIRouter(prefix="/kbs/{kb_id}", tags=["知识库-任务管理"])


@router.post("/documents/{document_id}/parse", status_code=201)
@limiter.limit(AI_LIMIT)
async def submit_parse_task(
    document_id: UUID,
    request: Request,
    payload: KbParseRequest,
    kb_ctx: KBContext = Depends(require_role(*EDIT_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """提交文档解析任务到 arq 队列（editor+）。

    处理流程：
        1. 校验文档存在且属于当前 KB（RLS 已过滤，额外防御性校验 kb_id）。
        2. 通过 arq ``enqueue_job`` 投递任务，透传 ``kb_id`` 供 worker 隔离。
        3. 创建 Task 记录（kb_id = 当前 KB）。
        4. 返回任务标识。

    Args:
        document_id: 待解析文档 ID（路径参数）。
        payload: 解析参数（schema_id / term_base_id）。
        kb_ctx: 知识库上下文（已校验 editor+ 角色 + 激活 RLS）。
        db: 异步数据库会话。

    Returns:
        dict: 包含 task_id 与 status 的响应。

    Raises:
        BusinessException: 文档不存在或不属于当前 KB。
    """
    # 校验文档存在且属于当前 KB
    document = await db.get(Document, document_id)
    if document is None or document.kb_id != kb_ctx.kb_id:
        raise BusinessException(
            code=ErrorCode.BUSINESS_DOCUMENT_NOT_FOUND,
            message=f"文档 {document_id} 不存在",
        )

    # 提交解析前对知识库抽取配置做完整校验（任一配置缺失/无效即报错，直到全部通过）
    from app.services.extraction_config.config_validator import ensure_extraction_config_valid

    await ensure_extraction_config_valid(db, kb_ctx.kb_id)

    # 重新解析时重置文档状态，清空之前的解析结果
    document.status = "pending"
    document.parsed_text = None
    document.structured_data = None
    document.layout_data = None
    document.markdown_content = None
    document.index_status = None
    document.graph_status = None
    document.extraction_status = None
    document.error_message = None
    await db.flush()

    # 投递 arq 任务，透传 kb_id
    pool = await get_arq_pool()
    job_id = snowflake_generator.generate_id_str()
    job = await pool.enqueue_job(
        "parse_document_task",
        str(document_id),
        payload.schema_id,
        payload.term_base_id,
        str(kb_ctx.kb_id),
        _job_id=job_id,
    )

    if job is None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_TASK_FAILED,
            message="任务提交失败，可能已有相同任务在执行中",
        )

    # 创建任务记录（kb_id 显式设置）
    task = Task(
        id=job.job_id,
        kb_id=kb_ctx.kb_id,
        document_id=document_id,
        task_type="parse_document",
        status="pending",
        progress=0,
    )
    db.add(task)
    await db.commit()

    logger.info(
        "KB 解析任务已提交",
        kb_id=str(kb_ctx.kb_id),
        task_id=job.job_id,
        document_id=str(document_id),
        user_id=str(kb_ctx.user.id),
    )
    return success(data={"task_id": task.id, "status": "pending"})


@router.get("/tasks")
@limiter.limit(DEFAULT_LIMIT)
async def list_tasks(
    request: Request,
    kb_ctx: KBContext = Depends(get_kb_context),
    pagination: dict = Depends(get_pagination_params),
    db: AsyncSession = Depends(get_db),
    status: str | None = None,
    task_type: str | None = None,
    document_id: UUID | None = None,
) -> dict:
    """分页查询 KB 内任务列表（任意成员）。

    RLS 已按 kb_id 过滤。支持按 status / task_type / document_id 过滤。

    Args:
        kb_ctx: 知识库上下文。
        pagination: 分页参数。
        db: 异步数据库会话。
        status: 可选状态过滤（pending/started/progress/success/failed）。
        task_type: 可选任务类型过滤（parse/extraction/build_graph/...）。
        document_id: 可选文档 ID 过滤。

    Returns:
        dict: 分页任务列表。
    """
    page: int = pagination["page"]
    page_size: int = pagination["page_size"]

    base_stmt = select(Task).where(Task.kb_id == kb_ctx.kb_id)
    count_stmt = select(func.count()).select_from(Task).where(Task.kb_id == kb_ctx.kb_id)
    if status:
        base_stmt = base_stmt.where(Task.status == status)
        count_stmt = count_stmt.where(Task.status == status)
    if task_type:
        base_stmt = base_stmt.where(Task.task_type == task_type)
        count_stmt = count_stmt.where(Task.task_type == task_type)
    if document_id is not None:
        base_stmt = base_stmt.where(Task.document_id == document_id)
        count_stmt = count_stmt.where(Task.document_id == document_id)

    total: int = (await db.execute(count_stmt)).scalar_one()
    offset = (page - 1) * page_size
    list_stmt = (
        base_stmt.order_by(Task.created_at.desc()).offset(offset).limit(page_size)
    )
    tasks = (await db.execute(list_stmt)).scalars().all()

    items = [
        {
            "id": t.id,
            "document_id": str(t.document_id) if t.document_id else None,
            "task_type": t.task_type,
            "status": t.status,
            "progress": t.progress,
            "error_message": t.error_message,
            "retry_count": t.retry_count,
            "parent_task_id": t.parent_task_id,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "started_at": t.started_at.isoformat() if t.started_at else None,
            "completed_at": t.completed_at.isoformat() if t.completed_at else None,
        }
        for t in tasks
    ]
    return paginated(items, total, page, page_size)


@router.get("/tasks/stats")
@limiter.limit(DEFAULT_LIMIT)
async def task_stats(
    request: Request,
    kb_ctx: KBContext = Depends(get_kb_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """任务统计（任意成员）。

    返回各状态任务数、各类型任务数、成功率、平均耗时。
    RLS 已按 kb_id 过滤。
    """
    # 按状态分组计数（显式按 kb_id 过滤，纵深防御不依赖 RLS）
    status_rows = await db.execute(
        select(Task.status, func.count(Task.id))
        .where(Task.kb_id == kb_ctx.kb_id)
        .group_by(Task.status)
    )
    by_status = {row[0]: row[1] for row in status_rows.all()}

    # 按类型分组计数
    type_rows = await db.execute(
        select(Task.task_type, func.count(Task.id))
        .where(Task.kb_id == kb_ctx.kb_id)
        .group_by(Task.task_type)
    )
    by_type = {row[0]: row[1] for row in type_rows.all()}

    total = sum(by_status.values())
    # 注意：局部变量不能命名为 success/failed，否则会遮蔽从 app.core.response 导入的
    # success() 函数，导致下方 return success(...) 报 'int' object is not callable
    success_count = by_status.get("success", 0)
    failed_count = by_status.get("failed", 0)
    success_rate = round(success_count / total * 100, 1) if total else 0.0

    return success(data={
        "total": total,
        "by_status": by_status,
        "by_type": by_type,
        "success_count": success_count,
        "failed_count": failed_count,
        "success_rate": success_rate,
    })


@router.post("/tasks/{task_id}/cancel")
@limiter.limit(UPLOAD_LIMIT)
async def cancel_task(
    task_id: str,
    request: Request,
    kb_ctx: KBContext = Depends(require_role(*EDIT_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """取消/暂停任务（editor+）。

    将处于 pending/queued/started/running/progress 状态的任务标记为 failed（取消）。
    尝试通过 arq abort 终止正在执行的任务，失败则仅标记数据库状态。
    """
    task = (
        await db.execute(
            select(Task).where(
                Task.id == task_id,
                Task.kb_id == kb_ctx.kb_id,
            )
        )
    ).scalar_one_or_none()
    if task is None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_TASK_NOT_FOUND,
            message=f"任务 {task_id} 不存在",
        )
    cancellable_statuses = ("pending", "queued", "started", "running", "progress")
    if task.status not in cancellable_statuses:
        raise BusinessException(
            code=ErrorCode.BUSINESS_TASK_FAILED,
            message=f"任务当前状态为 {task.status}，无法取消",
        )

    try:
        pool = await get_arq_pool()
        job = await pool.job(task_id)
        if job is not None:
            try:
                await job.abort(timeout=3)
            except Exception:
                try:
                    await pool.abort_job(task_id)
                except Exception:
                    pass
    except Exception as exc:
        logger.warning("arq 任务取消失败", task_id=task_id, error=str(exc))

    task.status = "failed"
    task.error_message = "用户手动取消"
    task.completed_at = datetime.now(timezone.utc)
    await db.commit()
    return success(message="任务已取消")


@router.get("/tasks/{task_id}")
async def get_task(
    task_id: str,
    kb_ctx: KBContext = Depends(get_kb_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """查询任务详情。

    显式按 kb_id 过滤，纵深防御不依赖 RLS（superuser 绕过 RLS）。
    跨 KB 任务查询返回 None。

    Raises:
        BusinessException: 任务不存在时抛出。
    """
    # 显式按 kb_id 过滤，纵深防御不依赖 RLS（superuser 绕过 RLS）
    task = (
        await db.execute(
            select(Task).where(
                Task.id == task_id,
                Task.kb_id == kb_ctx.kb_id,
            )
        )
    ).scalar_one_or_none()
    if task is None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_TASK_FAILED,
            message=f"任务 {task_id} 不存在",
        )
    return success(
        data={
            "id": task.id,
            "document_id": str(task.document_id) if task.document_id else None,
            "task_type": task.task_type,
            "status": task.status,
            "progress": task.progress,
            "result": task.result,
            "error_message": task.error_message,
            "retry_count": task.retry_count,
            "parent_task_id": task.parent_task_id,
            "created_at": task.created_at.isoformat() if task.created_at else None,
            "started_at": task.started_at.isoformat() if task.started_at else None,
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        }
    )


@router.post("/tasks/{task_id}/retry")
@limiter.limit(AI_LIMIT)
async def retry_task(
    task_id: str,
    request: Request,
    kb_ctx: KBContext = Depends(require_role(*EDIT_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """重试任务（editor+）。

    支持对 success 和 failed 状态的任务重新投递，根据 task_type 分发到对应 arq 任务函数。
    重置 Task 记录状态为 pending。
    """
    task = (
        await db.execute(
            select(Task).where(
                Task.id == task_id,
                Task.kb_id == kb_ctx.kb_id,
            )
        )
    ).scalar_one_or_none()
    if task is None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_TASK_FAILED,
            message=f"任务 {task_id} 不存在",
        )
    if task.status not in ("success", "failed", "completed"):
        raise BusinessException(
            code=ErrorCode.BUSINESS_TASK_FAILED,
            message=f"任务当前状态为 {task.status}，仅成功或失败任务可重试",
        )

    # 重试同样需通过抽取配置完整性校验
    from app.services.extraction_config.config_validator import ensure_extraction_config_valid

    await ensure_extraction_config_valid(db, kb_ctx.kb_id)

    task_type_to_func = {
        "parse_document": "parse_document_task",
        "parse": "parse_document_task",
        "extract_document": "extract_document_task",
        "extraction": "extract_document_task",
        "build_index_graph": "build_index_graph_task",
    }
    func_name = task_type_to_func.get(task.task_type, "parse_document_task")

    pool = await get_arq_pool()
    new_job_id = snowflake_generator.generate_id_str()

    if func_name == "parse_document_task":
        job = await pool.enqueue_job(
            func_name,
            str(task.document_id),
            None,
            None,
            str(kb_ctx.kb_id),
            _job_id=new_job_id,
        )
    else:
        job = await pool.enqueue_job(
            func_name,
            str(task.document_id),
            str(kb_ctx.kb_id),
            _job_id=new_job_id,
        )

    if job is None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_TASK_FAILED,
            message="重试任务提交失败",
        )

    new_task = Task(
        id=new_job_id,
        kb_id=kb_ctx.kb_id,
        document_id=task.document_id,
        task_type=task.task_type if task.task_type in ("parse_document", "extract_document", "build_index_graph") else "parse_document",
        status="pending",
        progress=0,
        parent_task_id=task_id,
        retry_count=(task.retry_count or 0) + 1,
    )
    db.add(new_task)
    await db.commit()

    logger.info(
        "KB 任务已重试",
        kb_id=str(kb_ctx.kb_id),
        old_task_id=task_id,
        new_task_id=new_job_id,
        task_type=new_task.task_type,
        document_id=str(task.document_id),
        user_id=str(kb_ctx.user.id),
    )
    return success(data={"task_id": new_job_id, "status": "pending"})


@router.delete("/tasks/{task_id}")
@limiter.limit(UPLOAD_LIMIT)
async def delete_task(
    task_id: str,
    request: Request,
    kb_ctx: KBContext = Depends(require_role(*EDIT_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """删除任务记录（editor+）。

    仅允许删除 success/completed/failed 状态的任务，运行中的任务需先取消。
    """
    task = (
        await db.execute(
            select(Task).where(
                Task.id == task_id,
                Task.kb_id == kb_ctx.kb_id,
            )
        )
    ).scalar_one_or_none()
    if task is None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_TASK_NOT_FOUND,
            message=f"任务 {task_id} 不存在",
        )
    deletable_statuses = ("success", "completed", "failed")
    if task.status not in deletable_statuses:
        raise BusinessException(
            code=ErrorCode.BUSINESS_TASK_FAILED,
            message=f"任务当前状态为 {task.status}，请先取消再删除",
        )

    await db.delete(task)
    await db.commit()

    logger.info(
        "KB 任务已删除",
        kb_id=str(kb_ctx.kb_id),
        task_id=task_id,
        user_id=str(kb_ctx.user.id),
    )
    return success(message="任务已删除")


# ============================================================
# 批量操作（阶段 2.3）
# ============================================================
class BatchParseRequest(BaseModel):
    """批量解析请求体。"""
    document_ids: list[UUID]
    schema_id: str | None = None
    term_base_id: str | None = None


class BatchRetryRequest(BaseModel):
    """批量重试请求体。"""
    task_ids: list[str]


@router.post("/batch-parse", status_code=201)
@limiter.limit(UPLOAD_LIMIT)
async def batch_parse_documents(
    request: Request,
    body: BatchParseRequest,
    kb_ctx: KBContext = Depends(require_role(*EDIT_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """批量提交文档解析任务（editor+）。

    循环校验文档归属并投递 arq 任务，单条失败不阻断其余。
    """
    # 提交前对知识库抽取配置做完整校验（任一配置缺失/无效即报错，直到全部通过）
    from app.services.extraction_config.config_validator import ensure_extraction_config_valid

    await ensure_extraction_config_valid(db, kb_ctx.kb_id)

    pool = await get_arq_pool()
    results: list[dict] = []
    for doc_id in body.document_ids:
        try:
            document = await db.get(Document, doc_id)
            if document is None or document.kb_id != kb_ctx.kb_id:
                results.append({"document_id": str(doc_id), "ok": False, "error": "文档不存在", "task_id": None})
                continue
            job_id = snowflake_generator.generate_id_str()
            job = await pool.enqueue_job(
                "parse_document_task",
                str(doc_id),
                body.schema_id,
                body.term_base_id,
                str(kb_ctx.kb_id),
                _job_id=job_id,
            )
            if job is None:
                results.append({"document_id": str(doc_id), "ok": False, "error": "任务提交失败", "task_id": None})
                continue
            task = Task(id=job.job_id, kb_id=kb_ctx.kb_id, document_id=doc_id, task_type="parse_document", status="pending", progress=0)
            db.add(task)
            results.append({"document_id": str(doc_id), "ok": True, "error": None, "task_id": job.job_id})
        except Exception as err:  # noqa: BLE001
            results.append({"document_id": str(doc_id), "ok": False, "error": str(err)[:200], "task_id": None})
    await db.commit()
    ok_count = sum(1 for r in results if r["ok"])
    return success(data={"results": results, "total": len(results), "success": ok_count, "failed": len(results) - ok_count})


@router.post("/batch-retry")
@limiter.limit(UPLOAD_LIMIT)
async def batch_retry_tasks(
    request: Request,
    body: BatchRetryRequest,
    kb_ctx: KBContext = Depends(require_role(*EDIT_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """批量重试任务（editor+），支持 success/failed/completed 状态。"""
    # 重试同样需通过抽取配置完整性校验
    from app.services.extraction_config.config_validator import ensure_extraction_config_valid

    await ensure_extraction_config_valid(db, kb_ctx.kb_id)

    pool = await get_arq_pool()
    task_type_to_func = {
        "parse_document": "parse_document_task",
        "parse": "parse_document_task",
        "extract_document": "extract_document_task",
        "extraction": "extract_document_task",
        "build_index_graph": "build_index_graph_task",
    }
    results: list[dict] = []
    for task_id in body.task_ids:
        try:
            task = (
                await db.execute(
                    select(Task).where(
                        Task.id == task_id,
                        Task.kb_id == kb_ctx.kb_id,
                    )
                )
            ).scalar_one_or_none()
            if task is None:
                results.append({"task_id": task_id, "ok": False, "error": "任务不存在"})
                continue
            if task.status not in ("success", "failed", "completed"):
                results.append({"task_id": task_id, "ok": False, "error": f"任务状态为 {task.status}，不可重试"})
                continue
            func_name = task_type_to_func.get(task.task_type, "parse_document_task")
            new_job_id = snowflake_generator.generate_id_str()
            if func_name == "parse_document_task":
                job = await pool.enqueue_job(
                    func_name,
                    str(task.document_id),
                    None,
                    None,
                    str(kb_ctx.kb_id),
                    _job_id=new_job_id,
                )
            else:
                job = await pool.enqueue_job(
                    func_name,
                    str(task.document_id),
                    str(kb_ctx.kb_id),
                    _job_id=new_job_id,
                )
            if job is None:
                results.append({"task_id": task_id, "ok": False, "error": "重试提交失败"})
                continue
            new_task_type = task.task_type if task.task_type in ("parse_document", "extract_document", "build_index_graph") else "parse_document"
            new_task = Task(
                id=new_job_id,
                kb_id=kb_ctx.kb_id,
                document_id=task.document_id,
                task_type=new_task_type,
                status="pending",
                progress=0,
                parent_task_id=task_id,
                retry_count=(task.retry_count or 0) + 1,
            )
            db.add(new_task)
            results.append({"task_id": task_id, "ok": True, "error": None, "new_task_id": new_job_id})
        except Exception as err:  # noqa: BLE001
            results.append({"task_id": task_id, "ok": False, "error": str(err)[:200]})
    await db.commit()
    ok_count = sum(1 for r in results if r["ok"])
    return success(data={"results": results, "total": len(results), "success": ok_count, "failed": len(results) - ok_count})
