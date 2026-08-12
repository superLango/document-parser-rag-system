"""L5 安全：M34-S1 抽取配置 RLS（独立 session 模式）。"""

import uuid

import pytest
from qa.fixtures.indexing_helpers import (
    create_kb_via_api,
    ensure_test_role,
    grant_table_permissions,
    set_rls_context,
    upsert_kb_member,
)
from sqlalchemy import insert, select
from sqlalchemy import text as sa_text
from sqlalchemy.exc import DBAPIError

from app.core.database import AsyncSessionLocal
from app.models.extraction import SchemaTemplate
from app.models.user import User

RLS_ROLE = "hansondoc_extraction_rls"
TABLES = [
    "schema_templates", "schema_categories", "schema_fields",
    "prompt_templates", "prompt_content", "rule_groups",
    "rule_group_items", "kb_scripts",
]


async def _setup(client, super_token, name):
    """在独立会话中建 KB、模板与测试角色，返回 (db, kb_id, admin_id)。"""
    db = AsyncSessionLocal()
    try:
        kb = await create_kb_via_api(client, super_token, name)
        kb_id = uuid.UUID(kb["id"])
        await db.execute(sa_text("SELECT set_config('app.is_superuser', 'true', true)"))
        db.add(SchemaTemplate(kb_id=kb_id, name="保密模板"))
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
    """L5M34-S1-01：无上下文非超管角色 SELECT/INSERT 被 RLS 拒绝。"""
    db, kb_id, _admin = await _setup(client, super_token, "S9无上下文")
    try:
        await db.execute(sa_text("SET ROLE " + RLS_ROLE))
        await set_rls_context(db, None, None)
        rows = (await db.execute(sa_text("select * from schema_templates"))).fetchall()
        assert rows == []
        with pytest.raises(DBAPIError):
            await db.execute(insert(SchemaTemplate).values(kb_id=kb_id, name="x"))
        await db.rollback()
        await db.execute(sa_text("RESET ROLE"))
    finally:
        await db.close()


async def test_viewer_read_only(client, super_token):
    """L5M34-S1-02：viewer 可读不可写。"""
    db, kb_id, admin = await _setup(client, super_token, "S9viewer")
    try:
        await upsert_kb_member(db, kb_id, admin, "viewer")
        await db.execute(sa_text("SET ROLE " + RLS_ROLE))
        await set_rls_context(db, kb_id, admin)
        rows = (await db.execute(sa_text("select * from schema_templates"))).fetchall()
        assert len(rows) == 1
        with pytest.raises(DBAPIError):
            await db.execute(insert(SchemaTemplate).values(kb_id=kb_id, name="x"))
        await db.rollback()
        await db.execute(sa_text("RESET ROLE"))
    finally:
        await db.close()


async def test_editor_can_write(client, super_token):
    """L5M34-S1-03：editor 可写入。"""
    db, kb_id, admin = await _setup(client, super_token, "S9editor")
    try:
        await upsert_kb_member(db, kb_id, admin, "editor")
        await db.execute(sa_text("SET ROLE " + RLS_ROLE))
        await set_rls_context(db, kb_id, admin)
        await db.execute(insert(SchemaTemplate).values(kb_id=kb_id, name="editor写入"))
        await db.rollback()
        await db.execute(sa_text("RESET ROLE"))
    finally:
        await db.close()


async def test_cross_kb_isolation(client, super_token):
    """L5M34-S1-04：A KB 上下文看不到 B KB 模板。"""
    db_a, kb_a, admin = await _setup(client, super_token, "S9隔离A")
    db_b, kb_b, _ = await _setup(client, super_token, "S9隔离B")
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
        rows = (await db_a.execute(sa_text("select name from schema_templates"))).fetchall()
        assert [r[0] for r in rows] == ["保密模板"]
        await db_a.rollback()
        await db_a.execute(sa_text("RESET ROLE"))
    finally:
        await db_a.close()
        await db_b.close()
