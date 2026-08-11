"""L4 边界异常：M30 检索服务。"""

import uuid

from app.services.indexing.retrieval import retrieval_service
from qa.fixtures.indexing_helpers import create_kb_via_api


async def test_empty_query_returns_empty(client, super_token, db_session):
    """L4M30-01：空查询返回空。"""
    kb = await create_kb_via_api(client, super_token, "S6空查询")
    assert await retrieval_service.search(db_session, uuid.UUID(kb["id"]), "") == []
    assert await retrieval_service.search(db_session, uuid.UUID(kb["id"]), "   ") == []


async def test_empty_corpus_returns_empty(client, super_token, db_session):
    """L4M30-02：无索引语料返回空。"""
    kb = await create_kb_via_api(client, super_token, "S6无语料")
    hits = await retrieval_service.search(db_session, uuid.UUID(kb["id"]), "查询内容")
    assert hits == []


async def test_api_validation_errors(client, super_token, db_session):
    """L4M30-03：API 参数校验（空 query / top_k 越界返回 422）。"""
    kb = await create_kb_via_api(client, super_token, "S6校验")
    kb_id = kb["id"]
    h = {"Authorization": f"Bearer {super_token}"}
    r1 = await client.post(f"/api/v1/kb/{kb_id}/search", headers=h, json={"query": ""})
    assert r1.status_code == 400  # 项目统一异常处理器将校验错误映射为 400
    r2 = await client.post(f"/api/v1/kb/{kb_id}/search", headers=h, json={"query": "x", "top_k": 999})
    assert r2.status_code == 400


async def test_unknown_kb_search(client, super_token, db_session):
    """L4M30-04：未知 KB 搜索被拒绝。"""
    resp = await client.post(
        f"/api/v1/kb/{uuid.uuid4()}/search",
        headers={"Authorization": f"Bearer {super_token}"},
        json={"query": "测试"},
    )
    assert resp.status_code in (400, 404, 403)
