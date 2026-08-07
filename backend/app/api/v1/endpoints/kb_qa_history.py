"""知识库问答会话历史端点模块（阶段 2 - 对话历史）。

提供 KB 内问答会话与消息的管理接口，所有端点强制 ``Depends(get_kb_context)``，
通过 PostgreSQL RLS 自动按 ``kb_id`` 过滤 QaSession，qa_messages 通过
session_id 间接隔离。

- GET    /kbs/{kb_id}/qa/sessions                      分页查询会话列表（viewer+）
- POST   /kbs/{kb_id}/qa/sessions                      创建会话（viewer+）
- GET    /kbs/{kb_id}/qa/sessions/{session_id}         会话详情（viewer+）
- PATCH  /kbs/{kb_id}/qa/sessions/{session_id}         重命名会话（viewer+）
- DELETE /kbs/{kb_id}/qa/sessions/{session_id}         删除会话（viewer+，级联消息）
- GET    /kbs/{kb_id}/qa/sessions/{session_id}/messages 会话内消息列表（viewer+）
- GET    /kbs/{kb_id}/qa/sessions/{session_id}/export  导出会话为 JSON/Markdown（viewer+）

会话归属：仅创建者与同 KB 成员可访问；删除仅限创建者或 owner/admin。
"""

import json
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    DEFAULT_LIMIT,
    KBContext,
    get_db,
    get_kb_context,
    get_pagination_params,
    limiter,
)
from app.core.exceptions import BusinessException, ErrorCode
from app.core.logging import get_logger
from app.core.response import paginated, success
from app.services.infra.qa_history_service import (
    create_session,
    delete_session,
    get_session,
    list_messages,
    list_sessions,
    rename_session,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/kbs/{kb_id}/qa/sessions", tags=["知识库-问答历史"])


class SessionCreateRequest(BaseModel):
    """创建会话请求。"""

    title: str = Field(default="未命名会话", max_length=255)
    doc_ids: list[str] | None = Field(default=None)


class SessionUpdateRequest(BaseModel):
    """更新会话请求（重命名）。"""

    title: str = Field(..., min_length=1, max_length=255)


def _session_to_dict(session) -> dict:
    """序列化会话对象为字典。"""
    return {
        "id": str(session.id),
        "kb_id": str(session.kb_id),
        "user_id": str(session.user_id),
        "title": session.title,
        "doc_ids": session.doc_ids or [],
        "message_count": session.message_count,
        "last_message_at": session.last_message_at.isoformat() if session.last_message_at else None,
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "updated_at": session.updated_at.isoformat() if session.updated_at else None,
    }


def _message_to_dict(msg) -> dict:
    """序列化消息对象为字典。"""
    return {
        "id": str(msg.id),
        "session_id": str(msg.session_id),
        "role": msg.role,
        "content": msg.content,
        "citations": msg.citations,
        "tokens": msg.tokens,
        "created_at": msg.created_at.isoformat() if msg.created_at else None,
    }


@router.get("")
@limiter.limit(DEFAULT_LIMIT)
async def list_kb_qa_sessions(
    request: Request,
    kb_ctx: KBContext = Depends(get_kb_context),
    pagination: dict = Depends(get_pagination_params),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """分页查询 KB 内问答会话列表（viewer+）。

    RLS 已按 kb_id 过滤，仅返回当前 KB 的会话，按最近活跃时间倒序。
    """
    sessions, total = await list_sessions(
        db, kb_ctx.kb_id, page=pagination["page"], page_size=pagination["page_size"]
    )
    items = [_session_to_dict(s) for s in sessions]
    return paginated(items, total, pagination["page"], pagination["page_size"])


@router.post("", status_code=201)
@limiter.limit(DEFAULT_LIMIT)
async def create_kb_qa_session(
    request: Request,
    body: SessionCreateRequest,
    kb_ctx: KBContext = Depends(get_kb_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """创建问答会话（viewer+）。

    任意成员均可创建会话；会话归属创建者，但同 KB 成员可读取（RLS 隔离）。
    """
    session = await create_session(
        db,
        kb_id=kb_ctx.kb_id,
        user_id=kb_ctx.user.id,
        title=body.title,
        doc_ids=body.doc_ids,
    )
    await db.commit()
    return success(data=_session_to_dict(session))


@router.get("/{session_id}")
@limiter.limit(DEFAULT_LIMIT)
async def get_kb_qa_session(
    session_id: UUID,
    request: Request,
    kb_ctx: KBContext = Depends(get_kb_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取会话详情（viewer+）。显式按 kb_id 过滤，纵深防御不依赖 RLS。"""
    # 显式按 kb_id 过滤，纵深防御不依赖 RLS（superuser 绕过 RLS）
    session = await get_session(db, session_id, kb_id=kb_ctx.kb_id)
    return success(data=_session_to_dict(session))


@router.patch("/{session_id}")
@limiter.limit(DEFAULT_LIMIT)
async def update_kb_qa_session(
    session_id: UUID,
    request: Request,
    body: SessionUpdateRequest,
    kb_ctx: KBContext = Depends(get_kb_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """重命名会话（viewer+）。

    任意成员可重命名（会话属 KB 共享资源，权限由 KB 成员资格保证）。
    显式按 kb_id 过滤，纵深防御不依赖 RLS。
    """
    # 显式按 kb_id 过滤，纵深防御不依赖 RLS（superuser 绕过 RLS）
    session = await rename_session(db, session_id, body.title, kb_id=kb_ctx.kb_id)
    await db.commit()
    return success(data=_session_to_dict(session))


@router.delete("/{session_id}")
@limiter.limit(DEFAULT_LIMIT)
async def delete_kb_qa_session(
    session_id: UUID,
    request: Request,
    kb_ctx: KBContext = Depends(get_kb_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """删除会话（viewer+，级联删除消息）。

    删除仅限会话创建者或 owner/admin，避免误删他人会话。
    显式按 kb_id 过滤，纵深防御不依赖 RLS。
    """
    # 显式按 kb_id 过滤，纵深防御不依赖 RLS（superuser 绕过 RLS）
    session = await get_session(db, session_id, kb_id=kb_ctx.kb_id)
    # 权限：创建者本人 或 owner/admin
    is_owner = session.user_id == kb_ctx.user.id
    if not (is_owner or kb_ctx.role in ("owner", "admin")):
        raise BusinessException(
            code=ErrorCode.AUTH_PERMISSION_DENIED,
            message="仅会话创建者或管理员可删除会话",
        )
    await delete_session(db, session_id, kb_id=kb_ctx.kb_id)
    await db.commit()
    return success(data={"deleted": True})


@router.get("/{session_id}/messages")
@limiter.limit(DEFAULT_LIMIT)
async def list_kb_qa_messages(
    session_id: UUID,
    request: Request,
    kb_ctx: KBContext = Depends(get_kb_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """查询会话内全部消息（viewer+，按时间升序）。"""
    # 显式按 kb_id 过滤，纵深防御不依赖 RLS（superuser 绕过 RLS）
    messages = await list_messages(db, session_id, kb_id=kb_ctx.kb_id)
    items = [_message_to_dict(m) for m in messages]
    return success(data={"items": items, "total": len(items)})


@router.get("/{session_id}/export")
@limiter.limit(DEFAULT_LIMIT)
async def export_kb_qa_session(
    session_id: UUID,
    request: Request,
    kb_ctx: KBContext = Depends(get_kb_context),
    db: AsyncSession = Depends(get_db),
    format: str = Query("json", description="导出格式：json/markdown"),
) -> StreamingResponse:
    """导出会话为 JSON 或 Markdown（viewer+）。"""
    import io

    # 显式按 kb_id 过滤，纵深防御不依赖 RLS（superuser 绕过 RLS）
    session = await get_session(db, session_id, kb_id=kb_ctx.kb_id)
    messages = await list_messages(db, session_id, kb_id=kb_ctx.kb_id)

    if format == "markdown":
        lines = [f"# {session.title}", ""]
        lines.append(f"- 会话 ID：{session.id}")
        lines.append(f"- 知识库：{kb_ctx.kb.name}")
        lines.append(f"- 创建时间：{session.created_at.isoformat() if session.created_at else '-'}")
        lines.append(f"- 消息数：{len(messages)}")
        lines.append("")
        lines.append("---")
        lines.append("")
        for msg in messages:
            role_label = "🧑 用户" if msg.role == "user" else "🤖 助手" if msg.role == "assistant" else "系统"
            ts = msg.created_at.isoformat() if msg.created_at else ""
            lines.append(f"## {role_label} · {ts}")
            lines.append("")
            lines.append(msg.content)
            lines.append("")
            if msg.citations:
                lines.append("**引用来源：**")
                for i, c in enumerate(msg.citations, 1):
                    if isinstance(c, dict):
                        lines.append(f"{i}. `{c.get('document_id', '-')}` (score: {c.get('score', '-')})")
                lines.append("")
            lines.append("---")
            lines.append("")
        content = "\n".join(lines)
        return StreamingResponse(
            io.BytesIO(content.encode("utf-8")),
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="qa_session_{session_id}.md"',
            },
        )

    # 默认 JSON
    payload = {
        "session": _session_to_dict(session),
        "messages": [_message_to_dict(m) for m in messages],
    }
    content = json.dumps(payload, ensure_ascii=False, indent=2)
    return StreamingResponse(
        io.BytesIO(content.encode("utf-8")),
        media_type="application/json; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="qa_session_{session_id}.json"',
        },
    )
