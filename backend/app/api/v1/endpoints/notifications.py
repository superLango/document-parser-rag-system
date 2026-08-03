"""通知中心端点（阶段 4 - 通知中心）。

按 ``user_id`` 隔离（**不走 KB RLS**），所有端点用 ``get_current_active_user``
而非 ``get_kb_context``。前端顶栏铃铛通过 ``/unread-count`` 轮询驱动未读数。

端点清单（前缀 ``/notifications``）：

- GET    /notifications              分页查询当前用户通知（支持 unread_only）
- GET    /notifications/unread-count 未读数
- POST   /notifications/{id}/read   标记单条已读
- POST   /notifications/read-all    全部已读
- DELETE /notifications/{id}        删除单条
- DELETE /notifications/read        清除所有已读
"""

import asyncio
import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    DEFAULT_LIMIT,
    get_current_active_user,
    get_db,
    get_pagination_params,
    limiter,
)
from app.core.database import get_db
from app.core.exceptions import PermissionException, ErrorCode
from app.core.response import paginated, success
from app.models.notification import Notification
from app.models.user import User
from app.services import notification_service
from app.services.notification_service import sse_manager

router = APIRouter(prefix="/notifications", tags=["通知中心"])


def _to_dict(n: Notification) -> dict:
    """将 Notification ORM 对象序列化为响应字典。"""
    return {
        "id": str(n.id),
        "type": n.type,
        "title": n.title,
        "content": n.content,
        "read": n.read,
        "resource_type": n.resource_type,
        "resource_id": n.resource_id,
        "kb_id": str(n.kb_id) if n.kb_id else None,
        "created_at": n.created_at.isoformat() if n.created_at else None,
    }


@router.get("")
@limiter.limit(DEFAULT_LIMIT)
async def list_notifications(
    request: Request,
    unread_only: bool = Query(False, description="仅返回未读通知"),
    current_user: User = Depends(get_current_active_user),
    pagination: dict = Depends(get_pagination_params),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """分页查询当前用户的通知列表。

    按 ``created_at`` 倒序返回，支持 ``unread_only`` 过滤。
    """
    items, total = await notification_service.list_notifications(
        db,
        current_user.id,
        unread_only=unread_only,
        page=pagination["page"],
        page_size=pagination["page_size"],
    )
    return paginated(
        [_to_dict(n) for n in items],
        total,
        pagination["page"],
        pagination["page_size"],
    )


@router.get("/unread-count")
@limiter.limit(DEFAULT_LIMIT)
async def unread_count(
    request: Request,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取当前用户的未读通知数（顶栏铃铛 Badge 依据）。"""
    count = await notification_service.get_unread_count(db, current_user.id)
    return success(data={"count": count})


@router.get("/subscribe")
async def subscribe(
    current_user: User = Depends(get_current_active_user),
) -> StreamingResponse:
    """SSE 实时推送订阅（D1 通知中心 - SSE 推送）。

    建立长连接，服务端通过 ``text/event-stream`` 推送通知事件。
    前端用 ``EventSource`` 连接，收到事件后更新铃铛未读数与通知列表。
    每 30 秒发送心跳（ping）防止代理超时断开。轮询作为兜底机制。

    注意：本端点不加 ``@limiter.limit``（长连接不适合请求级限流）。
    多进程部署需替换为 Redis Pub/Sub。
    """
    user_id = current_user.id
    queue = sse_manager.register(user_id)

    async def event_generator():
        try:
            # 首次推送连接确认
            yield f"event: connected\ndata: {json.dumps({'user_id': str(user_id)})}\n\n"
            while True:
                try:
                    event_data = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield f"data: {json.dumps(event_data, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    # 心跳：防止代理超时
                    yield ": ping\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            sse_manager.unregister(user_id, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # nginx 关闭缓冲
            "Content-Encoding": "identity",  # 跳过 GZip 压缩，保持实时性
        },
    )


@router.post("/{notification_id}/read")
@limiter.limit(DEFAULT_LIMIT)
async def mark_read(
    notification_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """标记单条通知为已读（校验归属，不存在抛 30017）。"""
    await notification_service.mark_read(db, notification_id, current_user.id)
    await db.commit()
    return success(message="已标记已读")


@router.post("/read-all")
@limiter.limit(DEFAULT_LIMIT)
async def mark_all_read(
    request: Request,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """将当前用户所有未读通知标记为已读。"""
    count = await notification_service.mark_all_read(db, current_user.id)
    await db.commit()
    return success(data={"updated": count})


@router.delete("/{notification_id}")
@limiter.limit(DEFAULT_LIMIT)
async def delete_notification(
    notification_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """删除单条通知（校验归属，不存在抛 30017）。"""
    await notification_service.delete_notification(db, notification_id, current_user.id)
    await db.commit()
    return success(message="已删除")


@router.delete("/read")
@limiter.limit(DEFAULT_LIMIT)
async def clear_read(
    request: Request,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """清除当前用户所有已读通知。"""
    count = await notification_service.clear_all_read(db, current_user.id)
    await db.commit()
    return success(data={"deleted": count})


# ============================================================
# P2-5 管理员公告功能（超管向全体活跃用户发送系统通知）
# ============================================================
class BroadcastRequest(BaseModel):
    """公告请求体。"""

    title: str
    content: str | None = None


@router.post("/broadcast")
@limiter.limit(DEFAULT_LIMIT)
async def broadcast(
    body: BroadcastRequest,
    request: Request,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """管理员公告（超管专属，向所有活跃用户发送系统通知）。

    遍历所有 ``is_active=True`` 且未软删除的用户，为每人创建一条
    ``type=system`` 的通知。SSE 连接的用户会实时收到推送。
    """
    if not current_user.is_superuser:
        raise PermissionException(
            code=ErrorCode.AUTH_PERMISSION_DENIED,
            message="仅超管可发送系统公告",
        )

    result = await db.execute(
        select(User.id).where(
            User.is_active.is_(True),
            User.deleted_at.is_(None),
        )
    )
    user_ids = [row[0] for row in result.all()]

    for uid in user_ids:
        await notification_service.create_notification(
            db,
            user_id=uid,
            type="system",
            title=body.title[:255],
            content=body.content,
            resource_type="broadcast",
        )
    await db.commit()

    return success(data={"sent_count": len(user_ids)})
