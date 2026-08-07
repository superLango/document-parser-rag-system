"""通知服务（阶段 4 - 通知中心）。

提供通知的创建、查询、标记已读、清除等能力，按 ``user_id`` 隔离
（**不走 KB RLS**，通知表为用户级数据）。任务完成/失败时由 arq worker
回调 ``create_notification`` 自动写入通知，前端通过轮询 ``get_unread_count``
驱动顶栏铃铛未读数。

注意：本服务仅消费 ``Notification`` ORM（``app.models.notification``），
不涉及 services 下已优化模块（ocr/popo/vector/extraction），仅必要引用。
"""

import asyncio
import json
import uuid

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessException, ErrorCode
from app.core.logging import get_logger
from app.models.notification import Notification

logger = get_logger(__name__)


# ============================================================
# SSE 连接管理器（D1 通知中心 - SSE 实时推送）
# ============================================================
class _SSEConnectionManager:
    """SSE 连接管理器（进程内单例）。

    每个用户可有多个活跃连接（多标签页），用 ``asyncio.Queue`` 缓冲事件。
    ``create_notification`` 写库后调用 ``broadcast`` 向目标用户的所有连接
    推送实时事件，实现通知秒级到达（轮询作为兜底）。

    注意：仅适用于单进程部署；多进程/多实例需替换为 Redis Pub/Sub。
    """

    def __init__(self) -> None:
        self._connections: dict[uuid.UUID, set[asyncio.Queue]] = {}

    def register(self, user_id: uuid.UUID) -> asyncio.Queue:
        """注册一个 SSE 连接，返回该连接的事件队列。"""
        queue: asyncio.Queue = asyncio.Queue(maxsize=64)
        if user_id not in self._connections:
            self._connections[user_id] = set()
        self._connections[user_id].add(queue)
        logger.debug("SSE 连接已注册", user_id=str(user_id), total=len(self._connections[user_id]))
        return queue

    def unregister(self, user_id: uuid.UUID, queue: asyncio.Queue) -> None:
        """注销一个 SSE 连接。"""
        conns = self._connections.get(user_id)
        if conns is not None:
            conns.discard(queue)
            if not conns:
                del self._connections[user_id]
            logger.debug("SSE 连接已注销", user_id=str(user_id))

    async def broadcast(self, user_id: uuid.UUID, event_data: dict) -> None:
        """向目标用户的所有连接推送事件（队列满则丢弃，避免阻塞）。"""
        conns = self._connections.get(user_id)
        if not conns:
            return
        for queue in list(conns):  # copy 避免迭代中修改
            try:
                queue.put_nowait(event_data)
            except asyncio.QueueFull:
                logger.warning("SSE 队列已满，丢弃事件", user_id=str(user_id))

    @property
    def total_connections(self) -> int:
        """当前活跃连接总数（监控用）。"""
        return sum(len(conns) for conns in self._connections.values())


# 进程内单例
sse_manager = _SSEConnectionManager()


async def create_notification(
    db: AsyncSession,
    user_id: uuid.UUID,
    type: str,
    title: str,
    content: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    kb_id: uuid.UUID | None = None,
) -> Notification:
    """创建一条通知并落库。

    由 arq worker 在任务终态、系统事件等场景调用。调用方负责 ``db.commit()``，
    本函数仅 ``add`` + ``flush`` 以获取 ``id`` 与 ``created_at``。

    Args:
        db: 异步数据库会话。
        user_id: 接收通知的用户 ID。
        type: 通知类型（task_done / task_failed / system / audit_alert / kb_member）。
        title: 通知标题（<=255 字符）。
        content: 通知正文，可空。
        resource_type: 关联资源类型（如 "task" / "document" / "kb"），供前端跳转。
        resource_id: 关联资源 ID 字符串。
        kb_id: 关联知识库 ID，KB 内通知填写便于跳转；跨 KB 通知可空。

    Returns:
        Notification: 已落库的通知对象（含 id 与 created_at）。
    """
    notification = Notification(
        user_id=user_id,
        type=type,
        title=title[:255] if title else title,
        content=content,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id is not None else None,
        kb_id=kb_id,
    )
    db.add(notification)
    await db.flush()
    logger.info(
        "通知已创建",
        notification_id=str(notification.id),
        user_id=str(user_id),
        type=type,
        kb_id=str(kb_id) if kb_id else None,
    )

    # SSE 实时推送：向目标用户的所有活跃连接推送通知事件（轮询作为兜底）
    event_data = {
        "id": str(notification.id),
        "type": type,
        "title": notification.title,
        "content": content,
        "resource_type": resource_type,
        "resource_id": str(resource_id) if resource_id is not None else None,
        "kb_id": str(kb_id) if kb_id else None,
        "created_at": notification.created_at.isoformat() if notification.created_at else None,
    }
    await sse_manager.broadcast(user_id, event_data)

    return notification


async def list_notifications(
    db: AsyncSession,
    user_id: uuid.UUID,
    unread_only: bool = False,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[Notification], int]:
    """分页查询当前用户的通知列表。

    按 ``created_at`` 倒序返回。``unread_only=True`` 时仅返回未读通知。

    Args:
        db: 异步数据库会话。
        user_id: 当前用户 ID（隔离依据）。
        unread_only: 是否仅查询未读。
        page: 页码，从 1 开始。
        page_size: 每页条数。

    Returns:
        tuple[list[Notification], int]: (当前页通知列表, 符合条件总数)。
    """
    base = select(Notification).where(Notification.user_id == user_id)
    count_stmt = select(func.count()).select_from(Notification).where(
        Notification.user_id == user_id
    )
    if unread_only:
        base = base.where(Notification.read.is_(False))
        count_stmt = count_stmt.where(Notification.read.is_(False))

    total = (await db.execute(count_stmt)).scalar_one()
    rows = await db.execute(
        base.order_by(Notification.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(rows.scalars().all()), int(total)


async def get_unread_count(db: AsyncSession, user_id: uuid.UUID) -> int:
    """获取当前用户的未读通知数（顶栏铃铛 Badge 依据）。

    Args:
        db: 异步数据库会话。
        user_id: 当前用户 ID。

    Returns:
        int: 未读通知数。
    """
    stmt = (
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == user_id, Notification.read.is_(False))
    )
    return int((await db.execute(stmt)).scalar_one())


async def mark_read(
    db: AsyncSession, notification_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    """标记单条通知为已读（校验 user_id 归属）。

    通过 ``user_id`` 与 ``id`` 双重过滤确保用户只能操作自己的通知，
    避免越权。若通知不存在或不属于该用户，抛 ``BUSINESS_NOT_FOUND``。

    Args:
        db: 异步数据库会话。
        notification_id: 通知 ID。
        user_id: 当前用户 ID。

    Raises:
        BusinessException: 通知不存在或不属于当前用户（30017）。
    """
    result = await db.execute(
        update(Notification)
        .where(Notification.id == notification_id, Notification.user_id == user_id)
        .values(read=True)
    )
    if result.rowcount == 0:
        raise BusinessException(
            code=ErrorCode.BUSINESS_NOT_FOUND,
            message="通知不存在",
        )


async def mark_all_read(db: AsyncSession, user_id: uuid.UUID) -> int:
    """将当前用户所有未读通知标记为已读。

    Args:
        db: 异步数据库会话。
        user_id: 当前用户 ID。

    Returns:
        int: 实际更新条数。
    """
    result = await db.execute(
        update(Notification)
        .where(Notification.user_id == user_id, Notification.read.is_(False))
        .values(read=True)
    )
    return int(result.rowcount)


async def delete_notification(
    db: AsyncSession, notification_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    """删除单条通知（校验 user_id 归属）。

    Args:
        db: 异步数据库会话。
        notification_id: 通知 ID。
        user_id: 当前用户 ID。

    Raises:
        BusinessException: 通知不存在或不属于当前用户（30017）。
    """
    result = await db.execute(
        delete(Notification).where(
            Notification.id == notification_id, Notification.user_id == user_id
        )
    )
    if result.rowcount == 0:
        raise BusinessException(
            code=ErrorCode.BUSINESS_NOT_FOUND,
            message="通知不存在",
        )


async def clear_all_read(db: AsyncSession, user_id: uuid.UUID) -> int:
    """清除当前用户所有已读通知。

    Args:
        db: 异步数据库会话。
        user_id: 当前用户 ID。

    Returns:
        int: 实际删除条数。
    """
    result = await db.execute(
        delete(Notification).where(
            Notification.user_id == user_id, Notification.read.is_(True)
        )
    )
    return int(result.rowcount)
