"""L2 集成链路 + L3 功能场景：M24 索引存储底座（迁移产物 + ORM 全链路）。"""

import uuid

from sqlalchemy import select, text as sa_text

from app.models.document import Document
from app.models.indexing import DocumentChunk, KbBm25Stats, TextChunk
from qa.fixtures.indexing_helpers import (
    create_document_row,
    create_kb_via_api,
    upsert_kb_member,
)


async def test_migration_artifacts_present(db_session):
    """L2M24-01：009 迁移产物（扩展/表/索引/策略/状态列）齐备。"""
    rows = (
        await db_session.execute(
            sa_text(
                "select tablename from pg_tables where schemaname='public' "
                "and tablename in ('document_chunks','text_chunks','kb_bm25_stats')"
            )
        )
    ).scalars().all()
    assert set(rows) == {"document_chunks", "text_chunks", "kb_bm25_stats"}

    ext = (
        await db_session.execute(
            sa_text("select extversion from pg_extension where extname='vector'")
        )
    ).scalar()
    assert ext is not None and ext.startswith("0.8")

    idx = (
        await db_session.execute(
            sa_text(
                "select indexname from pg_indexes where tablename='document_chunks'"
            )
        )
    ).scalars().all()
    assert "idx_chunks_title_vec" in idx
    assert "idx_chunks_content_vec" in idx
    assert "idx_chunks_bm25_tokens" in idx
    assert "idx_chunks_kb_doc" in idx

    policies = (
        await db_session.execute(
            sa_text(
                "select count(*) from pg_policies "
                "where tablename in ('document_chunks','text_chunks','kb_bm25_stats')"
            )
        )
    ).scalar()
    assert policies == 12

    cols = (
        await db_session.execute(
            sa_text(
                "select column_name from information_schema.columns "
                "where table_name='documents' and column_name like 'index%'"
            )
        )
    ).scalars().all()
    assert set(cols) == {"index_status", "index_progress", "index_total", "index_error"}


async def test_alembic_version_head(db_session):
    """L2M24-02：测试库迁移版本为 015_global_extraction_config（当前链头）。"""
    ver = (
        await db_session.execute(
            sa_text("select version_num from alembic_version")
        )
    ).scalar()
    assert ver == "015_global_extraction_config"


async def test_orm_write_read_flow(client, super_token, db_session):
    """L3M24-03：超管上下文 ORM 写入/读取 document_chunks + text_chunks + kb_bm25_stats。"""
    kb = await create_kb_via_api(client, super_token, "S1存储集成")
    kb_id = uuid.UUID(kb["id"])
    doc_id = await create_document_row(db_session, kb_id)

    await db_session.execute(sa_text("SELECT set_config('app.is_superuser', 'true', true)"))
    chunk = DocumentChunk(
        kb_id=kb_id,
        document_id=doc_id,
        chunk_id=f"{doc_id}_p0_0",
        parent_chunk_id=f"{doc_id}_p0",
        chunk_index=0,
        hierarchy_path="1 范围",
        title="1 范围",
        level=1,
        has_table=False,
        semantic_label="text",
        source_pages=[1],
        content="本文件规定了…",
        content_for_embedding="本文件规定了…",
        parent_text="1 范围\n本文件规定了…",
        tokens=12,
        title_vector=[0.1] * 1024,
        content_vector=[0.2] * 1024,
        bm25_tokens={"规定": 1, "本文件": 1},
    )
    db_session.add(chunk)
    await db_session.flush()

    text = TextChunk(
        kb_id=kb_id,
        document_id=doc_id,
        document_chunk_id=chunk.id,
        chunk_id=chunk.chunk_id,
        content=chunk.content,
        heading=chunk.hierarchy_path,
        tokens=12,
        metadata_json={"page": 1, "has_table": False},
    )
    db_session.add(text)
    stats = KbBm25Stats(kb_id=kb_id, payload={"n_docs": 1, "total_len": 12, "doc_freq": {"规定": 1}}, version=1)
    db_session.add(stats)
    await db_session.commit()

    got = (
        await db_session.execute(
            select(DocumentChunk).where(DocumentChunk.document_id == doc_id)
        )
    ).scalar_one()
    assert got.hierarchy_path == "1 范围"
    assert got.title_vector[0] == 0.1 and len(got.content_vector) == 1024
    assert got.bm25_tokens["规定"] == 1

    got_text = (
        await db_session.execute(
            select(TextChunk).where(TextChunk.document_chunk_id == chunk.id)
        )
    ).scalar_one()
    assert got_text.metadata_json["page"] == 1
    assert got_text.heading == "1 范围"

    got_stats = (
        await db_session.execute(
            select(KbBm25Stats).where(KbBm25Stats.kb_id == kb_id)
        )
    ).scalar_one()
    assert got_stats.payload["n_docs"] == 1
    assert got_stats.version == 1


async def test_soft_delete_partial_index_contract(client, super_token, db_session):
    """L3M24-04：软删块不参与 kb+doc 部分索引可见范围。"""
    kb = await create_kb_via_api(client, super_token, "S1软删契约")
    kb_id = uuid.UUID(kb["id"])
    doc_id = await create_document_row(db_session, kb_id)
    await db_session.execute(sa_text("SELECT set_config('app.is_superuser', 'true', true)"))

    c1 = DocumentChunk(kb_id=kb_id, document_id=doc_id, chunk_id=f"{doc_id}_p0_0",
                       chunk_index=0, content="active", tokens=1)
    c2 = DocumentChunk(kb_id=kb_id, document_id=doc_id, chunk_id=f"{doc_id}_p0_1",
                       chunk_index=1, content="deleted", tokens=1)
    db_session.add_all([c1, c2])
    await db_session.commit()

    from datetime import datetime, timezone

    c2.deleted_at = datetime.now(timezone.utc)
    await db_session.commit()

    visible = (
        await db_session.execute(
            sa_text(
                "select chunk_id from document_chunks where kb_id=:kb and document_id=:doc "
                "and deleted_at is null"
            ).bindparams(kb=kb_id, doc=doc_id)
        )
    ).scalars().all()
    assert visible == [f"{doc_id}_p0_0"]


async def test_kb_effective_role_member(db_session, client, super_token):
    """L2M24-05：RLS 策略函数对有效成员返回角色。"""
    from app.models.user import User

    kb = await create_kb_via_api(client, super_token, "S1角色函数")
    kb_id = uuid.UUID(kb["id"])
    admin = (
        await db_session.execute(select(User).where(User.username == "admin"))
    ).scalar_one()
    await upsert_kb_member(db_session, kb_id, admin.id, "viewer")

    await db_session.execute(sa_text("SELECT set_config('app.is_superuser', '', true)"))
    role = (
        await db_session.execute(
            sa_text(
                "select hansondoc_kb_effective_role(cast(:kb as uuid), cast(:uid as uuid))"
            ).bindparams(kb=str(kb_id), uid=str(admin.id))
        )
    ).scalar()
    assert role == "viewer"

    # 非成员返回 NULL
    role = (
        await db_session.execute(
            sa_text(
                "select hansondoc_kb_effective_role(cast(:kb as uuid), cast(:uid as uuid))"
            ).bindparams(kb=str(kb_id), uid=str(uuid.uuid4()))
        )
    ).scalar()
    assert role is None
