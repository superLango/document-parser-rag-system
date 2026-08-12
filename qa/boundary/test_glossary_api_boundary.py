"""L4 边界：M33-S2 术语集 API。"""

import uuid

import pytest
from qa.fixtures.indexing_helpers import create_kb_via_api

from app.services.glossary import term_base_service


async def test_duplicate_name_409(client, super_token):
    """L4M33-S2-01：重复名称返回 409。"""
    kb = await create_kb_via_api(client, super_token, "S8重名")
    h = {"Authorization": f"Bearer {super_token}"}
    body = {"name": "同名术语", "source_type": "manual"}
    r1 = await client.post(f"/api/v1/kb/{kb['id']}/term-bases", headers=h, json=body)
    r2 = await client.post(f"/api/v1/kb/{kb['id']}/term-bases", headers=h, json=body)
    assert r1.status_code == 200
    assert r2.status_code == 409


async def test_invalid_source_url_rejected(client, super_token):
    """L4M33-S2-02：SSRF 高危 API 地址创建被拒。"""
    kb = await create_kb_via_api(client, super_token, "S8SSRF创建")
    resp = await client.post(
        f"/api/v1/kb/{kb['id']}/term-bases",
        headers={"Authorization": f"Bearer {super_token}"},
        json={
            "name": "危险源",
            "source_type": "api",
            "source_config": {"url": "http://127.0.0.1:8080/x"},
        },
    )
    assert resp.status_code == 400
    assert "不允许" in resp.json()["message"]


async def test_manual_sync_rejected(client, super_token, db_session):
    """L4M33-S2-03：手动术语集同步返回 400。"""
    kb = await create_kb_via_api(client, super_token, "S8手动同步")
    kb_id = kb["id"]
    r = await client.post(
        f"/api/v1/kb/{kb_id}/term-bases",
        headers={"Authorization": f"Bearer {super_token}"},
        json={"name": "手动", "source_type": "manual"},
    )
    base_id = r.json()["data"]["id"]
    resp = await client.post(
        f"/api/v1/kb/{kb_id}/term-bases/{base_id}/sync",
        headers={"Authorization": f"Bearer {super_token}"},
    )
    assert resp.status_code == 400
    assert "不支持同步" in resp.json()["message"]


async def test_import_limit(client, super_token, db_session):
    """L4M33-S2-04：导入超过 5000 条被拒。"""
    kb = await create_kb_via_api(client, super_token, "S8导入上限")
    kb_id = uuid.UUID(kb["id"])
    items = [{"term": f"词{i}"} for i in range(5001)]
    with pytest.raises(Exception, match="5000"):
        await term_base_service.create_term_base(
            db_session, kb_id, None,
            {"name": "超限", "source_type": "manual", "auto_import": True, "import_data": items},
        )


async def test_empty_name_rejected(client, super_token):
    """L4M33-S2-05：空名称创建返回 400/422。"""
    kb = await create_kb_via_api(client, super_token, "S8空名")
    resp = await client.post(
        f"/api/v1/kb/{kb['id']}/term-bases",
        headers={"Authorization": f"Bearer {super_token}"},
        json={"name": "", "source_type": "manual"},
    )
    assert resp.status_code in (400, 422)


async def test_api_test_endpoint_connect_error_400(monkeypatch, client, super_token):
    """L4M33-S2-06：API 测试连接异常转 400 而非 500。"""
    from app.services.glossary import source_api

    async def boom(config, limit=10, client=None):
        raise RuntimeError("API 请求失败（ConnectError）：connection refused")

    monkeypatch.setattr(source_api, "fetch_rows", boom)
    kb = await create_kb_via_api(client, super_token, "S8API连接失败")
    resp = await client.post(
        f"/api/v1/kb/{kb['id']}/term-bases/test-api",
        headers={"Authorization": f"Bearer {super_token}"},
        json={"url": "http://10.0.0.11/x", "method": "GET"},
    )
    assert resp.status_code == 400
    assert "API 请求失败" in resp.json()["message"]


async def test_db_test_endpoint_connect_error_400(monkeypatch, client, super_token):
    """L4M33-S2-07：DB 测试连接异常转 400 而非 500。"""
    from app.services.glossary import source_db

    async def boom(config):
        raise RuntimeError("数据库连接失败：db down")

    monkeypatch.setattr(source_db, "test_db", boom)
    kb = await create_kb_via_api(client, super_token, "S8DB连接失败")
    resp = await client.post(
        f"/api/v1/kb/{kb['id']}/term-bases/test-db",
        headers={"Authorization": f"Bearer {super_token}"},
        json={"host": "10.0.0.12", "port": 3306, "user": "u", "password": "p", "database": "d"},
    )
    assert resp.status_code == 400
    assert "数据库连接失败" in resp.json()["message"]


async def test_preview_sql_empty_400(client, super_token):
    """L4M33-S2-08：空 SQL 预览转 400 而非 500。"""
    kb = await create_kb_via_api(client, super_token, "S8空SQL")
    resp = await client.post(
        f"/api/v1/kb/{kb['id']}/term-bases/preview-sql",
        headers={"Authorization": f"Bearer {super_token}"},
        json={"host": "10.0.0.12", "port": 3306, "mode": "sql", "sql_query": ""},
    )
    assert resp.status_code == 400
    assert "SQL 不能为空" in resp.json()["message"]
