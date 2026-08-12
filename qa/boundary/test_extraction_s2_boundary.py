"""L4 边界：M34-S2 抽取配置 API 异常路径。"""

import uuid

from qa.fixtures.indexing_helpers import create_kb_via_api

H = "Authorization"


async def _kb(client, super_token, name):
    return (await create_kb_via_api(client, super_token, name))["id"]


async def test_schema_template_duplicate_409(client, super_token):
    """L4M34-S2-01：Schema 模板重名 409。"""
    kb_id = await _kb(client, super_token, "S10模板重名")
    h = {H: f"Bearer {super_token}"}
    await client.post(f"/api/v1/kb/{kb_id}/schema-templates", headers=h, json={"name": "同名"})
    r = await client.post(f"/api/v1/kb/{kb_id}/schema-templates", headers=h, json={"name": "同名"})
    assert r.status_code == 409


async def test_category_invalid_enum(client, super_token):
    """L4M34-S2-02：类别非法枚举返回 4xx。"""
    kb_id = await _kb(client, super_token, "S10非法枚举")
    h = {H: f"Bearer {super_token}"}
    tpl = (await client.post(f"/api/v1/kb/{kb_id}/schema-templates", headers=h,
                             json={"name": "T"})).json()["data"]
    r = await client.post(f"/api/v1/kb/{kb_id}/schema-templates/{tpl['id']}/categories", headers=h,
                          json={"name": "C", "return_type": "bad"})
    assert r.status_code in (400, 422)


async def test_category_cross_kb_term_base_rejected(client, super_token):
    """L4M34-S2-03：类别引用他 KB 术语集被拒。"""
    kb_a = await _kb(client, super_token, "S10引用A")
    kb_b = await _kb(client, super_token, "S10引用B")
    h = {H: f"Bearer {super_token}"}
    tb_b = (await client.post(f"/api/v1/kb/{kb_b}/term-bases", headers=h,
                              json={"name": "B库", "source_type": "manual"})).json()["data"]["id"]
    tpl = (await client.post(f"/api/v1/kb/{kb_a}/schema-templates", headers=h,
                             json={"name": "TA"})).json()["data"]
    r = await client.post(f"/api/v1/kb/{kb_a}/schema-templates/{tpl['id']}/categories", headers=h,
                          json={"name": "C", "name_source": "term_base", "name_term_base_id": tb_b})
    assert r.status_code == 400


async def test_prompt_schema_requires_template(client, super_token):
    """L4M34-S2-04：schema 模式 Prompt 必须绑定模板。"""
    kb_id = await _kb(client, super_token, "S10Prompt缺模板")
    h = {H: f"Bearer {super_token}"}
    r = await client.post(f"/api/v1/kb/{kb_id}/extraction-config/prompts", headers=h,
                          json={"name": "P", "scope": "schema"})
    assert r.status_code == 400


async def test_script_missing_run_function(client, super_token):
    """L4M34-S2-05：脚本未定义 def run(args) 返回 400。"""
    kb_id = await _kb(client, super_token, "S10脚本无run")
    h = {H: f"Bearer {super_token}"}
    r = await client.post(f"/api/v1/kb/{kb_id}/extraction-config/scripts/run", headers=h,
                          json={"code": "print(1)", "args": {}})
    assert r.status_code == 400
    assert "def run(args)" in r.json()["message"]


async def test_script_run_timeout(client, super_token):
    """L4M34-S2-06：脚本执行超时返回错误（不 500）。"""
    kb_id = await _kb(client, super_token, "S10脚本超时")
    h = {H: f"Bearer {super_token}"}
    r = await client.post(f"/api/v1/kb/{kb_id}/extraction-config/scripts/run", headers=h,
                          json={"code": "import time\ndef run(args):\n    time.sleep(11)\n    return {}",
                                "args": {}})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["ok"] is False
    assert "超时" in r.json()["data"]["error"]


async def test_rule_group_template_not_found(client, super_token):
    """L4M34-S2-07：规则组引用不存在模板返回 400。"""
    kb_id = await _kb(client, super_token, "S10规则缺模板")
    h = {H: f"Bearer {super_token}"}
    r = await client.post(f"/api/v1/kb/{kb_id}/extraction-config/rule-groups", headers=h,
                          json={"schema_template_id": str(uuid.uuid4())})
    assert r.status_code == 400


async def test_rule_item_script_not_found(client, super_token):
    """L4M34-S2-08：规则项引用不存在的脚本返回 400。"""
    kb_id = await _kb(client, super_token, "S10规则缺脚本")
    h = {H: f"Bearer {super_token}"}
    tpl = (await client.post(f"/api/v1/kb/{kb_id}/schema-templates", headers=h,
                             json={"name": "T"})).json()["data"]
    g = (await client.post(f"/api/v1/kb/{kb_id}/extraction-config/rule-groups", headers=h,
                           json={"schema_template_id": tpl["id"]})).json()["data"]
    r = await client.put(f"/api/v1/kb/{kb_id}/extraction-config/rule-groups/{g['id']}/items", headers=h,
                         json={"category_id": None, "items": [{"script_id": str(uuid.uuid4()), "stage": "post"}]})
    assert r.status_code == 400
    assert "脚本" in r.json()["message"]
