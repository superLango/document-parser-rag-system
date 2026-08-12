"""L4 边界：M33-S1 术语集存储。"""

import uuid

import pytest
from sqlalchemy import text as sa_text
from sqlalchemy.exc import IntegrityError

from app.models.glossary import TermBase
from qa.fixtures.indexing_helpers import create_kb_via_api


async def test_duplicate_name_rejected(client, super_token, db_session):
    """L4M33-S1-01：未软删的同名词条违反部分唯一索引。"""
    kb = await create_kb_via_api(client, super_token, "S8唯一")
    kb_id = uuid.UUID(kb["id"])
    await db_session.execute(sa_text("SELECT set_config('app.is_superuser', 'true', true)"))
    db_session.add(TermBase(kb_id=kb_id, name="唯一术语"))
    await db_session.commit()
    db_session.add(TermBase(kb_id=kb_id, name="唯一术语"))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_cross_kb_same_name_allowed(client, super_token, db_session):
    """L4M33-S1-02：不同 KB 允许同名术语集（唯一索引含 kb_id）。"""
    kb_a = await create_kb_via_api(client, super_token, "S8隔离A")
    kb_b = await create_kb_via_api(client, super_token, "S8隔离B")
    await db_session.execute(sa_text("SELECT set_config('app.is_superuser', 'true', true)"))
    db_session.add(TermBase(kb_id=uuid.UUID(kb_a["id"]), name="同名"))
    db_session.add(TermBase(kb_id=uuid.UUID(kb_b["id"]), name="同名"))
    await db_session.commit()
    assert True


async def test_term_duplicate_within_base(client, super_token, db_session):
    """L4M33-S1-03：同库同术语集重复术语名违反唯一索引。"""
    kb = await create_kb_via_api(client, super_token, "S8词条唯一")
    kb_id = uuid.UUID(kb["id"])
    await db_session.execute(sa_text("SELECT set_config('app.is_superuser', 'true', true)"))
    base = TermBase(kb_id=kb_id, name="词条集")
    db_session.add(base)
    await db_session.flush()
    from app.models.glossary import Term

    db_session.add(Term(kb_id=kb_id, term_base_id=base.id, term_name="重复词"))
    db_session.add(Term(kb_id=kb_id, term_base_id=base.id, term_name="重复词"))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()
