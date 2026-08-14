"""L2/L3 集成：M34 全局配置 GET/PUT 全流程。"""


from qa.fixtures.indexing_helpers import create_kb_via_api

H = "Authorization"


async def _kb(client, super_token, name):
    kb = await create_kb_via_api(client, super_token, name)
    return kb["id"]


async def test_global_config_default_and_save(client, super_token):
    """L2G-01：GET 默认 → PUT 保存 → GET 持久化 + 版本自增。"""
    kb_id = await _kb(client, super_token, "S10全局")
    h = {H: f"Bearer {super_token}"}

    r = await client.get(f"/api/v1/kb/{kb_id}/extraction-config/global", headers=h)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["enabled"] is True
    assert data["version"] == 1
    assert data["content"]["retrieval"]["top_k"] == 10
    assert data["content"]["kb_tool"]["script_timeout"] == 60

    # 部分覆盖保存
    r = await client.put(f"/api/v1/kb/{kb_id}/extraction-config/global", headers=h, json={
        "enabled": True,
        "content": {
            "retrieval": {"top_k": 30, "hybrid": {"rrf_k": 80}, "category_recall": {"mode": "strict", "top_k": 6}},
            "kb_tool": {"script_timeout": 20},
        },
    })
    assert r.status_code == 200, r.text
    saved = r.json()["data"]
    assert saved["version"] == 2
    assert saved["content"]["retrieval"]["top_k"] == 30
    assert saved["content"]["retrieval"]["hybrid"]["rrf_k"] == 80
    assert saved["content"]["retrieval"]["candidate_mult"] == 2  # 未覆盖保留默认
    assert saved["content"]["retrieval"]["category_recall"]["mode"] == "strict"
    assert saved["content"]["retrieval"]["category_recall"]["top_k"] == 6
    assert saved["content"]["kb_tool"]["script_timeout"] == 20

    r = await client.get(f"/api/v1/kb/{kb_id}/extraction-config/global", headers=h)
    data = r.json()["data"]
    assert data["version"] == 2
    assert data["content"]["retrieval"]["category_recall"]["mode"] == "strict"
    assert data["content"]["retrieval"]["top_k"] == 30
    assert data["content"]["kb_tool"]["script_timeout"] == 20

    # 再次保存版本继续自增
    r = await client.put(f"/api/v1/kb/{kb_id}/extraction-config/global", headers=h, json={
        "enabled": True,
        "content": {"retrieval": {"top_k": 40}},
    })
    assert r.json()["data"]["version"] == 3


async def test_global_config_invalid_payload_422(client, super_token):
    """L2G-02：非法内容返回 422。"""
    kb_id = await _kb(client, super_token, "S10全局非法")
    h = {H: f"Bearer {super_token}"}
    r = await client.put(f"/api/v1/kb/{kb_id}/extraction-config/global", headers=h, json={
        "enabled": True,
        "content": {"retrieval": {"top_k": 0}},
    })
    assert r.status_code == 400


async def test_global_config_cross_kb_isolation(client, super_token):
    """L2G-03：A KB 保存的全局配置不影响 B KB。"""
    a = await _kb(client, super_token, "S10全局A")
    b = await _kb(client, super_token, "S10全局B")
    h = {H: f"Bearer {super_token}"}
    await client.put(f"/api/v1/kb/{a}/extraction-config/global", headers=h, json={
        "enabled": True,
        "content": {"retrieval": {"top_k": 66}},
    })
    data = (await client.get(f"/api/v1/kb/{b}/extraction-config/global", headers=h)).json()["data"]
    assert data["content"]["retrieval"]["top_k"] == 10
