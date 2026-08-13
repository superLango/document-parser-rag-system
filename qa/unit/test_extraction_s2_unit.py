"""L1 单元测试：M34-S2 抽取配置服务辅助逻辑。"""

from app.services import extraction_config_service as svc


def test_script_io_registry():
    """L1M34-S2-01：脚本 IO 注册包含 post/validation 目录与工具。"""
    data = svc.script_io_registry()
    assert set(data["folders"]) == {"post", "validation"}
    for folder in ("post", "validation"):
        assert data["folders"][folder]["input"]
        assert data["folders"][folder]["output"]
        tools = data["folders"][folder]["tools"]
        assert any(t["name"] == "get_term_records" for t in tools)
        assert all("desc" in t and "usage" in t for t in tools)


def test_qs_to_dict():
    """L1M34-S2-02：QuerySource 对象与 dict 统一转 dict。"""
    assert svc._qs_to_dict({"a": 1}) == {"a": 1}

    class FakeQS:
        def model_dump(self):
            return {"label": "x", "value_field": "name"}

    assert svc._qs_to_dict(FakeQS()) == {"label": "x", "value_field": "name"}


def test_run_template_contract():
    """L1M34-S2-03：脚本运行模板包含真实 kb_tools 与 def run 调用（数据经 stdin）。"""
    from app.services.extraction import script_tools

    src = script_tools.build_script_code("def run(args): return args")
    assert "class _KbTools" in src
    assert "kb_tools = _KbTools" in src
    assert "result = run(_args)" in src
    assert 'TERM_DATA = _payload["term_data"]' in src
    assert "json.loads(sys.stdin.read())" in src


def test_script_io_registry_tools_aligned():
    """L1M34-S2-05：工具目录对齐原项目 KbScriptTools 签名。"""
    from app.services.extraction import script_tools

    tools = {t["name"]: t for t in svc._TOOL_CATALOG}
    assert set(tools) == {"get_term_records", "embed", "semantic_search", "match_record"}
    assert "params" in tools["semantic_search"]
    names = [x["name"] for x in tools["semantic_search"]["params"]]
    assert names == ["records", "query", "match_fields", "top_k", "return_fields"]
    names = [x["name"] for x in tools["match_record"]["params"]]
    assert names == ["name", "records", "match_fields", "threshold"]
    assert "usage" in tools["get_term_records"]
    assert script_tools.EMBED_MAX_TEXTS >= 1


def test_embed_token_lifecycle():
    """L1M34-S2-06：内部嵌入令牌（无状态 HMAC：签发/校验/跨 KB/过期/伪造）。"""
    import time as _time

    from app.services.extraction import script_tools

    tok = script_tools.issue_embed_token("kb-1")
    assert script_tools.validate_embed_token(tok, "kb-1") is True
    assert script_tools.validate_embed_token(tok, "kb-2") is False
    assert script_tools.validate_embed_token("", "kb-1") is False
    assert script_tools.validate_embed_token("abc.def", "kb-1") is False

    # 过期令牌：构造合法签名但时间已过期
    import hashlib
    import hmac

    from app.core.config import settings

    exp = int(_time.time()) - 10
    payload = f"kb-1:{exp}"
    sig = hmac.new(
        settings.SECRET_KEY.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256
    ).hexdigest()[:32]
    assert script_tools.validate_embed_token(f"{exp}.{sig}", "kb-1") is False


def test_kb_tools_core_in_process():
    """L1M34-S2-07：kb_tools 语义检索/匹配/术语集读取（注入假 embed）。"""
    import asyncio

    from app.services.extraction import script_tools

    ns: dict = {"TERM_DATA": {
        "检测项目": [
            {"NAME": "抗拉强度(Rm)", "FEATURE": "室温拉伸", "UNIT": "MPa"},
            {"NAME": "断后伸长率(δ5)", "FEATURE": "室温拉伸", "UNIT": "%"},
        ],
    }}
    exec(script_tools._EDIT_SIMILARITY_SRC + "\n" + script_tools._KB_TOOLS_CLASS_SRC, ns)  # noqa: S102
    KbTools = ns["_KbTools"]

    async def fake_embed(texts):
        vec = {"抗拉强度(Rm)": [1.0, 0.0], "断后伸长率(δ5)": [0.0, 1.0]}
        return [vec.get(t, [0.5, 0.5]) for t in texts]

    tools = KbTools("http://mock", "t")
    tools.embed = fake_embed

    async def run():
        rows = await tools.get_term_records("检测项目", "NAME", "FEATURE")
        assert rows == [
            {"NAME": "抗拉强度(Rm)", "FEATURE": "室温拉伸"},
            {"NAME": "断后伸长率(δ5)", "FEATURE": "室温拉伸"},
        ]
        top = await tools.semantic_search(rows, "抗拉强度(Rm)", ["NAME"], top_k=1)
        assert top[0]["NAME"] == "抗拉强度(Rm)" and top[0]["score"] > 0.9
        hit = await tools.match_record("抗拉强度(Rm)", rows, ["NAME"], threshold=0.90)
        assert hit["type"] == "vector" and hit["canonical"] == "抗拉强度(Rm)"
        # 编辑距离兜底
        hit2 = await tools.match_record("抗拉强度", rows, ["NAME"])
        assert hit2["type"] in ("exact", "edit_distance", "unverified")
        # 未知 → unverified
        hit3 = await tools.match_record("完全不存在", rows, ["NAME"], threshold=0.99)
        assert hit3["type"] == "unverified"

    asyncio.run(run())


def test_serializers_exist():
    """L1M34-S2-04：Schema/Prompt 序列化函数存在且返回关键字段。"""
    from datetime import datetime, timezone

    from app.models.extraction import SchemaTemplate

    t = SchemaTemplate(id="1", kb_id="2", name="T", description="", is_active=True, sort_order=0,
                       created_at=datetime.now(timezone.utc))
    d = svc._serialize_template(t)
    assert d["name"] == "T" and d["categories"] == []
