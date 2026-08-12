"""L5 安全：M33-S1 术语集 RLS（独立 session 模式，贴近并发隔离）。"""

import uuid

import pytest
from sqlalchemy import insert, select, text as sa_text
from sqlalchemy.exc import DBAPIError

from app.core.database import AsyncSessionLocal
from app.models.glossary import TermBase
from app.models.user import User
from qa.fixtures.indexing_helpers import (
    create_kb_via_api,
    ensure_test_role,
    grant_table_permissions,
    set_rls_context,
    upsert_kb_member,
)

RLS_ROLE = "hansondoc_glossary_rls"
TABLES = ["term_bases", "terms"]


async def _setup(client, super_token, name):
    """在独立会话中建 KB、术语集与测试角色，返回 (db, kb_id, admin_id)。"""
    db = AsyncSessionLocal()
    try:
        kb = await create_kb_via_api(client, super_token, name)
        kb_id = uuid.UUID(kb["id"])
        await db.execute(sa_text("SELECT set_config('app.is_superuser', 'true', true)"))
        db.add(TermBase(kb_id=kb_id, name="保密术语"))
        await db.commit()
        admin = (
            await db.execute(select(User.id).where(User.username == "admin"))
        ).scalar_one()
        await ensure_test_role(db, RLS_ROLE)
        await grant_table_permissions(db, RLS_ROLE, TABLES)
        return db, kb_id, admin
    except Exception:
        await db.close()
        raise


async def test_non_superuser_no_context_rejected(client, super_token):
    """L5M33-S1-01：无上下文非超管角色 SELECT/INSERT 被 RLS 拒绝。"""
    db, kb_id, admin = await _setup(client, super_token, "S8无上下文")
    try:
        await db.execute(sa_text("SET ROLE " + RLS_ROLE))
        await set_rls_context(db, None, None)
        rows = (await db.execute(sa_text("select * from term_bases"))).fetchall()
        assert rows == []
        with pytest.raises(DBAPIError):
            await db.execute(insert(TermBase).values(kb_id=kb_id, name="x"))
        await db.rollback()
        await db.execute(sa_text("RESET ROLE"))
    finally:
        await db.close()


async def test_viewer_read_only(client, super_token):
    """L5M33-S1-02：viewer 可读不可写。"""
    db, kb_id, admin = await _setup(client, super_token, "S8viewer")
    try:
        await upsert_kb_member(db, kb_id, admin, "viewer")
        await db.execute(sa_text("SET ROLE " + RLS_ROLE))
        await set_rls_context(db, kb_id, admin)
        rows = (await db.execute(sa_text("select * from term_bases"))).fetchall()
        assert len(rows) == 1
        with pytest.raises(DBAPIError):
            await db.execute(insert(TermBase).values(kb_id=kb_id, name="x"))
        await db.rollback()
        await db.execute(sa_text("RESET ROLE"))
    finally:
        await db.close()


async def test_editor_can_write(client, super_token):
    """L5M33-S1-03：editor 可写入。"""
    db, kb_id, admin = await _setup(client, super_token, "S8editor")
    try:
        await upsert_kb_member(db, kb_id, admin, "editor")
        await db.execute(sa_text("SET ROLE " + RLS_ROLE))
        await set_rls_context(db, kb_id, admin)
        await db.execute(insert(TermBase).values(kb_id=kb_id, name="editor写入"))
        await db.rollback()
        await db.execute(sa_text("RESET ROLE"))
    finally:
        await db.close()


async def test_cross_kb_isolation(client, super_token):
    """L5M33-S1-04：A KB 上下文看不到 B KB 术语集。"""
    db_a, kb_a, admin = await _setup(client, super_token, "S8隔离A")
    db_b, kb_b, _ = await _setup(client, super_token, "S8隔离B")
    try:
        await upsert_kb_member(db_a, kb_a, admin, "viewer")
        await db_a.execute(
            sa_text("delete from kb_members where kb_id=:kb and user_id=:u").bindparams(
                kb=kb_b, u=admin
            )
        )
        await db_a.commit()
        await db_a.execute(sa_text("SET ROLE " + RLS_ROLE))
        await set_rls_context(db_a, kb_a, admin)
        rows = (await db_a.execute(sa_text("select name from term_bases"))).fetchall()
        assert [r[0] for r in rows] == ["保密术语"]
        await db_a.rollback()
        await db_a.execute(sa_text("RESET ROLE"))
    finally:
        await db_a.close()
        await db_b.close()
