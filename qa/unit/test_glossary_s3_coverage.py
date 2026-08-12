"""M33-S3 覆盖率补充：term_service 分支。"""

import uuid

import pytest
from sqlalchemy import text as sa_text

from app.core.exceptions import BusinessException
from app.services.glossary import term_service
from app.services.glossary.term_base_service import create_term_base
from qa.fixtures.indexing_helpers import create_kb_via_api


async def test_list_terms_filters_and_empty(client, super_token, db_session):
    """补测：术语过滤分支（术语集/状态/无数据）。"""
    kb = await create_kb_via_api(client, super_token, "S8过滤补测")
    kb_id = uuid.UUID(kb["id"])
    base = await create_term_base(db_session, kb_id, None, {"name": "过滤集", "source_type": "manual"})
    bid = uuid.UUID(base["id"])
    await term_service.create_term(db_session, kb_id, None, {"term": "A", "term_base_id": base["id"], "category": "C1"})
    await term_service.create_term(db_session, kb_id, None, {"term": "B", "term_base_id": base["id"], "category": "C2"})

    items, total = await term_service.list_terms(db_session, kb_id, 1, 10, term_base_id=bid)
    assert total == 2
    items, total = await term_service.list_terms(db_session, kb_id, 1, 10, term_base_id=bid, status="active")
    assert total == 2
    items, total = await term_service.list_terms(db_session, kb_id, 1, 10, status="rejected")
    assert total == 0
    items, total = await term_service.list_terms(db_session, kb_id, 1, 10, category="C1")
    assert total == 1
    items, total = await term_service.list_terms(db_session, kb_id, 1, 10, keyword="B")
    assert total == 1


async def test_get_term_detail_not_found(client, super_token, db_session):
    """补测：未知术语详情 404。"""
    kb = await create_kb_via_api(client, super_token, "S8术语404")
    with pytest.raises(BusinessException):
        await term_service.get_term_detail(db_session, uuid.UUID(kb["id"]), uuid.uuid4())


async def test_create_term_validation_branches(client, super_token, db_session):
    """补测：create 空名/超长/未知术语集。"""
    kb = await create_kb_via_api(client, super_token, "S8创建校验")
    kb_id = uuid.UUID(kb["id"])
    with pytest.raises(BusinessException):
        await term_service.create_term(db_session, kb_id, None, {"term": " "})
    with pytest.raises(BusinessException):
        await term_service.create_term(db_session, kb_id, None, {"term": "x" * 300})
    with pytest.raises(BusinessException):
        await term_service.create_term(db_session, kb_id, None, {"term": "x", "term_base_id": str(uuid.uuid4())})


async def test_update_term_all_fields_and_conflict(client, super_token, db_session):
    """补测：update 各字段与改名冲突。"""
    kb = await create_kb_via_api(client, super_token, "S8更新补测")
    kb_id = uuid.UUID(kb["id"])
    base = await create_term_base(db_session, kb_id, None, {"name": "更新集", "source_type": "manual"})
    t1 = await term_service.create_term(db_session, kb_id, None, {"term": "T1", "term_base_id": base["id"]})
    t2 = await term_service.create_term(db_session, kb_id, None, {"term": "T2", "term_base_id": base["id"]})
    updated = await term_service.update_term(
        db_session, kb_id, uuid.UUID(t1["id"]),
        {"term": "T1改", "standard_name": "S", "english_term": "E",
         "definition": "D", "category": "C", "standard_number": "GB",
         "synonyms": ["s"], "aliases": ["a"], "extras": {"k": "v"}},
    )
    assert updated["term_name"] == "T1改" and updated["synonyms"] == ["s"]
    # 改名撞 T2
    with pytest.raises(BusinessException):
        await term_service.update_term(db_session, kb_id, uuid.UUID(t1["id"]), {"term": "T2"})
    # 空名
    with pytest.raises(BusinessException):
        await term_service.update_term(db_session, kb_id, uuid.UUID(t1["id"]), {"term": " "})


async def test_review_reject_and_delete(client, super_token, db_session):
    """补测：reject 审核与删除。"""
    kb = await create_kb_via_api(client, super_token, "S8审核补测")
    kb_id = uuid.UUID(kb["id"])
    base = await create_term_base(db_session, kb_id, None, {"name": "审核集", "source_type": "manual"})
    t = await term_service.create_term(db_session, kb_id, None, {"term": "T", "term_base_id": base["id"]})
    tid = uuid.UUID(t["id"])
    await db_session.execute(sa_text("update terms set status='pending' where id=:id").bindparams(id=tid))
    await db_session.commit()
    from app.models.user import User
    from sqlalchemy import select

    reviewer = (await db_session.execute(select(User.id).where(User.username == "admin"))).scalar_one()
    rejected = await term_service.review_term(db_session, kb_id, tid, "reject", reviewer)
    assert rejected["status"] == "rejected"
    with pytest.raises(BusinessException):
        await term_service.review_term(db_session, kb_id, tid, "banana", reviewer)
    await term_service.delete_term(db_session, kb_id, tid)
    with pytest.raises(BusinessException):
        await term_service.get_term(db_session, kb_id, tid)


async def test_export_empty_kb(client, super_token, db_session):
    """补测：空 KB 导出仅表头。"""
    kb = await create_kb_via_api(client, super_token, "S8空导出")
    content = await term_service.export_terms(db_session, uuid.UUID(kb["id"]))
    text = content.decode("utf-8")
    assert text.startswith("\ufeff")
    assert "术语,标准名" in text
    assert text.count("\n") == 1
