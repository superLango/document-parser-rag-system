"""L2/L3 集成：E2 资源配置 API + 抽取配置解析器。"""

import uuid

from app.services.extraction import extraction_resolver
from sqlalchemy import text as sa_text

from qa.fixtures.indexing_helpers import create_kb_via_api

H = "Authorization"


async def test_llm_resource_crud_and_masking(client, super_token):
    """L2E2-01：LLM 资源配置保存/读取/Key 掩码/留空保持。"""
    kb = await create_kb_via_api(client, super_token, "E2资源")
    h = {H: f"Bearer {super_token}"}
    r = await client.put(f"/api/v1/kb/{kb['id']}/resources/llm", headers=h, json={
        "enabled": True, "api_base": "http://127.0.0.1:8001/v1", "model": "qwen",
        "api_key": "secret1234", "timeout": 120,
    })
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["enabled"] is True and data["api_base"].endswith("/v1")
    assert data["api_key_masked"] == "****1234"
    assert "api_key" not in data

    r = await client.get(f"/api/v1/kb/{kb['id']}/resources/llm", headers=h)
    assert r.json()["data"]["api_key_masked"] == "****1234"

    # 留空 api_key 保持旧值
    r = await client.put(f"/api/v1/kb/{kb['id']}/resources/llm", headers=h, json={
        "enabled": True, "api_base": "http://127.0.0.1:8001/v1", "model": "qwen2", "api_key": "", "timeout": 120,
    })
    assert r.json()["data"]["model"] == "qwen2"
    assert r.json()["data"]["api_key_masked"] == "****1234"


async def test_llm_test_connection_unreachable(client, super_token):
    """L2E2-02：不可达地址测试连接返回 ok=false。"""
    kb = await create_kb_via_api(client, super_token, "E2测试")
    h = {H: f"Bearer {super_token}"}
    r = await client.post(f"/api/v1/kb/{kb['id']}/resources/llm/test", headers=h, json={
        "enabled": True, "api_base": "http://127.0.0.1:9/v1", "model": "qwen", "timeout": 2,
    })
    assert r.status_code == 200, r.text
    assert r.json()["data"]["ok"] is False
    assert r.json()["data"]["error"]


async def test_resolver_aggregates_all_configs(client, super_token, db_session):
    """L2E2-03：解析器聚合 Schema/Prompt/规则组/全局配置/术语集。"""
    kb = await create_kb_via_api(client, super_token, "E2解析")
    h = {H: f"Bearer {super_token}"}
    tpl = (await client.post(f"/api/v1/kb/{kb['id']}/schema-templates", headers=h, json={"name": "T"})).json()["data"]
    cat = (await client.post(f"/api/v1/kb/{kb['id']}/schema-templates/{tpl['id']}/categories", headers=h, json={"name": "C"})).json()["data"]
    await client.post(f"/api/v1/kb/{kb['id']}/schema-templates/{tpl['id']}/categories/{cat['id']}/fields", headers=h, json={"name": "f1", "type": "string"})
    prompt = (await client.post(f"/api/v1/kb/{kb['id']}/extraction-config/prompts", headers=h, json={
        "name": "P", "scope": "schema", "schema_template_id": tpl["id"], "category_ids": [cat["id"]],
    })).json()["data"]
    await client.put(f"/api/v1/kb/{kb['id']}/extraction-config/prompts/{prompt['id']}/save", headers=h, json={
        "system_prompt": "sys", "categories": [{"category_id": cat["id"], "user_prompt": "u"}],
    })
    sc = (await client.post(f"/api/v1/kb/{kb['id']}/extraction-config/scripts", headers=h, json={
        "folder": "post", "name": "clean", "code": "def run(args): return args",
    })).json()["data"]
    gid = (await client.post(f"/api/v1/kb/{kb['id']}/extraction-config/rule-groups", headers=h, json={
        "schema_template_id": tpl["id"],
    })).json()["data"]["id"]
    await client.put(f"/api/v1/kb/{kb['id']}/extraction-config/rule-groups/{gid}/items", headers=h, json={
        "category_id": cat["id"], "items": [{"script_id": sc["id"], "stage": "post"}],
    })
    await db_session.execute(sa_text("SELECT set_config('app.is_superuser', 'true', true)"))

    cfg = await extraction_resolver.resolve(db_session, uuid.UUID(kb["id"]))
    assert cfg.global_config["retrieval"]["top_k"] == 10
    assert len(cfg.schema_templates) == 1
    assert cfg.schema_templates[0]["categories"][0]["fields"][0]["name"] == "f1"
    assert len(cfg.prompt_templates) == 1
    assert cfg.prompt_templates[0]["categories"][0]["user_prompt"] == "u"
    assert cfg.rule_groups[0]["categories"][0]["rules"][0]["script_name"] == "clean"
    assert cfg.term_bases == []
