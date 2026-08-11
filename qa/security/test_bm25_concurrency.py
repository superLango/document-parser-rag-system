"""L5 安全/并发：M29 BM25 统计并发一致性与 KB 隔离。"""

import asyncio
import uuid

from sqlalchemy import select

from app.models.indexing import KbBm25Stats
from app.services.indexing.bm25 import KBBm25Service, chunk_token_counts
from qa.fixtures.indexing_helpers import create_kb_via_api


async def test_concurrent_stats_updates_consistent(client, super_token, db_session):
    """L5M29-01（并发）：同一 KB 并发新增 6 个文档统计，最终一致。"""
    from app.core.database import AsyncSessionLocal

    kb = await create_kb_via_api(client, super_token, "S5并发")
    kb_id = uuid.UUID(kb["id"])

    async def _add(i: int):
        async with AsyncSessionLocal() as db:
            from sqlalchemy import text as sa_text

            await db.execute(sa_text("SELECT set_config('app.is_superuser', 'true', true)"))
            svc = KBBm25Service()
            await svc.add_document_stats(
                db, kb_id, [chunk_token_counts(f"并发文档{i} 不锈钢")]
            )

    await asyncio.gather(*[_add(i) for i in range(6)])
    stats = (
        await db_session.execute(select(KbBm25Stats).where(KbBm25Stats.kb_id == kb_id))
    ).scalar_one()
    assert stats.payload["n_docs"] == 6
    assert stats.payload["doc_freq"]["不锈钢"] == 6


async def test_kb_stats_isolation(client, super_token, db_session):
    """L5M29-02：不同 KB 统计互不干扰。"""
    kb_a = await create_kb_via_api(client, super_token, "S5隔离A")
    kb_b = await create_kb_via_api(client, super_token, "S5隔离B")
    svc = KBBm25Service()
    await svc.add_document_stats(db_session, uuid.UUID(kb_a["id"]), [chunk_token_counts("A 内容")])
    await svc.add_document_stats(db_session, uuid.UUID(kb_b["id"]), [chunk_token_counts("B 内容")])
    a = (
        await db_session.execute(
            select(KbBm25Stats).where(KbBm25Stats.kb_id == uuid.UUID(kb_a["id"]))
        )
    ).scalar_one()
    b = (
        await db_session.execute(
            select(KbBm25Stats).where(KbBm25Stats.kb_id == uuid.UUID(kb_b["id"]))
        )
    ).scalar_one()
    assert a.payload["n_docs"] == 1 and b.payload["n_docs"] == 1
    assert "A 内容" not in str(b.payload) or "A" not in b.payload["doc_freq"]
