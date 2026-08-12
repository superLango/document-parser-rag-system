"""L2 集成：M33-S1 术语集迁移产物与 ORM 读写。"""

import uuid

from qa.fixtures.indexing_helpers import create_kb_via_api
from sqlalchemy import select
from sqlalchemy import text as sa_text

from app.models.glossary import Term, TermBase


async def test_migration_artifacts(client, super_token, db_session):
    """L2M33-S1-01：迁移产物（表/索引/RLS 策略）齐备。"""
    rows = (await db_session.execute(sa_text(
        "select tablename from pg_tables where schemaname='public' "
        "and tablename in ('term_bases','terms')"
    ))).scalars().all()
    assert set(rows) == {"term_bases", "terms"}
    idx = (await db_session.execute(sa_text(
        "select indexname from pg_indexes where tablename='term_bases'"
    ))).scalars().all()
    assert "uq_term_bases_kb_name" in idx
    policies = (await db_session.execute(sa_text(
        "select count(*) from pg_policies where tablename in ('term_bases','terms')"
    ))).scalar()
    assert policies == 8


async def test_orm_write_read_hard_delete_recreate(client, super_token, db_session):
    """L2M33-S1-02：ORM 写入/读取；硬删后允许重建同名术语集。"""
    kb = await create_kb_via_api(client, super_token, "S8模型")
    kb_id = uuid.UUID(kb["id"])
    await db_session.execute(sa_text("SELECT set_config('app.is_superuser', 'true', true)"))

    base = TermBase(kb_id=kb_id, name="材料术语", description="d",
                    source_type="manual", columns=[{"name": "term", "type": "string"}])
    db_session.add(base)
    await db_session.flush()
    t = Term(kb_id=kb_id, term_base_id=base.id, term_name="抗拉强度",
             standard_name="抗拉强度", english_term="Tensile strength",
             category="力学性能")
    db_session.add(t)
    await db_session.commit()

    got = (await db_session.execute(select(Term).where(Term.term_base_id == base.id))).scalar_one()
    assert got.term_name == "抗拉强度"
    assert got.status == "active"

    # 硬删后重建同名（FK CASCADE 删除词条）
    await db_session.delete(base)
    await db_session.commit()
    base2 = TermBase(kb_id=kb_id, name="材料术语")
    db_session.add(base2)
    await db_session.commit()
    got2 = (
        await db_session.execute(
            select(TermBase).where(
                TermBase.kb_id == kb_id,
                TermBase.name == "材料术语",
                TermBase.deleted_at.is_(None),
            )
        )
    ).scalar_one()
    assert got2.id != base.id
