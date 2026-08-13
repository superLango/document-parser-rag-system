"""L5 安全：E3 流水线跨 KB 配置隔离（RLS）。"""

import uuid

from app.services.extraction import pipeline
from sqlalchemy import text as sa_text

from qa.fixtures.indexing_helpers import (
    create_kb_via_api,
    ensure_test_role,
    grant_table_permissions,
    set_rls_context,
)

H = "Authorization"


class MockLLM:
    async def complete(self, messages, **kwargs):
        return "[{}]"


async def test_pipeline_respects_rls(client, super_token, db_session):
    """L5E3-01：非成员角色看不到配置 → 流水线返回空结果。"""
    kb = await create_kb_via_api(client, super_token, "E3隔离")
    h = {H: f"Bearer {super_token}"}
    tpl = (await client.post(f"/api/v1/kb/{kb['id']}/schema-templates", headers=h, json={"name": "T"})).json()["data"]
    cat = (await client.post(f"/api/v1/kb/{kb['id']}/schema-templates/{tpl['id']}/categories", headers=h, json={"name": "C"})).json()["data"]
    prompt = (await client.post(f"/api/v1/kb/{kb['id']}/extraction-config/prompts", headers=h, json={
        "name": "P", "scope": "schema", "schema_template_id": tpl["id"], "category_ids": [cat["id"]],
    })).json()["data"]
    await client.put(f"/api/v1/kb/{kb['id']}/extraction-config/prompts/{prompt['id']}/save", headers=h, json={
        "system_prompt": "sys", "categories": [{"category_id": cat["id"], "user_prompt": "u"}],
    })

    role = "e3_rls_sec"
    await ensure_test_role(db_session, role)
    await grant_table_permissions(db_session, role, [
        "schema_templates", "schema_categories", "schema_fields", "prompt_templates",
        "prompt_content", "rule_groups", "rule_group_items", "kb_scripts", "kb_extraction_config",
        "term_bases", "terms",
    ])
    try:
        await db_session.execute(sa_text(f"SET ROLE {role}"))
        await set_rls_context(db_session, uuid.UUID(kb["id"]), uuid.uuid4())
        result = await pipeline.run(kb_id=uuid.UUID(kb["id"]), document_id=uuid.uuid4(), llm_client=MockLLM(), db=db_session)
        assert result["categories"] == []
    finally:
        await db_session.execute(sa_text("RESET ROLE"))
