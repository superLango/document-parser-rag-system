"""L2/L3 集成：E4 抽取端点全流程。"""

import asyncio
import uuid

from app.models.document import Document
from app.models.indexing import DocumentChunk
from app.services.extraction import result_store
from sqlalchemy import text as sa_text

from qa.fixtures.indexing_helpers import create_document_row, create_kb_via_api

H = "Authorization"
DIM = 1024


async def _setup(client, super_token, db_session, name, indexed=True):
    kb = await create_kb_via_api(client, super_token, name)
    kb_id = uuid.UUID(kb["id"])
    h = {H: f"Bearer {super_token}"}
    doc_id = await create_document_row(db_session, kb_id, layout_path="x" if indexed else None)
    if indexed:
        doc = await db_session.get(Document, doc_id)
        doc.index_status = "completed"
        db_session.add(DocumentChunk(
            kb_id=kb_id, document_id=doc_id, chunk_id=f"{doc_id}_p0_0",
            hierarchy_path="1", title="C", level=1, has_table=False, semantic_label="text",
            content="室温拉伸抗拉强度 800MPa", content_for_embedding="室温拉伸抗拉强度 800MPa",
            parent_text="C", tokens=8, title_vector=[0.1] * DIM, content_vector=[0.1] * DIM,
            bm25_tokens={"抗拉": 1}, source_pages=[1],
        ))
        await db_session.commit()
        # Schema + Prompt，保证流水线进入 LLM 阶段
        tpl = (await client.post(f"/api/v1/kb/{kb['id']}/schema-templates", headers=h, json={"name": "T"})).json()["data"]
        cat = (await client.post(f"/api/v1/kb/{kb['id']}/schema-templates/{tpl['id']}/categories", headers=h, json={"name": "C"})).json()["data"]
        prompt = (await client.post(f"/api/v1/kb/{kb['id']}/extraction-config/prompts", headers=h, json={
            "name": "P", "scope": "schema", "schema_template_id": tpl["id"], "category_ids": [cat["id"]],
        })).json()["data"]
        await client.put(f"/api/v1/kb/{kb['id']}/extraction-config/prompts/{prompt['id']}/save", headers=h, json={
            "system_prompt": "sys", "categories": [{"category_id": cat["id"], "user_prompt": "u"}],
        })
        # LLM 资源：指向不可达地址，测试连接失败路径
        await client.put(f"/api/v1/kb/{kb['id']}/resources/llm", headers=h, json={
            "enabled": True, "api_base": "http://127.0.0.1:9/v1", "model": "qwen", "timeout": 2,
        })
    await db_session.execute(sa_text("SELECT set_config('app.is_superuser', 'true', true)"))
    return kb, kb_id, doc_id


async def _wait_status(client, token, kb_id, doc_id, timeout=20.0):
    deadline = asyncio.get_event_loop().time() + timeout
    last = None
    while asyncio.get_event_loop().time() < deadline:
        r = await client.get(f"/api/v1/kb/{kb_id}/extraction/{doc_id}/status", headers={H: f"Bearer {token}"})
        last = r.json()["data"]
        if last["status"] in ("completed", "failed"):
            return last
        await asyncio.sleep(0.3)
    raise AssertionError(f"状态未收敛：{last}")


async def test_list_start_status_result_delete(client, super_token, db_session):
    """L2E4-01：列表→启动→状态失败→结果→导出→删除。"""
    _kb, kb_id, doc_id = await _setup(client, super_token, db_session, "E4全流程")
    h = {H: f"Bearer {super_token}"}

    r = await client.get(f"/api/v1/kb/{kb_id}/extraction/documents", headers=h)
    assert r.status_code == 200
    items = r.json()["data"]["items"]
    assert any(i["id"] == str(doc_id) for i in items)

    r = await client.post(f"/api/v1/kb/{kb_id}/extraction/{doc_id}", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["status"] == "queued"

    status = await _wait_status(client, super_token, kb_id, doc_id)
    assert status["status"] == "failed"

    r = await client.get(f"/api/v1/kb/{kb_id}/extraction/{doc_id}/result", headers=h)
    data = r.json()["data"]
    assert data is not None and data["status"] == "failed"

    r = await client.get(f"/api/v1/kb/{kb_id}/extraction/{doc_id}/history", headers=h)
    assert r.json()["data"]["items"] == []

    r = await client.get(f"/api/v1/kb/{kb_id}/extraction/export?document_id={doc_id}", headers=h)
    assert r.status_code == 200 and "类别" in r.text

    r = await client.delete(f"/api/v1/kb/{kb_id}/extraction/{doc_id}/result", headers=h)
    assert r.status_code == 200
    r = await client.get(f"/api/v1/kb/{kb_id}/extraction/{doc_id}/result", headers=h)
    assert r.json()["data"] is None


async def test_start_prereq_reject(client, super_token, db_session):
    """L2E4-02：未完成索引的文档拒绝启动。"""
    _kb, kb_id, doc_id = await _setup(client, super_token, db_session, "E4前置", indexed=False)
    r = await client.post(f"/api/v1/kb/{kb_id}/extraction/{doc_id}", headers={H: f"Bearer {super_token}"})
    assert r.status_code == 400


async def test_concurrent_start_same_doc(client, super_token, db_session):
    """L2E4-03：同一文档并发启动仅一个成功。"""
    _kb, kb_id, doc_id = await _setup(client, super_token, db_session, "E4并发")
    h = {H: f"Bearer {super_token}"}

    async def _start():
        return await client.post(f"/api/v1/kb/{kb_id}/extraction/{doc_id}", headers=h)

    r1, r2 = await asyncio.gather(_start(), _start())
    codes = sorted([r1.status_code, r2.status_code])
    assert codes == [200, 409], (r1.text, r2.text)


async def test_result_store_via_endpoint(client, super_token, db_session):
    """L2E4-04：预置结果后通过端点读取/删除。"""
    _kb, kb_id, doc_id = await _setup(client, super_token, db_session, "E4结果")
    h = {H: f"Bearer {super_token}"}
    await result_store.save_result(
        db_session, kb_id, doc_id, schema_name="S",
        categories=[{"feature": "C", "records": [{"f1": "v"}]}],
        summary={"total_records": 1}, status="completed",
    )
    r = await client.get(f"/api/v1/kb/{kb_id}/extraction/{doc_id}/result", headers=h)
    assert r.json()["data"]["categories"][0]["records"][0]["f1"] == "v"
    r = await client.get(f"/api/v1/kb/{kb_id}/extraction/export?document_id={doc_id}", headers=h)
    assert "C" in r.text and "f1" in r.text
