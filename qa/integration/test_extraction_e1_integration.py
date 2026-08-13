"""L2/L3 集成：E1 抽取任务状态机 + 结果存储。"""

import uuid

import pytest
from app.core.exceptions import BusinessException
from app.models.document import Document, DocumentTask, TaskDeadLetter, TaskOutbox
from app.models.extraction import ExtractionResult
from app.services.extraction import extraction_task_service, result_store
from app.tasks.sync_executor import execute_sync_task
from sqlalchemy import select
from sqlalchemy import text as sa_text

from qa.fixtures.indexing_helpers import create_document_row, create_kb_via_api


async def _kb_and_doc(client, super_token, db_session, name, indexed=True):
    kb = await create_kb_via_api(client, super_token, name)
    kb_id = uuid.UUID(kb["id"])
    doc_id = await create_document_row(db_session, kb_id, layout_path="x" if indexed else None)
    if indexed:
        doc = await db_session.get(Document, doc_id)
        doc.index_status = "completed"
        await db_session.commit()
    return kb_id, doc_id


async def test_start_creates_task_and_outbox(client, super_token, db_session):
    """L2E1-01：启动抽取创建 DocumentTask + Outbox。"""
    kb_id, doc_id = await _kb_and_doc(client, super_token, db_session, "E1启动")
    started = await extraction_task_service.start_document_extraction(db_session, kb_id, doc_id)
    task = (
        await db_session.execute(
            select(DocumentTask).where(DocumentTask.task_id == started["task_id"])
        )
    ).scalar_one()
    outbox = (
        await db_session.execute(
            select(TaskOutbox).where(TaskOutbox.task_id == started["task_id"])
        )
    ).scalar_one()
    assert task.type == "document_extraction" and task.status == "queued"
    assert outbox.type == "document_extraction" and outbox.status == "pending"


async def test_prereq_reject(client, super_token, db_session):
    """L2E1-02：未完成解析/索引的文档拒绝启动。"""
    kb_id, doc_id = await _kb_and_doc(client, super_token, db_session, "E1前置", indexed=False)
    with pytest.raises(BusinessException) as exc:
        await extraction_task_service.start_document_extraction(db_session, kb_id, doc_id)
    assert "未完成解析与索引" in str(exc.value)


async def test_duplicate_start_conflict(client, super_token, db_session):
    """L2E1-03：进行中任务重复启动 409。"""
    kb_id, doc_id = await _kb_and_doc(client, super_token, db_session, "E1重复")
    await extraction_task_service.start_document_extraction(db_session, kb_id, doc_id)
    with pytest.raises(BusinessException) as exc:
        await extraction_task_service.start_document_extraction(db_session, kb_id, doc_id)
    assert exc.value.http_status == 409


async def test_sync_failure_path(client, super_token, db_session):
    """L2E1-04：同步执行失败状态机（task failed + outbox done + 死信 + result failed）。"""
    kb_id, doc_id = await _kb_and_doc(client, super_token, db_session, "E1失败")
    started = await extraction_task_service.start_document_extraction(db_session, kb_id, doc_id)
    result = await execute_sync_task(str(doc_id), str(kb_id))
    assert result["status"] == "failed"
    task = (
        await db_session.execute(
            select(DocumentTask).where(DocumentTask.task_id == started["task_id"])
        )
    ).scalar_one()
    outbox = (
        await db_session.execute(
            select(TaskOutbox).where(TaskOutbox.task_id == started["task_id"])
        )
    ).scalar_one()
    dlq = (
        await db_session.execute(
            select(TaskDeadLetter).where(TaskDeadLetter.task_id == started["task_id"])
        )
    ).scalars().all()
    res = (
        await db_session.execute(
            select(ExtractionResult).where(
                ExtractionResult.kb_id == kb_id,
                ExtractionResult.document_id == doc_id,
            )
        )
    ).scalar_one()
    doc = await db_session.get(Document, doc_id)
    assert task.status == "failed"
    assert outbox.status == "done"
    assert dlq and "E3" in dlq[0].error
    assert res.status == "failed" and res.progress == 100
    assert doc.extraction_status == "failed"


async def test_result_store_save_archive_and_delete(client, super_token, db_session):
    """L2E1-05：结果保存版本自增、旧版归档、删除清理。"""
    kb_id, doc_id = await _kb_and_doc(client, super_token, db_session, "E1结果")
    await db_session.execute(sa_text("SELECT set_config('app.is_superuser', 'true', true)"))
    await result_store.save_result(
        db_session, kb_id, doc_id, schema_name="S1",
        categories=[{"feature": "A", "records": [{"x": 1}]}], summary={"total_records": 1},
        status="completed",
    )
    latest = await result_store.get_latest(db_session, kb_id, doc_id)
    assert latest is not None and latest.version == 1
    await result_store.save_result(
        db_session, kb_id, doc_id, schema_name="S2", categories=[], summary={}, status="completed",
    )
    latest = await result_store.get_latest(db_session, kb_id, doc_id)
    assert latest.version == 2
    assert await result_store.history_count(db_session, kb_id, doc_id) == 1
    await result_store.delete_result_and_history(db_session, kb_id, doc_id)
    assert await result_store.get_latest(db_session, kb_id, doc_id) is None
    assert await result_store.history_count(db_session, kb_id, doc_id) == 0
    doc = await db_session.get(Document, doc_id)
    assert doc.extraction_status is None
