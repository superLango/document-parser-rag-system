"""L5 安全：E1 抽取结果 RLS 策略与跨 KB 隔离。"""

import uuid

from app.services.extraction import result_store
from sqlalchemy import text as sa_text

from qa.fixtures.indexing_helpers import (
    create_document_row,
    create_kb_via_api,
    ensure_test_role,
    grant_table_permissions,
    set_rls_context,
)

RLS_ROLE = "e1_rls_sec"


async def test_rls_policies_exist(db_session):
    """L5E1-01：extraction_results / extraction_history 共 8 条 RLS 策略。"""
    rows = (
        await db_session.execute(
            sa_text(
                "select tablename, policyname from pg_policies "
                "where tablename in ('extraction_results','extraction_history')"
            )
        )
    ).all()
    assert len(rows) == 8


async def test_cross_kb_result_isolation(client, super_token, db_session):
    """L5E1-02：非成员角色在 B KB 上下文看不到 A KB 的结果（RLS 强制）。"""
    kb_a = await create_kb_via_api(client, super_token, "E1隔离A")
    kb_b = await create_kb_via_api(client, super_token, "E1隔离B")
    kb_a_id = uuid.UUID(kb_a["id"])
    kb_b_id = uuid.UUID(kb_b["id"])
    doc_a = await create_document_row(db_session, kb_a_id, layout_path="x")
    await db_session.execute(sa_text("SELECT set_config('app.is_superuser', 'true', true)"))
    await result_store.save_result(db_session, kb_a_id, doc_a, schema_name="S", categories=[], summary={}, status="completed")

    await ensure_test_role(db_session, RLS_ROLE)
    await grant_table_permissions(
        db_session, RLS_ROLE, ["extraction_results", "extraction_history"]
    )
    try:
        await db_session.execute(sa_text(f"SET ROLE {RLS_ROLE}"))
        # B KB 上下文 + 非成员用户：RLS 应过滤
        await set_rls_context(db_session, kb_b_id, uuid.uuid4())
        assert await result_store.get_latest(db_session, kb_b_id, doc_a) is None
        # A KB 上下文 + 非成员用户：同样不可见
        await set_rls_context(db_session, kb_a_id, uuid.uuid4())
        assert await result_store.get_latest(db_session, kb_a_id, doc_a) is None
    finally:
        await db_session.execute(sa_text("RESET ROLE"))
