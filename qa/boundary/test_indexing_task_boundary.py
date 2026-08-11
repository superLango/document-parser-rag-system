"""L4 边界异常 + 并发：M28 索引任务状态机。"""

import asyncio
import uuid

import pytest
from sqlalchemy import select

from app.models.document import DocumentTask
from app.models.indexing import DocumentChunk
from app.services import document_service
from qa.fixtures.indexing_helpers import create_document_row, create_kb_via_api


async def test_manual_index_requires_parsed(client, super_token, db_session):
    """L4M28-01：未解析文档手动触发索引返回 400。"""
    kb = await create_kb_via_api(client, super_token, "S4未解析")
    doc_id = await create_document_row(db_session, uuid.UUID(kb["id"]))
    resp = await client.post(
        f"/api/v1/kb/{kb['id']}/documents/{doc_id}/index",
        headers={"Authorization": f"Bearer {super_token}"},
    )
    assert resp.status_code == 400
    assert "尚未解析完成" in resp.json()["message"]


async def test_index_failure_isolated_from_parse(client, super_token, db_session):
    """L4M28-02：索引失败仅置 index_failed，解析状态保持 completed。"""
    kb = await create_kb_via_api(client, super_token, "S4失败隔离")
    kb_id = uuid.UUID(kb["id"])
    # 指向不存在的产物 → run_index_task 失败
    doc_id = await create_document_row(
        db_session, kb_id, layout_path="kb-x/ocr/missing/layout.json"
    )
    task = await document_service.enqueue_index_task(db_session, kb_id, doc_id)
    assert task is not None
    from app.services import document_service as ds

    with pytest.raises(Exception):
        await ds.run_index_task(db_session, doc_id, kb_id)
    doc = await ds.get_document(db_session, kb_id, doc_id)
    assert doc.status == "completed"  # 解析状态不受影响
    assert doc.index_status == "index_failed"
    assert doc.index_error is not None


async def test_empty_chunk_failure(client, super_token, db_session, tmp_path):
    """L4M28-03：分块为空（layout 无内容）→ 索引失败有明确错误。"""
    import json

    from app.services import document_service as ds, storage

    kb = await create_kb_via_api(client, super_token, "S4空块")
    kb_id = uuid.UUID(kb["id"])
    empty_layout = {
        "schema_version": "1.2",
        "page_count": 1,
        "pages": [],
        "rebuild": {"enabled": True, "document_tree": {"type": "root", "children": []}},
    }
    key = f"kb-{kb_id.hex}/ocr/empty/layout.json"
    storage.put_object(key, json.dumps(empty_layout).encode("utf-8"), "application/json")
    doc_id = await create_document_row(db_session, kb_id, layout_path=key)
    task = await ds.enqueue_index_task(db_session, kb_id, doc_id)
    assert task is not None
    with pytest.raises(Exception, match="分块结果为空"):
        await ds.run_index_task(db_session, doc_id, kb_id)
    doc = await ds.get_document(db_session, kb_id, doc_id)
    assert doc.index_status == "index_failed"


async def test_run_without_task_raises(client, super_token, db_session):
    """L4M28-05：直接执行索引但无索引任务时给出明确错误。"""
    from app.services import document_service as ds

    kb = await create_kb_via_api(client, super_token, "S4无任务")
    kb_id = uuid.UUID(kb["id"])
    doc_id = await create_document_row(
        db_session, kb_id, layout_path="kb-x/ocr/t/layout.json"
    )
    with pytest.raises(RuntimeError, match="索引任务不存在"):
        await ds.run_index_task(db_session, doc_id, kb_id)


async def test_run_without_layout_path_raises(client, super_token, db_session):
    """L4M28-06：任务存在但文档缺 layout 产物时报错（防御分支）。"""
    import uuid as _uuid

    from sqlalchemy import insert

    from app.models.document import DocumentTask
    from app.services import document_service as ds

    kb = await create_kb_via_api(client, super_token, "S4缺产物")
    kb_id = uuid.UUID(kb["id"])
    doc_id = await create_document_row(db_session, kb_id)  # layout_path=None
    # enqueue 前置校验会拦截无产物文档，直接插入任务验证 run 的防御分支
    await db_session.execute(
        insert(DocumentTask).values(
            kb_id=kb_id, document_id=doc_id, task_id=f"idx-{_uuid.uuid4()}",
            type="document_index", status="queued", checkpoint={},
        )
    )
    await db_session.commit()
    with pytest.raises(RuntimeError, match="缺少 layout.json"):
        await ds.run_index_task(db_session, doc_id, kb_id)


async def test_concurrent_trigger_single_task(client, super_token, db_session):
    """L4M28-04（并发）：并发触发同一文档索引，仅一个任务创建成功。"""
    from sqlalchemy import func

    kb = await create_kb_via_api(client, super_token, "S4并发触发")
    kb_id = uuid.UUID(kb["id"])
    doc_id = await create_document_row(
        db_session, kb_id, layout_path="kb-x/ocr/t/layout.json"
    )

    async def _trigger():
        return await document_service.enqueue_index_task(db_session, kb_id, doc_id)

    # 注意：咨询锁为事务级，同一 session 并发会串行；用独立 session 验证
    from app.core.database import AsyncSessionLocal

    async def _trigger_new():
        async with AsyncSessionLocal() as db:
            from sqlalchemy import text as sa_text

            await db.execute(sa_text("SELECT set_config('app.is_superuser', 'true', true)"))
            return await document_service.enqueue_index_task(db, kb_id, doc_id)

    results = await asyncio.gather(*[_trigger_new() for _ in range(4)])
    created = [r for r in results if r is not None]
    assert len(created) == 1
    total = (
        await db_session.execute(
            select(func.count())
            .select_from(DocumentTask)
            .where(
                DocumentTask.document_id == doc_id,
                DocumentTask.type == "document_index",
            )
        )
    ).scalar()
    assert total == 1
