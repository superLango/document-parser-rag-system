"""覆盖率补充：M33-S2 source_api/source_db/service 分支。"""

import uuid

import httpx
import pytest

from app.services.glossary import source_api, source_db, term_base_service
from app.services.glossary.security import validate_source_host
from app.services.glossary.term_base_loader import term_base_value_loader
from app.services.glossary.term_base_service import (
    _validate_source_config,
    create_term_base,
    list_syncable_bases,
    update_term_base,
)

# ---------------- source_api ----------------

def _transport_for(status=200, payload=None, raw=None):
    async def handler(request):
        if raw is not None:
            return httpx.Response(status, content=raw)
        return httpx.Response(status, json=payload)
    return httpx.MockTransport(handler)


async def test_api_post_headers_and_errors():
    """补测：POST/headers 传递、非 JSON、4xx、超限、json_path 非数组。"""
    # POST + headers
    seen = {}

    async def handler(request):
        seen["method"] = request.method
        seen["auth"] = request.headers.get("Authorization")
        return httpx.Response(200, json={"data": [{"a": 1}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        r = await source_api.fetch_rows(
            {"url": "http://10.0.0.11/x", "method": "POST",
             "headers": {"Authorization": "Bearer t"}, "json_path": "data"},
            client=c,
        )
    assert seen["method"] == "POST" and seen["auth"] == "Bearer t"
    assert r["rows"] == [{"a": 1}]

    # 4xx
    async with httpx.AsyncClient(transport=_transport_for(500)) as c:
        with pytest.raises(RuntimeError, match="HTTP 500"):
            await source_api.fetch_rows({"url": "http://10.0.0.11/x"}, client=c)

    # 非 JSON
    async with httpx.AsyncClient(transport=_transport_for(raw=b"not json")) as c:
        with pytest.raises(RuntimeError, match="JSON"):
            await source_api.fetch_rows({"url": "http://10.0.0.11/x"}, client=c)

    # json_path 非数组
    async with httpx.AsyncClient(transport=_transport_for(payload={"x": 1})) as c:
        with pytest.raises(TypeError):
            await source_api.fetch_rows(
                {"url": "http://10.0.0.11/x", "json_path": "x"}, client=c
            )

    # 响应超限
    big = b"x" * (6 * 1024 * 1024)
    async with httpx.AsyncClient(transport=_transport_for(raw=big)) as c:
        with pytest.raises(RuntimeError, match="MB"):
            await source_api.fetch_rows({"url": "http://10.0.0.11/x"}, client=c)


async def test_api_fetch_rows_without_client():
    """补测：无注入 client 时回环地址被 SSRF 校验拒绝。"""
    with pytest.raises(ValueError):
        await source_api.fetch_rows({"url": "http://127.0.0.1:9/x"})


async def test_api_params_path_header_body_timeout():
    """G1 补测：API 源支持 path/query/header 参数、enabled 开关、POST body、timeout。"""
    import json as _json

    seen = {}

    async def handler(request):
        seen["url"] = str(request.url)
        seen["x_token"] = request.headers.get("X-Token")
        seen["auth"] = request.headers.get("Authorization")
        seen["content"] = request.content
        return httpx.Response(200, json=[{"a": 1}])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        r = await source_api.fetch_rows(
            {
                "url": "http://10.0.0.11/x/{id}",
                "method": "POST",
                "params": [
                    {"key": "id", "value": "42", "in_location": "path", "enabled": True},
                    {"key": "q", "value": "x", "in_location": "query", "enabled": True},
                    {"key": "X-Token", "value": "t", "in_location": "header", "enabled": True},
                    {"key": "off", "value": "y", "in_location": "query", "enabled": False},
                ],
                "headers": {"Authorization": "Bearer b"},
                "body": '{"k":"v"}',
                "timeout": 5,
            },
            client=c,
        )
    assert seen["url"] == "http://10.0.0.11/x/42?q=x"
    assert seen["x_token"] == "t"
    assert seen["auth"] == "Bearer b"
    assert _json.loads(seen["content"]) == {"k": "v"}
    assert r["rows"] == [{"a": 1}]


async def test_api_connect_and_timeout_wrapped():
    """补测：httpx 连接/超时异常统一转 RuntimeError（避免接口 500）。"""
    async def boom_connect(request):
        raise httpx.ConnectError("connection refused", request=request)

    async def boom_timeout(request):
        raise httpx.ReadTimeout("timed out", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(boom_connect)) as c:
        with pytest.raises(RuntimeError, match="API 请求失败"):
            await source_api.fetch_rows({"url": "http://10.0.0.11/x"}, client=c)

    async with httpx.AsyncClient(transport=httpx.MockTransport(boom_timeout)) as c:
        with pytest.raises(RuntimeError, match="连接超时"):
            await source_api.fetch_rows({"url": "http://10.0.0.11/x"}, client=c)


async def test_map_source_row_dynamic_extras_and_fallback():
    """P0 补测：外部源行保留原始字段到 extras、名称列智能回退、别名映射、external_id。"""
    from datetime import datetime, timezone

    from app.services.glossary.term_base_service import _map_source_row

    # 名称列回退（name）+ 原始字段保留 + 同义词拆分
    item = _map_source_row(
        {"name": "不锈钢", "spec": "SUS304", "synonyms": "别名1|别名2", "tags": ["a", "b"]},
        {},
    )
    assert item["term"] == "不锈钢"
    assert item["extras"]["spec"] == "SUS304"
    assert item["extras"]["name"] == "不锈钢"
    assert item["synonyms"] == ["别名1", "别名2"]
    assert item["extras"]["tags"] == ["a", "b"]

    # 别名映射到内置字段
    item2 = _map_source_row({"牌号": "S22053", "EN": "X", "id": "e1"}, {"牌号": "term_name", "EN": "english_term"})
    assert item2["term"] == "S22053"
    assert item2["english_term"] == "X"
    assert item2["extras"]["牌号"] == "S22053"
    assert item2["extras"]["external_id"] == "e1"

    # 空行跳过；无名称列时回退第一列（对齐原项目），列值全空才跳过
    assert _map_source_row({}, {}) is None
    item_fb = _map_source_row({"spec": "AA"}, {})
    assert item_fb["term"] == "AA"
    assert _map_source_row({"spec": ""}, {}) is None
    # columns 首列兜底优先于行首列
    item_c = _map_source_row({"a": "x", "spec": "AA"}, {}, [{"name": "spec", "type": "string", "label": "规格"}])
    assert item_c["term"] == "AA"

    # 显式指定术语名称列（__name_column__）
    item4 = _map_source_row({"spec": "AA-300"}, {"__name_column__": "spec"})
    assert item4["term"] == "AA-300"
    assert item4["extras"]["spec"] == "AA-300"

    # 非 JSON 类型安全
    item3 = _map_source_row({"term": "T", "ts": datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc), "d": 1.5}, {})
    assert item3["extras"]["ts"] == "2024-01-02T03:04:05+00:00"
    assert item3["extras"]["d"] == 1.5


async def test_db_json_safe_serialization():
    """P0 补测：DB 行值（datetime/Decimal/bytes/None）可 JSONB 安全存储。"""
    from datetime import date, datetime, time, timezone
    from decimal import Decimal

    from app.services.glossary.source_db import _json_safe

    assert _json_safe(None) == ""
    assert _json_safe(datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc)) == "2024-01-02T03:04:05+00:00"
    assert _json_safe(date(2024, 1, 2)) == "2024-01-02"
    assert _json_safe(time(3, 4, 5)) == "03:04:05"
    assert _json_safe(Decimal("1.5")) == 1.5
    assert _json_safe(b"abc") == "abc"
    assert _json_safe(12) == 12


# ---------------- source_db ----------------

class _FakeCursor:
    def __init__(self, desc=None, rows=None):
        self.description = desc or [("a",), ("b",)]
        self._rows = rows or [(1, "x")]
        self.executed = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, sql):
        self.executed = sql

    async def fetchall(self):
        return self._rows

    async def fetchone(self):
        return (1,)


class _FakeConn:
    def __init__(self):
        self.cursor_used = None

    def cursor(self):
        self.cursor_used = _FakeCursor()
        return self.cursor_used

    def close(self):
        pass


async def test_db_source_logic(monkeypatch):
    """补测：DB 源连接参数校验、表/SQL 模式与连接错误。"""
    # host 校验
    with pytest.raises(ValueError):
        validate_source_host("127.0.0.1")

    fake_conn = _FakeConn()

    async def fake_connect(**kwargs):
        assert kwargs["host"] == "10.0.0.12"
        assert kwargs["connect_timeout"] > 0
        assert "read_timeout" not in kwargs  # aiomysql.connect 不支持该参数
        return fake_conn

    import aiomysql

    monkeypatch.setattr(aiomysql, "connect", fake_connect)

    cfg = {
        "host": "10.0.0.12", "port": 3306, "user": "u", "password": "p",
        "database": "d", "charset": "utf8mb4", "mode": "table", "table": "t",
    }
    assert (await source_db.test_db(cfg))["ok"] is True
    assert await source_db.list_tables(cfg) == [1]  # mock 游标首列值
    r = await source_db.fetch_rows(cfg)
    assert r["rows"] == [{"a": 1, "b": "x"}]
    assert fake_conn.cursor_used.executed == "SELECT * FROM `t` LIMIT 1000"

    sql_cfg = {**cfg, "mode": "sql", "sql_query": "SELECT a FROM t"}
    await source_db.preview_sql(sql_cfg)
    assert fake_conn.cursor_used.executed.endswith("LIMIT 5")
    await source_db.fetch_rows(sql_cfg)
    assert fake_conn.cursor_used.executed.endswith("LIMIT 1000")

    # 连接失败传播（统一转 RuntimeError，避免 500）
    async def fail_connect(**kwargs):
        raise ConnectionError("db down")

    import aiomysql

    monkeypatch.setattr(aiomysql, "connect", fail_connect)
    with pytest.raises(RuntimeError, match="数据库连接失败"):
        await source_db.test_db(cfg)


# ---------------- service / loader ----------------

async def test_validate_source_config_raises_business():
    """补测：高危地址校验转业务异常。"""
    from app.core.exceptions import BusinessException

    with pytest.raises(BusinessException):
        _validate_source_config("api", {"url": "http://127.0.0.1/x"})
    with pytest.raises(BusinessException):
        _validate_source_config("db", {"host": "localhost"})


async def test_service_update_and_syncable(client, super_token, db_session):
    """补测：update 分支与 list_syncable_bases。"""

    from qa.fixtures.indexing_helpers import create_kb_via_api

    kb = await create_kb_via_api(client, super_token, "S8补测")
    kb_id = uuid.UUID(kb["id"])
    base = await create_term_base(
        db_session, kb_id, None, {"name": "补测", "source_type": "manual"}
    )
    bid = uuid.UUID(base["id"])
    # 更新各字段
    updated = await update_term_base(
        db_session, kb_id, bid,
        {"name": "补测2", "description": "d", "sync_enabled": True},
    )
    assert updated["name"] == "补测2" and updated["sync_enabled"] is True
    # 重名冲突
    await create_term_base(db_session, kb_id, None, {"name": "其他", "source_type": "manual"})
    from app.core.exceptions import BusinessException

    with pytest.raises(BusinessException):
        await update_term_base(db_session, kb_id, bid, {"name": "其他"})
    # 外部源地址校验失败（manual 类型不校验，需 api 类型）
    api_base = await create_term_base(
        db_session, kb_id, None,
        {"name": "API补测", "source_type": "api",
         "source_config": {"url": "http://10.0.0.13/x"}},
    )
    api_id = uuid.UUID(api_base["id"])
    with pytest.raises(BusinessException):
        await update_term_base(
            db_session, kb_id, api_id,
            {"source_config": {"url": "http://127.0.0.1/x"}},
        )
    # syncable 扫描
    bases = await list_syncable_bases(db_session, limit=10)
    assert bases and all(b.sync_enabled and b.status == "active" for b in bases)


async def test_term_base_loader_grouping(client, super_token, db_session):
    """补测：加载器按分组读取 active 词条。"""
    from qa.fixtures.indexing_helpers import create_kb_via_api

    from app.models.glossary import TERM_STATUS_PENDING, Term

    kb = await create_kb_via_api(client, super_token, "S8加载器")
    kb_id = uuid.UUID(kb["id"])
    base = await create_term_base(db_session, kb_id, None, {"name": "加载", "source_type": "manual"})
    bid = uuid.UUID(base["id"])
    db_session.add(Term(kb_id=kb_id, term_base_id=bid, term_name="抗拉强度", category="力学", status="active"))
    db_session.add(Term(kb_id=kb_id, term_base_id=bid, term_name="待审", category="力学", status=TERM_STATUS_PENDING))
    await db_session.commit()

    data = await term_base_value_loader.load_term_base(db_session, kb_id, bid)
    assert data is not None
    assert "力学" in data["grouped"]
    assert "抗拉强度" in data["grouped"]["力学"]["term_name"]
    assert "待审" not in str(data)  # pending 不加载
# ---------------- 补充分支 ----------------

async def test_api_get_success(monkeypatch):
    """补测：GET 成功路径（headers/params 传递）。"""
    seen = {}

    async def handler(request):
        seen["method"] = request.method
        seen["url"] = str(request.url)
        return httpx.Response(200, json=[{"k": "v"}])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        r = await source_api.fetch_rows(
            {"url": "http://10.0.0.14/x", "method": "GET",
             "headers": {"X-K": "1"},
             "params": [{"key": "q", "value": "a", "in_location": "query", "enabled": True},
                        {"key": "skip", "value": "x", "in_location": "query", "enabled": False}]},
            client=c,
        )
    assert seen["method"] == "GET"
    assert "q=a" in seen["url"] and "skip" not in seen["url"]
    assert r["rows"] == [{"k": "v"}]


async def test_loader_group_and_cache(client, super_token, db_session):
    """补测：loader group_field 分组、缓存命中、aliases、不存在返回 None。"""
    from qa.fixtures.indexing_helpers import create_kb_via_api

    from app.models.glossary import Term

    kb = await create_kb_via_api(client, super_token, "S8加载补测")
    kb_id = uuid.UUID(kb["id"])
    base = await create_term_base(db_session, kb_id, None, {"name": "分组", "source_type": "manual"})
    bid = uuid.UUID(base["id"])
    db_session.add(Term(
        kb_id=kb_id, term_base_id=bid, term_name="A",
        category="", aliases=["别名A"], extras={"FEATURE": "组1"},
    ))
    await db_session.commit()

    data = await term_base_value_loader.load_term_base(db_session, kb_id, bid, group_field="FEATURE")
    assert "组1" in data["grouped"]
    assert "别名A" in data["grouped"]["组1"]["aliases"]

    # 缓存命中（第二次直接返回）
    again = await term_base_value_loader.load_term_base(db_session, kb_id, bid, group_field="FEATURE")
    assert again is data

    # 不存在的术语集
    assert await term_base_value_loader.load_term_base(db_session, kb_id, uuid.uuid4()) is None


async def test_service_validation_and_import_branches(client, super_token, db_session):
    """补测：create 校验分支、导入字段分支、sync 错误转业务异常。"""
    from qa.fixtures.indexing_helpers import create_kb_via_api

    from app.core.exceptions import BusinessException

    kb = await create_kb_via_api(client, super_token, "S8校验补测")
    kb_id = uuid.UUID(kb["id"])

    # 空名 / 超长名
    with pytest.raises(BusinessException):
        await create_term_base(db_session, kb_id, None, {"name": " ", "source_type": "manual"})
    with pytest.raises(BusinessException):
        await create_term_base(db_session, kb_id, None, {"name": "x" * 129, "source_type": "manual"})
    # 非法 source_type
    with pytest.raises(BusinessException):
        await create_term_base(db_session, kb_id, None, {"name": "x", "source_type": "ftp"})

    # 导入分支：synonyms/aliases/extras + 超长
    base = await create_term_base(
        db_session, kb_id, None,
        {"name": "导入补测", "source_type": "manual", "auto_import": True,
         "import_data": [
             {"term": "T1", "synonyms": ["s1", "s2"], "aliases": ["a1"],
              "extras": {"g": "g1"}, "standard_name": "S1", "english_term": "E1",
              "category": "C", "standard_number": "GB", "definition": "D"},
             {"term": "T1", "synonyms": ["s3"]},  # 幂等更新
             {"term": "", "definition": "x"},  # 空名跳过
         ]},
    )
    assert base["term_count"] == 1

    # sync 错误转业务异常（API 源 fetch 抛 RuntimeError）
    api_base = await create_term_base(
        db_session, kb_id, None,
        {"name": "同步失败", "source_type": "api",
         "source_config": {"url": "http://10.0.0.15/x"}},
    )
    from app.services.glossary import source_api

    async def _fail(cfg, limit=1000, client=None):
        raise RuntimeError("上游挂了")

    orig = source_api.fetch_rows
    source_api.fetch_rows = _fail
    try:
        with pytest.raises(BusinessException, match="上游挂了"):
            await term_base_service.sync_term_base(
                db_session, kb_id, uuid.UUID(api_base["id"])
            )
    finally:
        source_api.fetch_rows = orig
