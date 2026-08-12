"""L2 集成 + L3 功能：M33-S2 术语集 API 与外部源同步。"""

import uuid

import httpx
from qa.fixtures.indexing_helpers import create_kb_via_api
from sqlalchemy import select
from sqlalchemy import text as sa_text

from app.models.glossary import TERM_STATUS_ACTIVE, Term, TermBase
from app.services.glossary import term_base_service


async def _create_manual(client, super_token, kb_id, name="材料术语", items=None):
    resp = await client.post(
        f"/api/v1/kb/{kb_id}/term-bases",
        headers={"Authorization": f"Bearer {super_token}"},
        json={
            "name": name,
            "description": "测试术语集",
            "source_type": "manual",
            "auto_import": bool(items),
            "import_data": items or [],
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


async def test_manual_crud_flow(client, super_token, db_session):
    """L3M33-S2-01：手动术语集创建→列表→详情→更新→删除（词条级联软删）。"""
    kb = await create_kb_via_api(client, super_token, "S8CRUD")
    kb_id = kb["id"]
    data = await _create_manual(
        client, super_token, kb_id,
        items=[{"term": "抗拉强度", "standard_name": "抗拉强度", "category": "力学性能"}],
    )
    assert data["term_count"] == 1
    base_id = data["id"]

    listed = await client.get(
        f"/api/v1/kb/{kb_id}/term-bases",
        headers={"Authorization": f"Bearer {super_token}"},
    )
    assert listed.status_code == 200
    assert any(i["id"] == base_id for i in listed.json()["data"]["items"])

    detail = await client.get(
        f"/api/v1/kb/{kb_id}/term-bases/{base_id}",
        headers={"Authorization": f"Bearer {super_token}"},
    )
    assert detail.json()["data"]["term_count"] == 1

    upd = await client.put(
        f"/api/v1/kb/{kb_id}/term-bases/{base_id}",
        headers={"Authorization": f"Bearer {super_token}"},
        json={"description": "更新描述"},
    )
    assert upd.status_code == 200
    assert upd.json()["data"]["description"] == "更新描述"

    # 词条落库为 active
    rows = (await db_session.execute(
        sa_text("select term_name, status from terms where term_base_id=:b").bindparams(b=uuid.UUID(base_id))
    )).all()
    assert rows == [("抗拉强度", "active")]

    deleted = await client.delete(
        f"/api/v1/kb/{kb_id}/term-bases/{base_id}",
        headers={"Authorization": f"Bearer {super_token}"},
    )
    assert deleted.status_code == 200
    gone = await client.get(
        f"/api/v1/kb/{kb_id}/term-bases/{base_id}",
        headers={"Authorization": f"Bearer {super_token}"},
    )
    assert gone.status_code == 400
    remain = (await db_session.execute(
        sa_text("select count(*) from terms where term_base_id=:b").bindparams(b=uuid.UUID(base_id))
    )).scalar()
    assert remain == 0  # 硬删：词条由 FK CASCADE 级联删除


async def test_api_source_sync_with_mock(client, super_token, db_session):
    """L2M33-S2-02：API 源术语集创建→同步→词条 pending→幂等重同步。"""
    kb = await create_kb_via_api(client, super_token, "S8API源")
    kb_id = kb["id"]
    resp = await client.post(
        f"/api/v1/kb/{kb_id}/term-bases",
        headers={"Authorization": f"Bearer {super_token}"},
        json={
            "name": "外部标准术语",
            "source_type": "api",
            "source_config": {
                "url": "http://10.0.0.9/terms",
                "method": "GET",
                "json_path": "data.list",
                "password": "sekret",
            },
            "column_aliases": {"name": "term", "desc": "definition"},
            "sync_enabled": True,
        },
    )
    assert resp.status_code == 200, resp.text
    base_id = resp.json()["data"]["id"]

    async def _fake_fetch(cfg, limit=1000, client=None):
        return {
            "rows": [
                {"name": "晶间腐蚀", "desc": "沿晶界腐蚀", "id": "e1"},
                {"name": "点蚀", "desc": "局部腐蚀", "id": "e2"},
            ],
            "columns": [{"name": "name", "type": "string", "label": "name"}],
            "total": 2,
        }

    from app.services.glossary import source_api

    orig = source_api.fetch_rows
    source_api.fetch_rows = _fake_fetch
    try:
        async with httpx.AsyncClient() as mock_client:
            result = await term_base_service.sync_term_base(
                db_session, uuid.UUID(kb_id), uuid.UUID(base_id), api_client=mock_client
            )
    finally:
        source_api.fetch_rows = orig
    assert result["imported"] == 2

    rows = (await db_session.execute(
        sa_text("select term_name, definition, status from terms where term_base_id=:b order by term_name").bindparams(b=uuid.UUID(base_id))
    )).all()
    assert rows == [("晶间腐蚀", "沿晶界腐蚀", TERM_STATUS_ACTIVE), ("点蚀", "局部腐蚀", TERM_STATUS_ACTIVE)]

    base = (await db_session.execute(select(TermBase).where(TermBase.id == uuid.UUID(base_id)))).scalar_one()
    assert base.last_synced_at is not None

    # 幂等：再同步不重复
    source_api.fetch_rows = _fake_fetch
    try:
        async with httpx.AsyncClient() as mock_client:
            await term_base_service.sync_term_base(
                db_session, uuid.UUID(kb_id), uuid.UUID(base_id), api_client=mock_client
            )
    finally:
        source_api.fetch_rows = orig
    count = (await db_session.execute(
        sa_text("select count(*) from terms where term_base_id=:b and deleted_at is null").bindparams(b=uuid.UUID(base_id))
    )).scalar()
    assert count == 2


async def test_credentials_masked_in_response(client, super_token):
    """L3M33-S2-03：API 响应不回显凭据明文/密文（掩码）。"""
    kb = await create_kb_via_api(client, super_token, "S8掩码")
    kb_id = kb["id"]
    resp = await client.post(
        f"/api/v1/kb/{kb_id}/term-bases",
        headers={"Authorization": f"Bearer {super_token}"},
        json={
            "name": "掩码术语",
            "source_type": "api",
            "source_config": {
                "url": "http://10.0.0.10/x",
                "headers": {"Authorization": "Bearer tok123"},
                "password": "pw123",
            },
        },
    )
    base_id = resp.json()["data"]["id"]
    resp = await client.get(
        f"/api/v1/kb/{kb_id}/term-bases/{base_id}",
        headers={"Authorization": f"Bearer {super_token}"},
    )
    assert resp.status_code == 200, resp.text
    detail = resp.json()["data"]
    cfg = detail["source_config"]
    assert cfg["password"] == "******"
    assert cfg["headers"]["Authorization"] == "******"
    assert "pw123" not in str(detail)


async def test_sync_keeps_dynamic_extras(monkeypatch, client, super_token, db_session):
    """P0 集成：外部源同步保留动态列到 extras，名称列回退生效，外部词条 pending。"""
    from app.services.glossary import source_api

    kb = await create_kb_via_api(client, super_token, "S8动态列")
    kb_id = uuid.UUID(kb["id"])
    base = await term_base_service.create_term_base(
        db_session, kb_id, None,
        {
            "name": "动态列",
            "source_type": "api",
            "source_config": {"url": "http://10.0.0.99/x"},
            "columns": [
                {"name": "term_name", "type": "string", "label": "术语"},
                {"name": "spec", "type": "string", "label": "spec"},
            ],
        },
    )
    base_id = uuid.UUID(base["id"])

    async def fake_fetch(config, limit=1000, client=None):
        return {
            "rows": [
                {"term_name": "S22053", "spec": "AA-100"},
                {"name": "回退术语", "spec": "BB-200"},
            ],
            "columns": [
                {"name": "term_name", "type": "string", "label": "术语"},
                {"name": "spec", "type": "string", "label": "spec"},
            ],
            "total": 2,
        }

    monkeypatch.setattr(source_api, "fetch_rows", fake_fetch)
    result = await term_base_service.sync_term_base(db_session, kb_id, base_id, None)
    assert result["imported"] == 2
    assert result["total"] == 2
    assert result["skipped"] == 0

    rows = (
        await db_session.execute(
            select(Term).where(Term.term_base_id == base_id)
        )
    ).scalars().all()
    by_name = {t.term_name: t for t in rows}
    assert by_name["S22053"].extras["spec"] == "AA-100"
    assert by_name["回退术语"].extras["spec"] == "BB-200"
    assert all(t.status == TERM_STATUS_ACTIVE for t in rows)

    # 再次同步（upsert）：extras 动态值更新，不新增
    async def fake_fetch2(config, limit=1000, client=None):
        return {
            "rows": [
                {"term_name": "S22053", "spec": "AA-200"},
                {"name": "回退术语", "spec": "BB-200"},
            ],
            "columns": [],
            "total": 2,
        }

    monkeypatch.setattr(source_api, "fetch_rows", fake_fetch2)
    result2 = await term_base_service.sync_term_base(db_session, kb_id, base_id, None)
    assert result2["imported"] == 2
    assert result2["skipped"] == 0
    rows2 = (
        await db_session.execute(
            select(Term).where(Term.term_base_id == base_id)
        )
    ).scalars().all()
    active_rows2 = [t for t in rows2 if t.deleted_at is None]
    assert len(active_rows2) == 2
    by_name2 = {t.term_name: t for t in active_rows2}
    assert by_name2["S22053"].extras["spec"] == "AA-200"


async def test_batch_save_manual_terms(client, super_token, db_session):
    """G3 集成：manual 术语集批量保存（新增/更新/删除一次提交）。"""

    kb = await create_kb_via_api(client, super_token, "S8批量保存")
    kb_id = kb["id"]
    base = await _create_manual(client, super_token, kb_id, name="批量保存")
    base_id = base["id"]

    # 新增 2 条
    r1 = await client.put(
        f"/api/v1/kb/{kb_id}/term-bases/{base_id}/terms/batch",
        headers={"Authorization": f"Bearer {super_token}"},
        json={
            "items": [
                {"term": "抗拉强度", "english_term": "Rm", "category": "力学性能"},
                {"term": "屈服强度", "english_term": "Re", "category": "力学性能"},
            ],
            "deleted_ids": [],
        },
    )
    assert r1.status_code == 200, r1.text
    assert r1.json()["data"]["created"] == 2

    listed = (await client.get(
        f"/api/v1/kb/{kb_id}/terms?term_base_id={base_id}&page_size=100",
        headers={"Authorization": f"Bearer {super_token}"},
    )).json()["data"]["items"]
    first = next(t for t in listed if t["term_name"] == "抗拉强度")

    # 更新 1 条 + 删除 1 条
    r2 = await client.put(
        f"/api/v1/kb/{kb_id}/term-bases/{base_id}/terms/batch",
        headers={"Authorization": f"Bearer {super_token}"},
        json={
            "items": [
                {"id": first["id"], "term": "抗拉强度", "english_term": "R_m", "category": "力学性能"},
            ],
            "deleted_ids": [next(t for t in listed if t["term_name"] == "屈服强度")["id"]],
        },
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["data"] == {"created": 0, "updated": 1, "deleted": 1}

    listed2 = (await client.get(
        f"/api/v1/kb/{kb_id}/terms?term_base_id={base_id}&page_size=100",
        headers={"Authorization": f"Bearer {super_token}"},
    )).json()["data"]["items"]
    assert len(listed2) == 1
    assert listed2[0]["english_term"] == "R_m"
    assert listed2[0]["status"] == TERM_STATUS_ACTIVE


async def test_batch_save_rejects_api_base(monkeypatch, client, super_token, db_session):
    """G5 集成：api 数据源术语集批量保存被拒绝（只读）。"""

    kb = await create_kb_via_api(client, super_token, "S8只读拒绝")
    kb_id = uuid.UUID(kb["id"])
    base = await term_base_service.create_term_base(
        db_session, kb_id, None,
        {"name": "只读", "source_type": "api", "source_config": {"url": "http://10.0.0.97/x"}},
    )
    base_id = base["id"]
    resp = await client.put(
        f"/api/v1/kb/{kb_id}/term-bases/{base_id}/terms/batch",
        headers={"Authorization": f"Bearer {super_token}"},
        json={"items": [{"term": "X"}], "deleted_ids": []},
    )
    assert resp.status_code == 400
    assert "只读" in resp.json()["message"]


async def test_search_field_manual_and_dynamic(monkeypatch, client, super_token, db_session):
    """G4 集成：字段级搜索（manual 固定字段 / api-db extras 动态列）。"""
    kb = await create_kb_via_api(client, super_token, "S8字段搜索")
    kb_id = kb["id"]
    base = await _create_manual(
        client, super_token, kb_id, name="搜索",
        items=[
            {"term": "抗拉强度", "standard_name": "拉伸强度", "category": "力学性能"},
            {"term": "硬度", "standard_name": "布氏硬度", "category": "硬度类"},
        ],
    )
    base_id = base["id"]

    # manual：search_field=category
    r1 = await client.get(
        f"/api/v1/kb/{kb_id}/terms?term_base_id={base_id}&keyword=力学&search_field=category",
        headers={"Authorization": f"Bearer {super_token}"},
    )
    names1 = [t["term_name"] for t in r1.json()["data"]["items"]]
    assert names1 == ["抗拉强度"]

    # api 术语集：动态列 extras ilike
    from app.services.glossary import source_api

    api_base = await term_base_service.create_term_base(
        db_session, uuid.UUID(kb_id), None,
        {
            "name": "动态搜索",
            "source_type": "api",
            "source_config": {"url": "http://10.0.0.96/x"},
            "columns": [{"name": "spec", "type": "string", "label": "规格"}],
        },
    )
    api_id = uuid.UUID(api_base["id"])

    async def fake_fetch(config, limit=1000, client=None):
        return {"rows": [
            {"term_name": "A", "spec": "AA-100"},
            {"term_name": "B", "spec": "BB-200"},
        ], "columns": [], "total": 2}

    monkeypatch.setattr(source_api, "fetch_rows", fake_fetch)
    await term_base_service.sync_term_base(db_session, uuid.UUID(kb_id), api_id, None)
    r2 = await client.get(
        f"/api/v1/kb/{kb_id}/terms?term_base_id={api_id}&keyword=AA-100&search_field=spec",
        headers={"Authorization": f"Bearer {super_token}"},
    )
    names2 = [t["term_name"] for t in r2.json()["data"]["items"]]
    assert names2 == ["A"]


async def test_sync_clears_removed_rows(monkeypatch, client, super_token, db_session):
    """G6 集成：同步清空重导——源端删除的词条会被清理。"""
    from app.services.glossary import source_api

    kb = await create_kb_via_api(client, super_token, "S8清空重导")
    kb_id = uuid.UUID(kb["id"])
    base = await term_base_service.create_term_base(
        db_session, kb_id, None,
        {"name": "清空", "source_type": "api", "source_config": {"url": "http://10.0.0.95/x"}},
    )
    base_id = uuid.UUID(base["id"])

    async def rows1(config, limit=1000, client=None):
        return {"rows": [{"term_name": "A"}, {"term_name": "B"}], "columns": [], "total": 2}

    monkeypatch.setattr(source_api, "fetch_rows", rows1)
    await term_base_service.sync_term_base(db_session, kb_id, base_id, None)

    async def rows2(config, limit=1000, client=None):
        return {"rows": [{"term_name": "B"}], "columns": [], "total": 1}

    monkeypatch.setattr(source_api, "fetch_rows", rows2)
    result = await term_base_service.sync_term_base(db_session, kb_id, base_id, None)
    assert result["imported"] == 1

    rows = (await db_session.execute(
        select(Term).where(Term.term_base_id == base_id)
    )).scalars().all()
    assert {t.term_name for t in rows} == {"B"}  # 硬删：源端已删除的词条被清理，无软删残留
    assert len(rows) == 1


async def test_sync_fallback_first_column(monkeypatch, client, super_token, db_session):
    """复刻对齐：未识别名称列时回退第一列（columns[0]/行首列），空值行才跳过。"""
    from app.services.glossary import source_api

    kb = await create_kb_via_api(client, super_token, "S8无名称列")
    kb_id = uuid.UUID(kb["id"])
    base = await term_base_service.create_term_base(
        db_session, kb_id, None,
        {
            "name": "无名称列",
            "source_type": "api",
            "source_config": {"url": "http://10.0.0.98/x"},
            "columns": [{"name": "spec", "type": "string", "label": "规格"}],
        },
    )
    base_id = uuid.UUID(base["id"])

    async def fake_fetch(config, limit=1000, client=None):
        return {"rows": [{"spec": "AA"}, {"code": "B"}, {"empty": ""}], "columns": [], "total": 3}

    monkeypatch.setattr(source_api, "fetch_rows", fake_fetch)
    result = await term_base_service.sync_term_base(db_session, kb_id, base_id, None)
    assert result["imported"] == 2  # AA（首列）+ B（行首列 code）
    assert result["total"] == 3
    assert result["skipped"] == 1  # 空值行

    rows = (await db_session.execute(
        select(Term).where(Term.term_base_id == base_id, Term.deleted_at.is_(None))
    )).scalars().all()
    assert {t.term_name for t in rows} == {"AA", "B"}
