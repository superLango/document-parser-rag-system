"""L5 安全渗透：M24 索引存储底座 RLS（KB 隔离第一边界）。"""

import uuid

import pytest
from sqlalchemy import insert, select, text as sa_text
from sqlalchemy.exc import DBAPIError

from app.models.document import Document
from app.models.indexing import DocumentChunk
from app.models.user import User
from qa.fixtures.indexing_helpers import (
    create_document_row,
    create_kb_via_api,
    ensure_test_role,
    grant_table_permissions,
    set_rls_context,
    upsert_kb_member,
)

RLS_ROLE = "hansondoc_index_rls"
RLS_TABLES = ["document_chunks", "text_chunks", "kb_bm25_stats"]


async def _seed_chunk(db, kb_id: uuid.UUID, doc_id: uuid.UUID, content: str) -> None:
    await db.execute(sa_text("SELECT set_config('app.is_superuser', 'true', true)"))
    await db.execute(
        insert(DocumentChunk).values(
            kb_id=kb_id,
            document_id=doc_id,
            chunk_id=f"{doc_id}_p0_0",
            chunk_index=0,
            content=content,
            tokens=1,
        )
    )
    await db.commit()


async def _setup(db_session, client, super_token, name: str):
    kb = await create_kb_via_api(client, super_token, name)
    kb_id = uuid.UUID(kb["id"])
    doc_id = await create_document_row(db_session, kb_id)
    await _seed_chunk(db_session, kb_id, doc_id, "保密内容-INDEX")
    admin_id = (
        await db_session.execute(select(User.id).where(User.username == "admin"))
    ).scalar_one()
    await ensure_test_role(db_session, RLS_ROLE)
    await grant_table_permissions(db_session, RLS_ROLE, RLS_TABLES)
    return kb_id, doc_id, admin_id


async def test_non_superuser_no_context_rejected(db_session, client, super_token):
    """L5M24-01：非超管角色、无任何上下文时 SELECT/INSERT 均被 RLS 拒绝。"""
    kb_id, doc_id, admin_id = await _setup(db_session, client, super_token, "S1无上下文")

    await db_session.execute(sa_text("SET ROLE " + RLS_ROLE))
    await set_rls_context(db_session, None, None)
    rows = (
        await db_session.execute(sa_text("select * from document_chunks"))
    ).fetchall()
    assert rows == []
    with pytest.raises(DBAPIError):
        await db_session.execute(
            insert(DocumentChunk).values(
                kb_id=kb_id, document_id=doc_id, chunk_id="x", chunk_index=0,
                content="x", tokens=1,
            )
        )
    await db_session.rollback()
    await db_session.execute(sa_text("RESET ROLE"))
    await db_session.execute(sa_text("SELECT set_config('app.is_superuser', 'true', true)"))


async def test_non_member_with_kb_context_rejected(db_session, client, super_token):
    """L5M24-02：设置 current_kb 但用户非成员 → SELECT 拒绝。"""
    kb_id, doc_id, admin_id = await _setup(db_session, client, super_token, "S1非成员")

    await db_session.execute(sa_text("SET ROLE " + RLS_ROLE))
    await set_rls_context(db_session, kb_id, uuid.uuid4())
    rows = (
        await db_session.execute(sa_text("select * from document_chunks"))
    ).fetchall()
    assert rows == []
    await db_session.rollback()
    await db_session.execute(sa_text("RESET ROLE"))
    await db_session.execute(sa_text("SELECT set_config('app.is_superuser', 'true', true)"))


async def test_viewer_can_select_cannot_insert(db_session, client, super_token):
    """L5M24-03：viewer 成员可 SELECT、不可 INSERT/UPDATE/DELETE。"""
    kb_id, doc_id, admin_id = await _setup(db_session, client, super_token, "S1viewer")
    await upsert_kb_member(db_session, kb_id, admin_id, "viewer")

    await db_session.execute(sa_text("SET ROLE " + RLS_ROLE))
    await set_rls_context(db_session, kb_id, admin_id)
    rows = (
        await db_session.execute(sa_text("select chunk_id from document_chunks"))
    ).scalars().all()
    assert rows == [f"{doc_id}_p0_0"]

    with pytest.raises(DBAPIError):
        await db_session.execute(
            insert(DocumentChunk).values(
                kb_id=kb_id, document_id=doc_id, chunk_id="v_write", chunk_index=1,
                content="x", tokens=1,
            )
        )
    await db_session.rollback()
    await db_session.execute(sa_text("RESET ROLE"))
    await db_session.execute(sa_text("SELECT set_config('app.is_superuser', 'true', true)"))
    # 视图成员写入的块不可见（INSERT 失败无副作用）
    cnt = (
        await db_session.execute(
            sa_text("select count(*) from document_chunks where chunk_id='v_write'")
        )
    ).scalar()
    assert cnt == 0
    await db_session.execute(sa_text("SELECT set_config('app.is_superuser', '', true)"))
    await db_session.execute(sa_text("SET ROLE " + RLS_ROLE))
    await set_rls_context(db_session, kb_id, admin_id)
    await db_session.execute(sa_text("RESET ROLE"))
    await db_session.execute(sa_text("SELECT set_config('app.is_superuser', 'true', true)"))


async def test_editor_can_insert_and_update(db_session, client, super_token):
    """L5M24-04：editor 成员可 INSERT，并可通过 UPDATE 更新块内容。"""
    kb_id, doc_id, admin_id = await _setup(db_session, client, super_token, "S1editor")
    await upsert_kb_member(db_session, kb_id, admin_id, "editor")

    await db_session.execute(sa_text("SET ROLE " + RLS_ROLE))
    await set_rls_context(db_session, kb_id, admin_id)
    await db_session.execute(
        insert(DocumentChunk).values(
            kb_id=kb_id, document_id=doc_id, chunk_id=f"{doc_id}_p0_1",
            chunk_index=1, content="editor 可写", tokens=1,
        )
    )
    await db_session.execute(
        sa_text(
            "update document_chunks set content='已更新' where chunk_id=:cid"
        ).bindparams(cid=f"{doc_id}_p0_0")
    )
    await db_session.rollback()
    await db_session.execute(sa_text("RESET ROLE"))
    await db_session.execute(sa_text("SELECT set_config('app.is_superuser', 'true', true)"))


async def test_cross_kb_isolation(db_session, client, super_token):
    """L5M24-05：A KB 成员在 A 上下文看不到 B KB 的块，且无法向 B KB 写入。"""
    kb_a, doc_a, admin_id = await _setup(db_session, client, super_token, "S1隔离A")
    kb_b, doc_b, _ = await _setup(db_session, client, super_token, "S1隔离B")
    await upsert_kb_member(db_session, kb_a, admin_id, "viewer")
    # admin 在 B KB 中不是成员（API 创建的 KB owner 是 admin，需移除 B 的成员记录）
    await db_session.execute(
        sa_text(
            "delete from kb_members where kb_id=:kb and user_id=:uid"
        ).bindparams(kb=kb_b, uid=admin_id)
    )
    await db_session.commit()

    await db_session.execute(sa_text("SET ROLE " + RLS_ROLE))
    await set_rls_context(db_session, kb_a, admin_id)
    rows = (
        await db_session.execute(sa_text("select chunk_id from document_chunks"))
    ).scalars().all()
    assert rows == [f"{doc_a}_p0_0"]
    with pytest.raises(DBAPIError):
        await db_session.execute(
            insert(DocumentChunk).values(
                kb_id=kb_b, document_id=doc_b, chunk_id="cross", chunk_index=0,
                content="越权", tokens=1,
            )
        )
    await db_session.rollback()
    await db_session.execute(sa_text("RESET ROLE"))
    await db_session.execute(sa_text("SELECT set_config('app.is_superuser', 'true', true)"))
