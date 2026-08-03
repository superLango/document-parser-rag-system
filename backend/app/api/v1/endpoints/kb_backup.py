"""知识库数据备份恢复端点模块（阶段 3 - 数据备份恢复）。

提供 KB 数据的备份创建、列表查询、下载、恢复与删除接口，所有端点强制
``Depends(get_kb_context)``，通过 PostgreSQL RLS 自动按 ``kb_id`` 过滤
``kb_backups`` 表。

- POST   /kbs/{kb_id}/backups               创建备份（admin+）
- GET    /kbs/{kb_id}/backups               备份列表（任意成员）
- GET    /kbs/{kb_id}/backups/{backup_id}   备份详情（任意成员）
- GET    /kbs/{kb_id}/backups/{backup_id}/download  下载备份 ZIP（admin+）
- POST   /kbs/{kb_id}/backups/restore       上传 ZIP 恢复（admin+）
- DELETE /kbs/{kb_id}/backups/{backup_id}   删除备份（admin+）

备份文件存储在 KB 专属 MinIO bucket 的 ``backups/`` 前缀下。
"""

import io
from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    DEFAULT_LIMIT,
    KBContext,
    UPLOAD_LIMIT,
    get_db,
    get_kb_context,
    get_pagination_params,
    limiter,
    require_role,
)
from app.core.exceptions import BusinessException, ErrorCode
from app.core.logging import get_logger
from app.core.response import paginated, success
from app.models.backup import KbBackup
from app.services.backup_service import (
    create_backup,
    delete_backup,
    download_backup,
    restore_backup,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/kbs/{kb_id}/backups", tags=["知识库-备份恢复"])


def _backup_to_dict(b: KbBackup) -> dict:
    """序列化备份记录为字典。"""
    return {
        "id": str(b.id),
        "kb_id": str(b.kb_id),
        "user_id": str(b.user_id),
        "file_name": b.file_name.split("/")[-1],  # 仅返回文件名，不含前缀
        "file_size": b.file_size,
        "status": b.status,
        "item_counts": b.item_counts or {},
        "created_at": b.created_at.isoformat() if b.created_at else None,
    }


@router.post("", status_code=201)
@limiter.limit(UPLOAD_LIMIT)
async def create_kb_backup(
    request: Request,
    kb_ctx: KBContext = Depends(require_role("owner", "admin")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """创建 KB 数据备份（admin+）。

    打包 KB 配置 + 文档元数据 + 抽取结果 + 术语 + Schema + 领域配置为 ZIP，
    上传到 KB 专属 bucket，并创建备份记录。
    """
    backup = await create_backup(db, kb_ctx.kb_id, kb_ctx.user.id)
    await db.commit()
    return success(data=_backup_to_dict(backup))


@router.get("")
@limiter.limit(DEFAULT_LIMIT)
async def list_kb_backups(
    request: Request,
    kb_ctx: KBContext = Depends(get_kb_context),
    pagination: dict = Depends(get_pagination_params),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """分页查询 KB 备份列表（任意成员）。RLS 已按 kb_id 过滤。"""
    page = pagination["page"]
    page_size = pagination["page_size"]

    count_stmt = select(KbBackup).where(KbBackup.kb_id == kb_ctx.kb_id)
    total = len((await db.execute(count_stmt)).scalars().all())

    offset = (page - 1) * page_size
    list_stmt = (
        select(KbBackup)
        .where(KbBackup.kb_id == kb_ctx.kb_id)
        .order_by(KbBackup.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    backups = (await db.execute(list_stmt)).scalars().all()
    items = [_backup_to_dict(b) for b in backups]
    return paginated(items, total, page, page_size)


@router.get("/{backup_id}")
@limiter.limit(DEFAULT_LIMIT)
async def get_kb_backup(
    backup_id: UUID,
    request: Request,
    kb_ctx: KBContext = Depends(get_kb_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取备份详情（任意成员）。"""
    backup = await db.get(KbBackup, backup_id)
    if backup is None or backup.kb_id != kb_ctx.kb_id:
        raise BusinessException(
            code=ErrorCode.BUSINESS_NOT_FOUND,
            message=f"备份 {backup_id} 不存在",
        )
    return success(data=_backup_to_dict(backup))


@router.get("/{backup_id}/download")
@limiter.limit(UPLOAD_LIMIT)
async def download_kb_backup(
    backup_id: UUID,
    request: Request,
    kb_ctx: KBContext = Depends(require_role("owner", "admin")),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """下载备份 ZIP 文件（admin+）。"""
    content, download_name = await download_backup(db, kb_ctx.kb_id, backup_id)
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{download_name}"',
        },
    )


@router.post("/restore")
@limiter.limit(UPLOAD_LIMIT)
async def restore_kb_backup(
    request: Request,
    file: UploadFile = File(..., description="备份 ZIP 文件"),
    kb_ctx: KBContext = Depends(require_role("owner", "admin")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """从上传的 ZIP 文件恢复数据（admin+）。

    恢复策略：按唯一键去重，已存在的跳过；配置与领域配置直接覆盖。
    """
    zip_bytes = await file.read()
    if not zip_bytes:
        raise BusinessException(
            code=ErrorCode.BUSINESS_FILE_TOO_LARGE,
            message="备份文件为空",
        )
    stats = await restore_backup(db, kb_ctx.kb_id, zip_bytes)
    await db.commit()
    return success(data=stats, message="恢复完成")


@router.delete("/{backup_id}")
@limiter.limit(UPLOAD_LIMIT)
async def delete_kb_backup(
    backup_id: UUID,
    request: Request,
    kb_ctx: KBContext = Depends(require_role("owner", "admin")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """删除备份（admin+，含 MinIO 对象与 DB 记录）。"""
    await delete_backup(db, kb_ctx.kb_id, backup_id)
    await db.commit()
    return success(message="备份已删除")
