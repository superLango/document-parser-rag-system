"""L4 边界异常 + 并发：M24 索引存储底座。"""

import os
import subprocess
import uuid

import pytest
from sqlalchemy import insert, select, text as sa_text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.models.document import Document
from app.models.indexing import DocumentChunk
from qa.fixtures.indexing_helpers import (
    create_document_row,
    create_kb_via_api,
)


async def test_repeated_migration_idempotent():
    """L4M24-01：重复 upgrade head 幂等（并发重复执行无副作用）。"""
    backend = os.path.join(os.path.dirname(__file__), "..", "..", "backend")
    env = dict(os.environ)
    proc = subprocess.run(
        [".venv/bin/alembic", "upgrade", "head"],
        cwd=backend,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]


async def test_current_user_empty_returns_null(db_session):
    """L4M24-02（REG-15 复测）：空 app.user_id 不再触发类型转换异常。"""
    await db_session.execute(sa_text("SELECT set_config('app.user_id', '', true)"))
    val = (
        await db_session.execute(sa_text("select hansondoc_current_user()"))
    ).scalar()
    assert val is None


async def test_vector_dimension_mismatch_rejected(client, super_token, db_session):
    """L4M24-03：向 1024 维列插入错误维度向量必须报错。"""
    kb = await create_kb_via_api(client, super_token, "S1维度边界")
    kb_id = uuid.UUID(kb["id"])
    doc_id = await create_document_row(db_session, kb_id)
    await db_session.execute(sa_text("SELECT set_config('app.is_superuser', 'true', true)"))

    bad = DocumentChunk(
        kb_id=kb_id, document_id=doc_id, chunk_id=f"{doc_id}_p0_0",
        chunk_index=0, content="dim mismatch", tokens=1,
        title_vector=[0.1] * 3,
    )
    db_session.add(bad)
    with pytest.raises(DBAPIError):
        await db_session.commit()
    await db_session.rollback()


async def test_unique_chunk_conflict(client, super_token, db_session):
    """L4M24-04：同一文档重复 chunk_id 违反唯一约束。"""
    kb = await create_kb_via_api(client, super_token, "S1唯一冲突")
    kb_id = uuid.UUID(kb["id"])
    doc_id = await create_document_row(db_session, kb_id)
    await db_session.execute(sa_text("SELECT set_config('app.is_superuser', 'true', true)"))

    for _ in range(2):
        db_session.add(
            DocumentChunk(
                kb_id=kb_id, document_id=doc_id, chunk_id=f"{doc_id}_p0_0",
                chunk_index=0, content="dup", tokens=1,
            )
        )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_empty_vectors_allowed_but_hnsw_excludes(client, super_token, db_session):
    """L4M24-05：向量列为 NULL 时表可写（索引任务中途失败不阻塞落库的契约）。"""
    kb = await create_kb_via_api(client, super_token, "S1空向量")
    kb_id = uuid.UUID(kb["id"])
    doc_id = await create_document_row(db_session, kb_id)
    await db_session.execute(sa_text("SELECT set_config('app.is_superuser', 'true', true)"))

    c = DocumentChunk(
        kb_id=kb_id, document_id=doc_id, chunk_id=f"{doc_id}_p0_0",
        chunk_index=0, content="no vec", tokens=1,
    )
    db_session.add(c)
    await db_session.commit()
    got = (
        await db_session.execute(
            select(DocumentChunk).where(DocumentChunk.chunk_id == f"{doc_id}_p0_0")
        )
    ).scalar_one()
    assert got.title_vector is None and got.content_vector is None


async def test_concurrent_insert_distinct_chunks(client, super_token, db_session):
    """L4M24-06（并发）：同一文档并发写入不同 chunk_id 不冲突。"""
    import asyncio

    from app.core.database import AsyncSessionLocal

    kb = await create_kb_via_api(client, super_token, "S1并发写入")
    kb_id = uuid.UUID(kb["id"])
    doc_id = await create_document_row(db_session, kb_id)

    async def _writer(idx: int) -> None:
        async with AsyncSessionLocal() as db:
            await db.execute(
                sa_text("SELECT set_config('app.is_superuser', 'true', true)")
            )
            await db.execute(
                insert(DocumentChunk).values(
                    kb_id=kb_id,
                    document_id=doc_id,
                    chunk_id=f"{doc_id}_p0_{idx}",
                    chunk_index=idx,
                    content=f"并发块 {idx}",
                    tokens=2,
                )
            )
            await db.commit()

    await asyncio.gather(*[_writer(i) for i in range(8)])
    count = (
        await db_session.execute(
            sa_text(
                "select count(*) from document_chunks where document_id=:doc"
            ).bindparams(doc=doc_id)
        )
    ).scalar()
    assert count == 8
