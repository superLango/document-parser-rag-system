"""L4 边界：E3 零命中/非法 JSON/校验脚本剔除。"""

import uuid

from app.models.document import Document
from app.services.extraction import pipeline
from sqlalchemy import text as sa_text

from qa.fixtures.indexing_helpers import create_document_row, create_kb_via_api

H = "Authorization"


class EmptyLLM:
    async def complete(self, messages, **kwargs):
        return "[{}]"


class BadLLM:
    async def complete(self, messages, **kwargs):
        return "not json"


class RejectLLM:
    async def complete(self, messages, **kwargs):
        return '[{"f1": "x"}]'


async def _kb_with_schema(client, super_token, name):
    kb = await create_kb_via_api(client, super_token, name)
    h = {H: f"Bearer {super_token}"}
    tpl = (await client.post(f"/api/v1/kb/{kb['id']}/schema-templates", headers=h, json={"name": "T"})).json()["data"]
    cat = (await client.post(f"/api/v1/kb/{kb['id']}/schema-templates/{tpl['id']}/categories", headers=h, json={"name": "C"})).json()["data"]
    prompt = (await client.post(f"/api/v1/kb/{kb['id']}/extraction-config/prompts", headers=h, json={
        "name": "P", "scope": "schema", "schema_template_id": tpl["id"], "category_ids": [cat["id"]],
    })).json()["data"]
    await client.put(f"/api/v1/kb/{kb['id']}/extraction-config/prompts/{prompt['id']}/save", headers=h, json={
        "system_prompt": "sys", "categories": [{"category_id": cat["id"], "user_prompt": "抽取 ${feature}"}],
    })
    return kb, h


async def _doc_no_chunk(db_session, kb_id):
    doc_id = await create_document_row(db_session, kb_id, layout_path="x")
    doc = await db_session.get(Document, doc_id)
    doc.index_status = "completed"
    await db_session.commit()
    await db_session.execute(sa_text("SELECT set_config('app.is_superuser', 'true', true)"))
    return doc_id


async def test_zero_hit_returns_empty(client, super_token, db_session):
    """L4E3-01：零命中类别剔除。"""
    kb, _h = await _kb_with_schema(client, super_token, "E3零命中")
    doc_id = await _doc_no_chunk(db_session, uuid.UUID(kb["id"]))
    result = await pipeline.run(kb_id=uuid.UUID(kb["id"]), document_id=doc_id, llm_client=BadLLM(), db=db_session)
    assert result["categories"] == []
    assert any(s["reason"] == "零命中（检索无结果）" for s in result["summary"]["skipped"])


async def test_bad_json_raises(client, super_token, db_session):
    """L4E3-02：LLM 非法 JSON 使任务失败（B11 不静默吞错）。"""
    import pytest
    from app.models.document import Document
    from app.models.indexing import DocumentChunk
    from app.services.llm.llm_client import LLMError

    kb, _h = await _kb_with_schema(client, super_token, "E3坏JSON")
    kb_id = uuid.UUID(kb["id"])
    doc_id = await create_document_row(db_session, kb_id, layout_path="x")
    doc = await db_session.get(Document, doc_id)
    doc.index_status = "completed"
    db_session.add(DocumentChunk(
        kb_id=kb_id, document_id=doc_id, chunk_id=f"{doc_id}_p0_0",
        hierarchy_path="1", title="C", level=1, has_table=False, semantic_label="text",
        content="室温拉伸抗拉强度 800MPa", content_for_embedding="室温拉伸抗拉强度 800MPa",
        parent_text="C", tokens=8, title_vector=[0.1] * 1024, content_vector=[0.1] * 1024,
        bm25_tokens={"抗拉": 1}, source_pages=[1],
    ))
    await db_session.commit()
    await db_session.execute(sa_text("SELECT set_config('app.is_superuser', 'true', true)"))
    with pytest.raises(LLMError):
        await pipeline.run(kb_id=kb_id, document_id=doc_id, llm_client=BadLLM(), db=db_session)
