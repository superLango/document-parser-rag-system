"""L4 边界：E1 历史保留上限与删除。"""

import uuid

from app.models.document import Document
from app.services.extraction import result_store
from sqlalchemy import text as sa_text

from qa.fixtures.indexing_helpers import create_document_row, create_kb_via_api


async def test_history_limit_50(client, super_token, db_session):
    """L4E1-01：连续保存 55 次，历史归档仅保留 50 条。"""
    kb = await create_kb_via_api(client, super_token, "E1上限")
    kb_id = uuid.UUID(kb["id"])
    doc_id = await create_document_row(db_session, kb_id, layout_path="x")
    await db_session.execute(sa_text("SELECT set_config('app.is_superuser', 'true', true)"))
    for i in range(55):
        await result_store.save_result(
            db_session, kb_id, doc_id, schema_name=f"S{i}", categories=[], summary={},
            status="completed",
        )
    assert await result_store.history_count(db_session, kb_id, doc_id) == 50
    latest = await result_store.get_latest(db_session, kb_id, doc_id)
    assert latest is not None and latest.version == 55


async def test_delete_resets_document_status(client, super_token, db_session):
    """L4E1-02：删除后最新/历史清空且文档状态重置。"""
    kb = await create_kb_via_api(client, super_token, "E1删除")
    kb_id = uuid.UUID(kb["id"])
    doc_id = await create_document_row(db_session, kb_id, layout_path="x")
    await db_session.execute(sa_text("SELECT set_config('app.is_superuser', 'true', true)"))
    await result_store.save_result(db_session, kb_id, doc_id, schema_name="S", categories=[], summary={}, status="completed")
    await result_store.delete_result_and_history(db_session, kb_id, doc_id)
    doc = await db_session.get(Document, doc_id)
    assert doc.extraction_status is None
