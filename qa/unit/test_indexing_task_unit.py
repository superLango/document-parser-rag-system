"""L1 单元测试：M28 索引任务触发（防重/前置校验/类型过滤）。"""

import uuid

import pytest
from sqlalchemy import select

from app.core.exceptions import BusinessException
from app.models.document import DocumentTask, TaskOutbox
from app.services import document_service
from qa.fixtures.indexing_helpers import (
    create_document_row,
    create_kb_via_api,
)


async def test_enqueue_requires_completed_and_layout(client, super_token, db_session):
    """L1M28-01：未解析完成（无 layout_path）文档不可索引。"""
    kb = await create_kb_via_api(client, super_token, "S4前置校验")
    doc_id = await create_document_row(db_session, uuid.UUID(kb["id"]))
    with pytest.raises(BusinessException):
        await document_service.enqueue_index_task(
            db_session, uuid.UUID(kb["id"]), doc_id
        )


async def test_enqueue_creates_task_and_outbox(client, super_token, db_session):
    """L1M28-02：合法文档创建 document_index 任务 + outbox。"""
    kb = await create_kb_via_api(client, super_token, "S4创建任务")
    kb_id = uuid.UUID(kb["id"])
    doc_id = await create_document_row(
        db_session, kb_id, layout_path="kb-x/ocr/t/layout.json"
    )
    task = await document_service.enqueue_index_task(db_session, kb_id, doc_id)
    assert task is not None
    assert task.type == "document_index"
    assert task.task_id.startswith("idx-")
    outbox = (
        await db_session.execute(
            select(TaskOutbox).where(TaskOutbox.task_id == task.task_id)
        )
    ).scalar_one_or_none()
    assert outbox is not None
    assert outbox.type == "document_index"
    assert outbox.status == "pending"


async def test_enqueue_idempotent_duplicate(client, super_token, db_session):
    """L1M28-03：同一文档重复触发返回 None（防重）。"""
    kb = await create_kb_via_api(client, super_token, "S4防重")
    kb_id = uuid.UUID(kb["id"])
    doc_id = await create_document_row(
        db_session, kb_id, layout_path="kb-x/ocr/t/layout.json"
    )
    first = await document_service.enqueue_index_task(db_session, kb_id, doc_id)
    second = await document_service.enqueue_index_task(db_session, kb_id, doc_id)
    assert first is not None
    assert second is None


async def test_list_tasks_type_filter(client, super_token, db_session):
    """L1M28-04：list_tasks 按 type 过滤（索引任务与解析任务分离）。"""
    from sqlalchemy import insert

    from app.models.document import Document, DocumentTask

    kb = await create_kb_via_api(client, super_token, "S4类型过滤")
    kb_id = uuid.UUID(kb["id"])
    doc_id = await create_document_row(db_session, kb_id)
    import uuid as _uuid

    await db_session.execute(
        insert(DocumentTask).values(
            kb_id=kb_id, document_id=doc_id, task_id=f"idx-{_uuid.uuid4()}",
            type="document_index", status="queued", checkpoint={},
        )
    )
    await db_session.execute(
        insert(DocumentTask).values(
            kb_id=kb_id, document_id=doc_id, task_id=f"parse-{_uuid.uuid4()}",
            type="document_parse", status="queued", checkpoint={},
        )
    )
    await db_session.commit()
    index_rows, index_total, _ = await document_service.list_tasks(
        db_session, kb_id, 1, 10, task_type="document_index"
    )
    parse_rows, parse_total, _ = await document_service.list_tasks(
        db_session, kb_id, 1, 10, task_type="document_parse"
    )
    assert index_total == 1 and [t.type for t in index_rows] == ["document_index"]
    assert parse_total == 1 and [t.type for t in parse_rows] == ["document_parse"]
