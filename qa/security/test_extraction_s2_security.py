"""L5 安全：M34-S2 抽取配置 API 权限与隔离。"""

import uuid

from qa.fixtures.indexing_helpers import create_kb_via_api

H = "Authorization"


async def _mk_user(client, super_token, prefix):
    username = f"{prefix}_{uuid.uuid4().hex[:8]}"
    r = await client.post("/api/v1/users", headers={H: f"Bearer {super_token}"},
                          json={"username": username, "password": "Test@1234", "role_codes": ["member"]})
    assert r.status_code == 200, r.text
    return username


async def _login(client, username):
    r = await client.post("/api/v1/auth/login", json={"username": username, "password": "Test@1234"})
    assert r.status_code == 200
    return r.json()["data"]["access_token"]


async def _invite(client, owner_token, kb_id, username, role):
    inv = (await client.post(
        f"/api/v1/kb/{kb_id}/invitations", headers={H: f"Bearer {owner_token}"},
        json={"username": username, "role": role},
    )).json()["data"]
    token = await _login(client, username)
    await client.post(f"/api/v1/kb/invitations/{inv['token']}/accept", headers={H: f"Bearer {token}"})
    return token


async def test_viewer_readonly_editor_write(client, super_token):
    """L5M34-S2-01：viewer 只读，editor 可写（四类资源）。"""
    owner = await _mk_user(client, super_token, "s10own")
    viewer = await _mk_user(client, super_token, "s10view")
    editor = await _mk_user(client, super_token, "s10edit")
    owner_token = await _login(client, owner)
    kb = (await client.post("/api/v1/kb", headers={H: f"Bearer {owner_token}"},
                            json={"name": "S10权限", "domain_code": "general"})).json()["data"]
    viewer_token = await _invite(client, owner_token, kb["id"], viewer, "viewer")
    editor_token = await _invite(client, owner_token, kb["id"], editor, "editor")

    # viewer 可读
    r = await client.get(f"/api/v1/kb/{kb['id']}/schema-templates", headers={H: f"Bearer {viewer_token}"})
    assert r.status_code == 200
    # viewer 写全部拒绝
    for method, path, body in (
        ("post", "/schema-templates", {"name": "越权"}),
        ("post", "/extraction-config/prompts", {"name": "越权", "scope": "simple"}),
        ("post", "/extraction-config/rule-groups", {"schema_template_id": str(uuid.uuid4())}),
        ("post", "/extraction-config/scripts", {"folder": "post", "name": "x"}),
    ):
        resp = await client.request(method, f"/api/v1/kb/{kb['id']}{path}", headers={H: f"Bearer {viewer_token}"}, json=body)
        assert resp.status_code in (400, 403), (method, path, resp.status_code)

    # editor 可写
    r = await client.post(f"/api/v1/kb/{kb['id']}/schema-templates", headers={H: f"Bearer {editor_token}"},
                          json={"name": "编辑建"})
    assert r.status_code == 200


async def test_outsider_403(client, super_token):
    """L5M34-S2-02：非成员全部拒绝。"""
    out = await _mk_user(client, super_token, "s10out")
    out_token = await _login(client, out)
    kb = await create_kb_via_api(client, super_token, "S10非成员")
    r = await client.get(f"/api/v1/kb/{kb['id']}/schema-templates", headers={H: f"Bearer {out_token}"})
    assert r.status_code == 403


async def test_cross_kb_isolation(client, super_token):
    """L5M34-S2-03：A 成员看不到 B 的 Schema/Prompt/脚本。"""
    owner = await _mk_user(client, super_token, "s10iso")
    owner_token = await _login(client, owner)
    kb_a = (await client.post("/api/v1/kb", headers={H: f"Bearer {owner_token}"},
                              json={"name": "S10隔离A", "domain_code": "general"})).json()["data"]
    kb_b = await create_kb_via_api(client, super_token, "S10隔离B")
    h = {H: f"Bearer {super_token}"}
    await client.post(f"/api/v1/kb/{kb_b}/schema-templates", headers=h, json={"name": "B模板"})
    await client.post(f"/api/v1/kb/{kb_b}/extraction-config/scripts", headers=h,
                      json={"folder": "post", "name": "B脚本"})
    r = await client.get(f"/api/v1/kb/{kb_a['id']}/schema-templates", headers={H: f"Bearer {owner_token}"})
    assert r.status_code == 200
    assert r.json()["data"]["items"] == []


async def test_script_run_allowed_for_viewer(client, super_token):
    """L5M34-S2-04：脚本试运行允许 KB 任意成员（对齐原项目）。"""
    owner = await _mk_user(client, super_token, "s10run")
    viewer = await _mk_user(client, super_token, "s10runv")
    owner_token = await _login(client, owner)
    kb = (await client.post("/api/v1/kb", headers={H: f"Bearer {owner_token}"},
                            json={"name": "S10运行", "domain_code": "general"})).json()["data"]
    viewer_token = await _invite(client, owner_token, kb["id"], viewer, "viewer")
    r = await client.post(f"/api/v1/kb/{kb['id']}/extraction-config/scripts/run",
                          headers={H: f"Bearer {viewer_token}"},
                          json={"code": "def run(args): return {'ok': 1}"})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["ok"] is True


async def test_script_embed_token_guard(client, super_token, monkeypatch):
    """L5M34-S2-05：内部嵌入端点令牌防护（无效/跨KB/过期/超限/正常）。"""
    import hashlib
    import hmac
    import time

    from app.core.config import settings
    from app.services.extraction import script_tools

    kb = await create_kb_via_api(client, super_token, "S10嵌入令牌")
    kb_id = kb["id"]

    # 正常路径：注入桩，避免测试环境加载嵌入模型
    async def fake_embed(texts):
        return [[0.1]] * len(texts)

    monkeypatch.setattr(script_tools, "_cache_embed", fake_embed)

    valid = script_tools.issue_embed_token(kb_id)
    r = await client.post(f"/api/v1/kb/{kb_id}/extraction-config/script-embed",
                          json={"token": valid, "texts": ["抗拉强度"]})
    assert r.status_code == 200, r.text
    assert len(r.json()["vectors"]) == 1

    # 无/伪造令牌
    for bad in ("", "abc.def", valid[::-1]):
        r = await client.post(f"/api/v1/kb/{kb_id}/extraction-config/script-embed",
                              json={"token": bad, "texts": ["x"]})
        assert r.status_code == 403, (bad, r.status_code)

    # 跨 KB：A 的令牌不能访问 B
    kb_b = await create_kb_via_api(client, super_token, "S10嵌入令牌B")
    token_a = script_tools.issue_embed_token(kb_id)
    r = await client.post(f"/api/v1/kb/{kb_b['id']}/extraction-config/script-embed",
                          json={"token": token_a, "texts": ["x"]})
    assert r.status_code == 403

    # 过期令牌：合法签名但时间已过期
    exp = int(time.time()) - 10
    payload = f"{kb_id}:{exp}"
    sig = hmac.new(settings.SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()[:32]
    r = await client.post(f"/api/v1/kb/{kb_id}/extraction-config/script-embed",
                          json={"token": f"{exp}.{sig}", "texts": ["x"]})
    assert r.status_code == 403

    # 超过单次文本上限 → 400（在调用嵌入前拦截）
    token = script_tools.issue_embed_token(kb_id)
    r = await client.post(f"/api/v1/kb/{kb_id}/extraction-config/script-embed",
                          json={"token": token, "texts": ["x"] * (script_tools.EMBED_MAX_TEXTS + 1)})
    assert r.status_code == 400, r.text
