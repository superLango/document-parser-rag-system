"""问答历史服务（阶段 2 - 对话历史）。

封装 QaSession / QaMessage 的持久化逻辑，供 kb_qa 与 kb_qa_history 端点复用。
所有写入均在已激活 RLS 的会话内执行；同时显式按 kb_id 过滤，纵深防御
不依赖 RLS（PostgreSQL superuser 绕过 RLS）。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessException, ErrorCode
from app.core.logging import get_logger
from app.models.qa_history import QaMessage, QaSession

logger = get_logger(__name__)

# 标题最大长度（截取自首条用户消息）
_TITLE_MAX_LEN = 40


async def create_session(
    db: AsyncSession,
    kb_id: uuid.UUID,
    user_id: uuid.UUID,
    title: str = "未命名会话",
    doc_ids: list[str] | None = None,
) -> QaSession:
    """创建问答会话。

    Args:
        db: 已激活 RLS 的异步会话。
        kb_id: 知识库 ID（RLS 已约束）。
        user_id: 创建者用户 ID。
        title: 会话标题，默认 "未命名会话"。
        doc_ids: 关联文档 ID 列表（可选）。

    Returns:
        QaSession: 已创建的会话对象。
    """
    session = QaSession(
        kb_id=kb_id,
        user_id=user_id,
        title=title or "未命名会话",
        doc_ids=doc_ids,
        message_count=0,
    )
    db.add(session)
    await db.flush()
    logger.info("创建问答会话", kb_id=str(kb_id), session_id=str(session.id), user_id=str(user_id))
    return session


async def get_session(
    db: AsyncSession,
    session_id: uuid.UUID,
    kb_id: uuid.UUID | None = None,
) -> QaSession:
    """获取会话。

    Args:
        db: 异步数据库会话。
        session_id: 会话 ID。
        kb_id: 知识库 ID。提供时显式按 kb_id 过滤（纵深防御不依赖 RLS，
            因 PostgreSQL superuser 绕过 RLS）；为 None 时依赖 RLS（向后兼容）。

    Raises:
        BusinessException: 会话不存在时抛出。
    """
    # 显式按 kb_id 过滤，纵深防御不依赖 RLS（superuser 绕过 RLS）
    if kb_id is not None:
        session = (
            await db.execute(
                select(QaSession).where(
                    QaSession.id == session_id,
                    QaSession.kb_id == kb_id,
                )
            )
        ).scalar_one_or_none()
    else:
        session = await db.get(QaSession, session_id)
    if session is None:
        raise BusinessException(
            code=ErrorCode.BUSINESS_NOT_FOUND,
            message=f"问答会话 {session_id} 不存在",
        )
    return session


async def list_sessions(
    db: AsyncSession,
    kb_id: uuid.UUID,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[QaSession], int]:
    """分页查询会话列表（显式按 kb_id 过滤，纵深防御不依赖 RLS）。

    Returns:
        (sessions, total)
    """
    # 显式按 kb_id 过滤，纵深防御不依赖 RLS（superuser 绕过 RLS）
    count_stmt = (
        select(func.count())
        .select_from(QaSession)
        .where(QaSession.kb_id == kb_id)
    )
    total: int = (await db.execute(count_stmt)).scalar_one()

    offset = (page - 1) * page_size
    list_stmt = (
        select(QaSession)
        .where(QaSession.kb_id == kb_id)
        .order_by(QaSession.last_message_at.desc().nullslast(), QaSession.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    sessions = (await db.execute(list_stmt)).scalars().all()
    return list(sessions), total


async def rename_session(
    db: AsyncSession,
    session_id: uuid.UUID,
    title: str,
    kb_id: uuid.UUID | None = None,
) -> QaSession:
    """重命名会话标题。"""
    session = await get_session(db, session_id, kb_id=kb_id)
    session.title = title[:255] if title else session.title
    await db.flush()
    return session


async def delete_session(
    db: AsyncSession,
    session_id: uuid.UUID,
    kb_id: uuid.UUID | None = None,
) -> None:
    """删除会话（级联删除消息，ondelete=CASCADE）。"""
    session = await get_session(db, session_id, kb_id=kb_id)
    await db.delete(session)
    await db.flush()
    logger.info("删除问答会话", session_id=str(session_id))


async def list_messages(
    db: AsyncSession,
    session_id: uuid.UUID,
    kb_id: uuid.UUID | None = None,
) -> list[QaMessage]:
    """查询会话内全部消息（按时间升序）。

    会话存在性由 ``get_session`` 校验；提供 ``kb_id`` 时显式按 kb_id 过滤，
    纵深防御不依赖 RLS。
    """
    await get_session(db, session_id, kb_id=kb_id)  # 校验会话存在且属当前 KB
    stmt = (
        select(QaMessage)
        .where(QaMessage.session_id == session_id)
        .order_by(QaMessage.created_at.asc())
    )
    return list((await db.execute(stmt)).scalars().all())


async def add_message(
    db: AsyncSession,
    session_id: uuid.UUID,
    role: str,
    content: str,
    citations: list[dict] | None = None,
    tokens: int | None = None,
    *,
    auto_title: bool = True,
    kb_id: uuid.UUID | None = None,
) -> QaMessage:
    """追加消息并更新会话统计。

    当 ``auto_title=True`` 且 role=="user" 且会话标题仍为默认值时，
    用首条用户消息前 40 字符回填标题。

    Args:
        db: 已激活 RLS 的异步会话。
        session_id: 会话 ID。
        role: user / assistant / system。
        content: 消息内容。
        citations: 引用来源（assistant 消息）。
        tokens: token 计数（可选）。
        auto_title: 是否自动回填标题。
        kb_id: 知识库 ID。提供时显式按 kb_id 过滤会话（纵深防御不依赖 RLS）。
    """
    session = await get_session(db, session_id, kb_id=kb_id)
    msg = QaMessage(
        session_id=session_id,
        role=role,
        content=content,
        citations=citations if citations else None,
        tokens=tokens,
    )
    db.add(msg)

    # 更新会话统计
    session.message_count = (session.message_count or 0) + 1
    session.last_message_at = datetime.now(timezone.utc)
    if auto_title and role == "user" and session.title in ("", "未命名会话"):
        session.title = content[:_TITLE_MAX_LEN] or "未命名会话"

    await db.flush()
    return msg


async def ensure_session(
    db: AsyncSession,
    kb_id: uuid.UUID,
    user_id: uuid.UUID,
    session_id: str | None,
) -> QaSession:
    """获取或创建会话。

    - session_id 为空：创建新会话，标题暂为 "未命名会话"（首条用户消息后回填）。
    - session_id 非空：校验存在性并显式按 kb_id 过滤（纵深防御不依赖 RLS）后返回。

    用于 kb_qa.query/stream 在问答前确保会话就绪。
    """
    if not session_id:
        return await create_session(db, kb_id, user_id)
    return await get_session(db, uuid.UUID(session_id), kb_id=kb_id)
