"""L2/L3 集成：E3 抽取流水线（mock LLM + 术语集 + 脚本）。"""

import uuid

from app.models.document import Document
from app.models.indexing import DocumentChunk
from app.services.extraction import pipeline
from sqlalchemy import text as sa_text

from qa.fixtures.indexing_helpers import create_document_row, create_kb_via_api

H = "Authorization"
DIM = 1024


class MockLLM:
    def __init__(self):
        self.calls = []

    async def complete(self, messages, **kwargs):
        self.calls.append(messages)
        return '[{"f1": "抗拉强度值"}]'


async def _setup_full(client, super_token, db_session, name):
    kb = await create_kb_via_api(client, super_token, name)
    kb_id = uuid.UUID(kb["id"])
    h = {H: f"Bearer {super_token}"}
    # 术语集
    tb = (await client.post(f"/api/v1/kb/{kb['id']}/term-bases", headers=h, json={
        "name": "材料库", "source_type": "manual", "auto_import": True,
        "import_data": [{"term": "抗拉强度", "standard_name": "拉伸强度"}],
    })).json()["data"]
    # Schema：手动类别 + 必填字段
    tpl = (await client.post(f"/api/v1/kb/{kb['id']}/schema-templates", headers=h, json={"name": "材料模板"})).json()["data"]
    cat = (await client.post(f"/api/v1/kb/{kb['id']}/schema-templates/{tpl['id']}/categories", headers=h, json={
        "name": "室温拉伸", "fields": [],
        "query_sources": [{"label": "材料库", "term_base_id": tb["id"], "value_field": "standard_name", "in_query": True}],
    })).json()["data"]
    await client.post(f"/api/v1/kb/{kb['id']}/schema-templates/{tpl['id']}/categories/{cat['id']}/fields", headers=h, json={
        "name": "f1", "type": "string", "required": True,
    })
    # Prompt
    prompt = (await client.post(f"/api/v1/kb/{kb['id']}/extraction-config/prompts", headers=h, json={
        "name": "P", "scope": "schema", "schema_template_id": tpl["id"], "category_ids": [cat["id"]],
    })).json()["data"]
    await client.put(f"/api/v1/kb/{kb['id']}/extraction-config/prompts/{prompt['id']}/save", headers=h, json={
        "system_prompt": "你是材料专家", "categories": [{"category_id": cat["id"], "user_prompt": "抽取 ${feature} 的字段 ${f1}，术语 ${材料库.standard_name}"}],
    })
    # 后处理脚本（全量通过）
    sc = (await client.post(f"/api/v1/kb/{kb['id']}/extraction-config/scripts", headers=h, json={
        "folder": "post", "name": "pass", "code": "def run(args): return {'records': args['records']}",
    })).json()["data"]
    gid = (await client.post(f"/api/v1/kb/{kb['id']}/extraction-config/rule-groups", headers=h, json={
        "schema_template_id": tpl["id"],
    })).json()["data"]["id"]
    await client.put(f"/api/v1/kb/{kb['id']}/extraction-config/rule-groups/{gid}/items", headers=h, json={
        "category_id": cat["id"], "items": [{"script_id": sc["id"], "stage": "post"}],
    })
    # 文档 + 分块
    doc_id = await create_document_row(db_session, kb_id, layout_path="x")
    doc = await db_session.get(Document, doc_id)
    doc.index_status = "indexed"
    db_session.add(DocumentChunk(
        kb_id=kb_id, document_id=doc_id, chunk_id=f"{doc_id}_p0_0",
        hierarchy_path="1 范围", title="范围", level=1, has_table=False, semantic_label="text",
        content="室温拉伸抗拉强度值 800MPa", content_for_embedding="室温拉伸抗拉强度值 800MPa",
        parent_text="室温拉伸", tokens=8, title_vector=[0.1] * DIM, content_vector=[0.1] * DIM,
        bm25_tokens={"抗拉": 1, "室温": 1}, source_pages=[1],
    ))
    await db_session.commit()
    await db_session.execute(sa_text("SELECT set_config('app.is_superuser', 'true', true)"))
    return kb_id, doc_id, tb, cat, MockLLM()


async def test_pipeline_full_flow(client, super_token, db_session):
    """L2E3-01：配置+检索+Prompt+LLM+脚本 全流程产出记录。"""
    kb_id, doc_id, _tb, _cat, mock = await _setup_full(client, super_token, db_session, "E3全流程")
    result = await pipeline.run(kb_id=kb_id, document_id=doc_id, llm_client=mock, db=db_session)
    assert result["schema_name"] == "材料模板"
    assert len(result["categories"]) >= 1
    assert result["summary"]["total_records"] >= 1
    assert result["categories"][0]["records"][0]["f1"] == "抗拉强度值"
    # Prompt 中术语集占位符被真实值替换
    user_prompt = "".join(m["content"] for m in mock.calls[0] if m["role"] == "user")
    assert "[拉伸强度]" in user_prompt
