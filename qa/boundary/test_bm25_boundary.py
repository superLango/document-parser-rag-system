"""L4 边界异常：M29 BM25。"""

import uuid

from sqlalchemy import select

from app.models.indexing import KbBm25Stats
from app.services.indexing.bm25 import kb_bm25_service, tokenize_text
from qa.fixtures.indexing_helpers import create_kb_via_api


async def test_empty_corpus_scores_empty(client, super_token, db_session):
    """L4M29-01：无索引文档时查询返回空。"""
    kb = await create_kb_via_api(client, super_token, "S5空语料")
    hits = await kb_bm25_service.score_query(db_session, uuid.UUID(kb["id"]), "任何查询")
    assert hits == []


async def test_unknown_kb_scores_empty(client, super_token, db_session):
    """L4M29-02：未知 KB 查询返回空（stats 缺失防御）。"""
    hits = await kb_bm25_service.score_query(db_session, uuid.uuid4(), "查询")
    assert hits == []


def test_long_query_tokenize_bounded():
    """L4M29-03：超长查询分词不崩溃且词元有界。"""
    tokens = tokenize_text("查询词" * 20000)
    assert tokens
    assert len(tokens) < 100000


async def test_empty_query_returns_empty(client, super_token, db_session):
    """L4M29-05：空查询/纯标点查询返回空。"""
    kb = await create_kb_via_api(client, super_token, "S5空查询")
    assert await kb_bm25_service.score_query(db_session, uuid.UUID(kb["id"]), "") == []
    assert await kb_bm25_service.score_query(db_session, uuid.UUID(kb["id"]), "，。！？") == []


async def test_no_matching_token_returns_empty(client, super_token, db_session):
    """L4M29-04：查询词元在语料中无匹配时返回空。"""
    from app.services.indexing.bm25 import KBBm25Service, chunk_token_counts

    kb = await create_kb_via_api(client, super_token, "S5无匹配")
    kb_id = uuid.UUID(kb["id"])
    svc = KBBm25Service()
    await svc.add_document_stats(db_session, kb_id, [chunk_token_counts("不锈钢")])
    hits = await kb_bm25_service.score_query(db_session, kb_id, "钛合金")
    assert hits == []


async def test_remove_more_than_existing_clamps(client, super_token, db_session):
    """L4M29-06：回退超过现有统计时钳制不为负。"""
    from app.services.indexing.bm25 import KBBm25Service, chunk_token_counts

    kb = await create_kb_via_api(client, super_token, "S5钳制")
    kb_id = uuid.UUID(kb["id"])
    svc = KBBm25Service()
    await svc.add_document_stats(db_session, kb_id, [chunk_token_counts("文档 A")])
    await svc.remove_document_stats(db_session, kb_id, [chunk_token_counts("文档 A"), chunk_token_counts("多余 B")])
    stats = (
        await db_session.execute(select(KbBm25Stats).where(KbBm25Stats.kb_id == kb_id))
    ).scalar_one()
    assert stats.payload["n_docs"] == 0
    assert stats.payload["total_len"] == 0
