"""L2/L3 集成：M34-S2 抽取配置 API 全流程。"""

import uuid

from qa.fixtures.indexing_helpers import create_kb_via_api

H = "Authorization"


async def _kb(client, super_token, name):
    kb = await create_kb_via_api(client, super_token, name)
    return kb["id"]


async def _create_term_base(client, token, kb_id, name):
    r = await client.post(
        f"/api/v1/kb/{kb_id}/term-bases",
        headers={H: f"Bearer {token}"},
        json={"name": name, "source_type": "manual"},
    )
    assert r.status_code == 200, r.text
    return r.json()["data"]["id"]


async def test_schema_template_full_flow(client, super_token):
    """L3M34-S2-01：Schema 模板→类别（术语集联动）→字段全流程。"""
    kb_id = await _kb(client, super_token, "S10Schema")
    h = {H: f"Bearer {super_token}"}
    tb_id = await _create_term_base(client, super_token, kb_id, "材料库")

    r = await client.post(f"/api/v1/kb/{kb_id}/schema-templates", headers=h,
                          json={"name": "材料检测", "description": "模板"})
    assert r.status_code == 200, r.text
    tpl_id = r.json()["data"]["id"]

    r = await client.post(
        f"/api/v1/kb/{kb_id}/schema-templates/{tpl_id}/categories", headers=h,
        json={
            "name": "", "name_source": "term_base", "name_term_base_id": tb_id,
            "name_term_field": "term_name",
            "query_sources": [{"label": "材料", "term_base_id": tb_id, "value_field": "name",
                               "in_query": True, "query_main_limit": 30}],
            "return_type": "array", "extraction_strategy": "auto",
        },
    )
    assert r.status_code == 200, r.text
    cat_id = r.json()["data"]["id"]

    r = await client.post(
        f"/api/v1/kb/{kb_id}/schema-templates/{tpl_id}/categories/{cat_id}/fields", headers=h,
        json={"name": "抗拉强度", "type": "string", "required": True},
    )
    assert r.status_code == 200, r.text
    field_id = r.json()["data"]["id"]

    detail = await client.get(f"/api/v1/kb/{kb_id}/schema-templates/{tpl_id}", headers=h)
    data = detail.json()["data"]
    assert data["categories"][0]["name_source"] == "term_base"
    assert data["categories"][0]["query_sources"][0]["in_query"] is True
    assert data["categories"][0]["fields"][0]["name"] == "抗拉强度"

    # 更新字段 + 删除字段
    r = await client.put(
        f"/api/v1/kb/{kb_id}/schema-templates/{tpl_id}/categories/{cat_id}/fields/{field_id}", headers=h,
        json={"description": "提升精度"},
    )
    assert r.status_code == 200
    r = await client.delete(
        f"/api/v1/kb/{kb_id}/schema-templates/{tpl_id}/categories/{cat_id}/fields/{field_id}", headers=h
    )
    assert r.status_code == 200

    # 级联：删模板 → 类别/字段消失
    await client.delete(f"/api/v1/kb/{kb_id}/schema-templates/{tpl_id}", headers=h)
    r = await client.get(f"/api/v1/kb/{kb_id}/schema-templates", headers=h)
    assert all(t["id"] != tpl_id for t in r.json()["data"]["items"])


async def test_prompt_simple_and_schema(client, super_token):
    """L3M34-S2-02：Prompt simple/schema 创建与保存。"""
    kb_id = await _kb(client, super_token, "S10Prompt")
    h = {H: f"Bearer {super_token}"}
    tpl = (await client.post(f"/api/v1/kb/{kb_id}/schema-templates", headers=h,
                             json={"name": "模板P"})).json()["data"]
    cat = (await client.post(f"/api/v1/kb/{kb_id}/schema-templates/{tpl['id']}/categories", headers=h,
                             json={"name": "类别1"})).json()["data"]

    # simple
    r = await client.post(f"/api/v1/kb/{kb_id}/extraction-config/prompts", headers=h,
                          json={"name": "简单P", "scope": "simple", "system_prompt": "sys", "user_prompt": "user"})
    assert r.status_code == 200, r.text
    pid = r.json()["data"]["id"]
    r = await client.put(f"/api/v1/kb/{kb_id}/extraction-config/prompts/{pid}/save", headers=h,
                         json={"system_prompt": "sys2", "user_prompt": "user2"})
    assert r.json()["data"]["system_prompt"] == "sys2"

    # schema
    r = await client.post(f"/api/v1/kb/{kb_id}/extraction-config/prompts", headers=h,
                          json={"name": "SchemaP", "scope": "schema", "schema_template_id": tpl["id"],
                                "category_ids": [cat["id"]]})
    assert r.status_code == 200, r.text
    pid2 = r.json()["data"]["id"]
    r = await client.put(f"/api/v1/kb/{kb_id}/extraction-config/prompts/{pid2}/save", headers=h,
                         json={"system_prompt": "全局sys", "categories": [{"category_id": cat["id"], "user_prompt": "类别提示词"}]})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["categories"][0]["user_prompt"] == "类别提示词"
    assert r.json()["data"]["categories"][0]["category_name"] == "类别1"
    detail = (await client.get(f"/api/v1/kb/{kb_id}/extraction-config/prompts/{pid2}", headers=h)).json()["data"]
    assert detail["categories"][0]["category_name"] == "类别1"

    # 非法类别保存被拒
    r = await client.put(f"/api/v1/kb/{kb_id}/extraction-config/prompts/{pid2}/save", headers=h,
                         json={"categories": [{"category_id": str(uuid.uuid4()), "user_prompt": "x"}]})
    assert r.status_code == 400

    await client.delete(f"/api/v1/kb/{kb_id}/extraction-config/prompts/{pid}", headers=h)
    r = await client.get(f"/api/v1/kb/{kb_id}/extraction-config/prompts", headers=h)
    assert all(p["id"] != pid for p in r.json()["data"]["items"])


async def test_delete_category_with_prompt_content(client, super_token):
    """L3M34-S2-01c：删除被 Schema Prompt 引用的类别不触发 uq_prompt_content_simple 冲突。"""
    kb_id = await _kb(client, super_token, "S10删类别")
    h = {H: f"Bearer {super_token}"}
    tpl = (await client.post(f"/api/v1/kb/{kb_id}/schema-templates", headers=h,
                             json={"name": "模板D"})).json()["data"]
    cat = (await client.post(f"/api/v1/kb/{kb_id}/schema-templates/{tpl['id']}/categories", headers=h,
                             json={"name": "类别D"})).json()["data"]
    pid = (await client.post(f"/api/v1/kb/{kb_id}/extraction-config/prompts", headers=h,
                             json={"name": "PromptD", "scope": "schema",
                                   "schema_template_id": tpl["id"], "category_ids": [cat["id"]]})).json()["data"]["id"]
    await client.put(f"/api/v1/kb/{kb_id}/extraction-config/prompts/{pid}/save", headers=h,
                     json={"system_prompt": "sys", "categories": [{"category_id": cat["id"], "user_prompt": "u"}]})

    r = await client.delete(f"/api/v1/kb/{kb_id}/schema-templates/{tpl['id']}/categories/{cat['id']}", headers=h)
    assert r.status_code == 200, r.text
    # Prompt 仍存在，且类别内容已清理
    detail = (await client.get(f"/api/v1/kb/{kb_id}/extraction-config/prompts/{pid}", headers=h)).json()["data"]
    assert detail["system_prompt"] == "sys"
    assert all(c["category_id"] != cat["id"] for c in detail["categories"])


async def test_rule_group_flow(client, super_token):
    """L3M34-S2-03：规则组创建/规则项保存/详情/删除。"""
    kb_id = await _kb(client, super_token, "S10规则")
    h = {H: f"Bearer {super_token}"}
    tpl = (await client.post(f"/api/v1/kb/{kb_id}/schema-templates", headers=h,
                             json={"name": "模板R"})).json()["data"]
    cat = (await client.post(f"/api/v1/kb/{kb_id}/schema-templates/{tpl['id']}/categories", headers=h,
                             json={"name": "类别R"})).json()["data"]

    r = await client.post(f"/api/v1/kb/{kb_id}/extraction-config/rule-groups", headers=h,
                          json={"schema_template_id": tpl["id"]})
    assert r.status_code == 200, r.text
    gid = r.json()["data"]["id"]
    # 一模板一规则组
    r = await client.post(f"/api/v1/kb/{kb_id}/extraction-config/rule-groups", headers=h,
                          json={"schema_template_id": tpl["id"]})
    assert r.status_code == 409

    sc = (await client.post(f"/api/v1/kb/{kb_id}/extraction-config/scripts", headers=h,
                             json={"folder": "post", "name": "clean_records",
                                   "code": "def run(args): return args"})).json()["data"]
    r = await client.put(f"/api/v1/kb/{kb_id}/extraction-config/rule-groups/{gid}/items", headers=h,
                         json={"category_id": cat["id"], "items": [
                             {"script_id": sc["id"], "stage": "post"},
                         ]})
    assert r.status_code == 200, r.text
    detail = (await client.get(f"/api/v1/kb/{kb_id}/extraction-config/rule-groups/{gid}", headers=h)).json()["data"]
    rule = detail["categories"][0]["rules"][0]
    assert rule["script_name"] == "clean_records" and rule["stage"] == "post"

    # 全量替换为空
    await client.put(f"/api/v1/kb/{kb_id}/extraction-config/rule-groups/{gid}/items", headers=h,
                     json={"category_id": cat["id"], "items": []})
    detail2 = (await client.get(f"/api/v1/kb/{kb_id}/extraction-config/rule-groups/{gid}", headers=h)).json()["data"]
    assert detail2["categories"][0]["rules"] == []

    await client.delete(f"/api/v1/kb/{kb_id}/extraction-config/rule-groups/{gid}", headers=h)
    r = await client.get(f"/api/v1/kb/{kb_id}/extraction-config/rule-groups", headers=h)
    assert all(g["id"] != gid for g in r.json()["data"]["items"])


async def test_rule_group_term_base_category_name(client, super_token):
    """L3M34-S2-03b：规则组详情中术语库来源且名称为空的类别回退术语集名。"""
    kb_id = await _kb(client, super_token, "S10术语规则")
    h = {H: f"Bearer {super_token}"}
    tb = (await client.post(f"/api/v1/kb/{kb_id}/term-bases", headers=h,
                            json={"name": "回退材料库", "source_type": "manual"})).json()["data"]
    tpl = (await client.post(f"/api/v1/kb/{kb_id}/schema-templates", headers=h,
                             json={"name": "模板T"})).json()["data"]
    await client.post(f"/api/v1/kb/{kb_id}/schema-templates/{tpl['id']}/categories", headers=h,
                       json={"name": "", "name_source": "term_base",
                             "name_term_base_id": tb["id"], "name_term_field": "term_name"})
    gid = (await client.post(f"/api/v1/kb/{kb_id}/extraction-config/rule-groups", headers=h,
                             json={"schema_template_id": tpl["id"]})).json()["data"]["id"]
    detail = (await client.get(f"/api/v1/kb/{kb_id}/extraction-config/rule-groups/{gid}", headers=h)).json()["data"]
    names = [c["name"] for c in detail["categories"]]
    assert "回退材料库" in names, names
    await client.delete(f"/api/v1/kb/{kb_id}/extraction-config/rule-groups/{gid}", headers=h)


async def test_script_crud_and_run(client, super_token, db_session):
    """L3M34-S2-04：脚本 CRUD、IO、受限运行与术语集注入。"""
    kb_id = await _kb(client, super_token, "S10脚本")
    h = {H: f"Bearer {super_token}"}
    # 建术语集供注入
    await client.post(f"/api/v1/kb/{kb_id}/term-bases", headers=h,
                       json={"name": "材料库", "source_type": "manual", "auto_import": True,
                             "import_data": [{"term": "抗拉强度", "standard_name": "拉伸强度"}]})

    r = await client.get(f"/api/v1/kb/{kb_id}/extraction-config/scripts/io", headers=h)
    assert set(r.json()["data"]["folders"]) == {"post", "validation"}

    r = await client.post(f"/api/v1/kb/{kb_id}/extraction-config/scripts", headers=h,
                          json={"folder": "post", "name": "clean", "code": "def run(args): return args"})
    assert r.status_code == 200, r.text
    sid = r.json()["data"]["id"]
    r = await client.put(f"/api/v1/kb/{kb_id}/extraction-config/scripts/{sid}", headers=h,
                         json={"description": "清理脚本"})
    assert r.status_code == 200

    # 运行（通过 script_id）
    r = await client.post(f"/api/v1/kb/{kb_id}/extraction-config/scripts/run", headers=h,
                          json={"script_id": sid, "args": {"records": [{"a": 1}]}})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["ok"] is True
    assert r.json()["data"]["result"]["records"] == [{"a": 1}]

    # 运行（直接传 code + 术语集工具）
    code = """
async def run(args):
    rows = await kb_tools.get_term_records("材料库", "term_name")
    return {"rows": rows}
"""
    r = await client.post(f"/api/v1/kb/{kb_id}/extraction-config/scripts/run", headers=h,
                          json={"code": code, "args": {}})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["ok"] is True
    assert r.json()["data"]["result"]["rows"] == [{"term_name": "抗拉强度"}]

    await client.delete(f"/api/v1/kb/{kb_id}/extraction-config/scripts/{sid}", headers=h)
    r = await client.get(f"/api/v1/kb/{kb_id}/extraction-config/scripts?folder=post", headers=h)
    assert all(i["id"] != sid for i in r.json()["data"]["items"])
