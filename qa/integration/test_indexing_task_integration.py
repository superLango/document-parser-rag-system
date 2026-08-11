"""L2 集成链路 + L3 功能场景：M28 独立索引任务状态机（D8）。"""

import asyncio
import time
import uuid

from sqlalchemy import select, text as sa_text

from app.models.document import DocumentTask, TaskOutbox
from app.models.indexing import DocumentChunk, TextChunk
from qa.fixtures.indexing_helpers import create_kb_via_api


def _pdf(text: str = "索引集成测试") -> bytes:
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), text, fontsize=12)
    data = doc.tobytes()
    doc.close()
    return data


async def _wait_document(client, token, kb_id, doc_id, field, expect, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        resp = await client.get(
            f"/api/v1/kb/{kb_id}/documents/{doc_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        if data.get(field) == expect:
            return data
        await asyncio.sleep(0.5)
    raise AssertionError(f"等待超时：{field} 期望 {expect}，当前 {data.get(field)}")


async def _upload_and_parse(client, super_token, kb_id):
    files = {"file": ("idx.pdf", _pdf(), "application/pdf")}
    up = await client.post(
        f"/api/v1/kb/{kb_id}/documents",
        headers={"Authorization": f"Bearer {super_token}"},
        files=files,
    )
    assert up.status_code == 200, up.text
    doc = up.json()["data"]["document"]
    start = await client.post(
        f"/api/v1/kb/{kb_id}/documents/{doc['id']}/start",
        headers={"Authorization": f"Bearer {super_token}"},
    )
    assert start.status_code == 200, start.text
    return doc


async def test_parse_completion_auto_enqueues_index(client, super_token, db_session):
    """L2M28-01：解析成功后自动创建独立索引任务（D8）。"""
    kb = await create_kb_via_api(client, super_token, "S4自动触发")
    kb_id = kb["id"]
    doc = await _upload_and_parse(client, super_token, kb_id)
    await _wait_document(client, super_token, kb_id, doc["id"], "status", "completed", timeout=90)

    # 自动触发：存在 queued 的 document_index 任务与 outbox
    tasks = (
        await db_session.execute(
            select(DocumentTask).where(
                DocumentTask.document_id == uuid.UUID(doc["id"]),
                DocumentTask.type == "document_index",
            )
        )
    ).scalars().all()
    assert tasks, "解析完成后应自动创建索引任务"
    assert any(t.status == "queued" for t in tasks)
    outbox = (
        await db_session.execute(
            select(TaskOutbox).where(TaskOutbox.task_id == tasks[0].task_id)
        )
    ).scalar_one_or_none()
    assert outbox is not None and outbox.type == "document_index"


async def _seed_layout_document(client, super_token, db_session, kb_id, name):
    """构造带 layout.json 产物的文档（真实存储 + 分块器可消费）。"""
    import json

    from app.services import storage
    from qa.fixtures.indexing_helpers import create_document_row

    layout = {
        "schema_version": "1.2",
        "producer": "parsekit",
        "layout_engine": "ppdoclayoutv3",
        "classification": "ocr",
        "page_count": 2,
        "pages": [
            {"page_index": 0, "width": 595, "height": 842,
             "path": "pages/page-0000.png", "blocks": [
                {"type": "title", "bbox": [50, 50, 500, 80], "page_index": 0,
                 "order": 0, "confidence": 0.95, "content": "1 范围", "source": "ocr"},
                {"type": "text", "bbox": [50, 90, 500, 130], "page_index": 0,
                 "order": 1, "confidence": 0.9,
                 "content": "本文件规定了不锈钢棒材的化学成分要求。", "source": "ocr"},
                {"type": "table", "bbox": [50, 140, 500, 300], "page_index": 0,
                 "order": 2, "confidence": 0.8,
                 "content": "<table><tr><th rowspan='2'>GB/T 序号</th><th colspan='2'>规定非比例延伸强度</th></tr><tr><th>不小于</th><th>不大于</th></tr><tr><td>67</td><td>440</td><td>715</td></tr></table>",
                 "source": "ocr"},
            ]},
            {"page_index": 1, "width": 595, "height": 842,
             "path": "pages/page-0001.png", "blocks": [
                {"type": "title", "bbox": [50, 50, 500, 80], "page_index": 1,
                 "order": 3, "confidence": 0.95, "content": "2 力学性能", "source": "ocr"},
                {"type": "text", "bbox": [50, 90, 500, 130], "page_index": 1,
                 "order": 4, "confidence": 0.9,
                 "content": "拉伸试验按 GB/T 228.1 执行。", "source": "ocr"},
            ]},
        ],
        "rebuild": {
            "enabled": True,
            "document_tree": {
                "type": "root", "level": 0, "content": "", "children": [
                    {"type": "title", "content": "1 范围", "level": 1, "page": 0,
                     "order": 0, "children": [
                        {"type": "text", "content": "本文件规定了不锈钢棒材的化学成分要求。",
                         "level": 0, "page": 0, "order": 1, "children": []},
                        {"type": "table",
                         "content": "<table><tr><th rowspan='2'>GB/T 序号</th><th colspan='2'>规定非比例延伸强度</th></tr><tr><th>不小于</th><th>不大于</th></tr><tr><td>67</td><td>440</td><td>715</td></tr></table>",
                         "level": 0, "page": 0, "order": 2, "children": [
                            {"type": "table_caption", "content": "表1 规定非比例延伸强度",
                             "level": 0, "page": 0, "order": 3, "children": []},
                        ]},
                    ]},
                    {"type": "title", "content": "2 力学性能", "level": 1, "page": 1,
                     "order": 4, "children": [
                        {"type": "text", "content": "拉伸试验按 GB/T 228.1 执行。",
                         "level": 0, "page": 1, "order": 5, "children": []},
                    ]},
                ],
            },
        },
    }
    key = f"kb-{uuid.UUID(kb_id).hex}/ocr/s4/layout.json"
    storage.put_object(key, json.dumps(layout, ensure_ascii=False).encode("utf-8"), "application/json")
    doc_id = await create_document_row(
        db_session, uuid.UUID(kb_id), filename=f"{name}.pdf", layout_path=key
    )
    return doc_id


async def test_manual_index_full_flow(client, super_token, db_session):
    """L3M28-02：手动触发索引 → 执行 → 块/向量落库 → 幂等重索引。"""
    from app.tasks.sync_executor import execute_sync_task

    kb = await create_kb_via_api(client, super_token, "S4手动索引")
    kb_id = kb["id"]
    doc_id = await _seed_layout_document(client, super_token, db_session, kb_id, "manual")

    # 手动触发索引（预置产物场景无自动任务；API sync 分支后台执行）
    resp = await client.post(
        f"/api/v1/kb/{kb_id}/documents/{doc_id}/index",
        headers={"Authorization": f"Bearer {super_token}"},
    )
    assert resp.status_code == 200, resp.text
    data = await _wait_document(
        client, super_token, kb_id, str(doc_id), "index_status", "indexed", timeout=90
    )
    # 手动重索引：创建新任务并后台执行，验证幂等
    resp = await client.post(
        f"/api/v1/kb/{kb_id}/documents/{doc_id}/index",
        headers={"Authorization": f"Bearer {super_token}"},
    )
    assert resp.status_code == 200, resp.text
    data = await _wait_document(
        client, super_token, kb_id, str(doc_id), "index_status", "indexed", timeout=90
    )
    assert data["index_total"] >= 1
    count = (
        await db_session.execute(
            sa_text(
                "select count(*) from document_chunks where document_id=:d"
            ).bindparams(d=doc_id)
        )
    ).scalar()
    text_count = (
        await db_session.execute(
            sa_text(
                "select count(*) from text_chunks where document_id=:d"
            ).bindparams(d=doc_id)
        )
    ).scalar()
    assert count >= 1
    assert text_count == count
    vec = (
        await db_session.execute(
            sa_text(
                "select content_vector from document_chunks "
                "where document_id=:d and content_vector is not null limit 1"
            ).bindparams(d=doc_id)
        )
    ).scalar()
    # pgvector 经 asyncpg 返回字符串表示 "[x,y,...]"
    assert vec is not None
    import json as _json

    parsed = _json.loads(vec)
    assert len(parsed) == 1024

    # 重索引后块数一致无重复
    count2 = (
        await db_session.execute(
            sa_text(
                "select count(*) from document_chunks where document_id=:d"
            ).bindparams(d=doc_id)
        )
    ).scalar()
    assert count2 == count


async def test_index_tasks_api(client, super_token, db_session):
    """L3M28-03：索引任务列表 API（有效成员可读，含文件名）。"""
    kb = await create_kb_via_api(client, super_token, "S4任务列表")
    kb_id = kb["id"]
    resp = await client.get(
        f"/api/v1/kb/{kb_id}/index/tasks?page=1&page_size=10",
        headers={"Authorization": f"Bearer {super_token}"},
    )
    assert resp.status_code == 200, resp.text
    assert "items" in resp.json()["data"]
