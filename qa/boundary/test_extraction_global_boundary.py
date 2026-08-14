"""L4 边界：M34 全局配置（非法值 / 超大 / 脚本超时上限）。"""


from qa.fixtures.indexing_helpers import create_kb_via_api

H = "Authorization"


async def _kb(client, super_token, name):
    return (await create_kb_via_api(client, super_token, name))["id"]


async def test_global_config_rejects_out_of_range(client, super_token):
    """L4G-01：负数/越界数值 422。"""
    kb_id = await _kb(client, super_token, "S10全局边界")
    h = {H: f"Bearer {super_token}"}
    for bad in (
        {"retrieval": {"candidate_mult": 0}},
        {"retrieval": {"context": {"chars_per_token": 0}}},
        {"kb_tool": {"script_timeout": 0}},
        {"kb_tool": {"script_max_output_bytes": 100}},
        {"llm": {"engines": {"BaseExtract": {"timeout": 0}}}},
    ):
        r = await client.put(f"/api/v1/kb/{kb_id}/extraction-config/global", headers=h, json={
            "enabled": True, "content": bad,
        })
        assert r.status_code == 400, (bad, r.text)


async def test_global_config_large_content_rejected(client, super_token):
    """L4G-02：超大 content 被 422（受 Pydantic/请求体限制保护）。"""
    kb_id = await _kb(client, super_token, "S10全局超大")
    h = {H: f"Bearer {super_token}"}
    huge = {"retrieval": {"context": {"truncate_marker": "x" * 300}}}
    r = await client.put(f"/api/v1/kb/{kb_id}/extraction-config/global", headers=h, json={
        "enabled": True, "content": huge,
    })
    assert r.status_code == 400


async def test_script_timeout_global_override(client, super_token):
    """L4G-03：脚本运行使用全局 script_timeout（短超时立即失败）。"""
    kb_id = await _kb(client, super_token, "S10全局超时")
    h = {H: f"Bearer {super_token}"}
    await client.put(f"/api/v1/kb/{kb_id}/extraction-config/global", headers=h, json={
        "enabled": True,
        "content": {"kb_tool": {"script_timeout": 1}},
    })
    r = await client.post(f"/api/v1/kb/{kb_id}/extraction-config/scripts/run", headers=h, json={
        "code": "import time\ndef run(args):\n    time.sleep(3)\n    return {}",
        "args": {},
    })
    assert r.status_code == 200, r.text
    assert r.json()["data"]["ok"] is False
    assert "超时" in r.json()["data"]["error"]


async def test_global_config_invalid_recall_mode(client, super_token):
    """L4G-04：非法类别召回模式被拒。"""
    kb_id = await _kb(client, super_token, "S10召回模式非法")
    h = {H: f"Bearer {super_token}"}
    r = await client.put(f"/api/v1/kb/{kb_id}/extraction-config/global", headers=h, json={
        "enabled": True,
        "content": {"retrieval": {"category_recall": {"mode": "bogus"}}},
    })
    assert r.status_code in (400, 422), r.text
