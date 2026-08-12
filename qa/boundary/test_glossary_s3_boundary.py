"""L4 边界：M33-S3 术语 API。"""

import uuid

from qa.fixtures.indexing_helpers import create_kb_via_api


async def _mk_base(client, super_token, kb_id, name="S3边界集"):
    r = await client.post(
        f"/api/v1/kb/{kb_id}/term-bases",
        headers={"Authorization": f"Bearer {super_token}"},
        json={"name": name, "source_type": "manual"},
    )
    return r.json()["data"]["id"]


async def test_duplicate_term_409(client, super_token):
    """L4M33-S3-01：同术语集重复术语名 409。"""
    kb = await create_kb_via_api(client, super_token, "S8术语重名")
    h = {"Authorization": f"Bearer {super_token}"}
    base_id = await _mk_base(client, super_token, kb["id"])
    body = {"term": "重名", "term_base_id": base_id}
    assert (await client.post(f"/api/v1/kb/{kb['id']}/terms", headers=h, json=body)).status_code == 200
    r2 = await client.post(f"/api/v1/kb/{kb['id']}/terms", headers=h, json=body)
    assert r2.status_code == 409


async def test_term_validation(client, super_token):
    """L4M33-S3-02：空术语/未知术语集/超长拒绝。"""
    kb = await create_kb_via_api(client, super_token, "S8术语校验")
    h = {"Authorization": f"Bearer {super_token}"}
    r1 = await client.post(f"/api/v1/kb/{kb['id']}/terms", headers=h, json={"term": "", "term_base_id": str(uuid.uuid4())})
    assert r1.status_code in (400, 422)
    r2 = await client.post(
        f"/api/v1/kb/{kb['id']}/terms",
        headers=h,
        json={"term": "x", "term_base_id": str(uuid.uuid4())},
    )
    assert r2.status_code == 400
    r3 = await client.post(
        f"/api/v1/kb/{kb['id']}/terms",
        headers=h,
        json={"term": "x" * 300, "term_base_id": str(uuid.uuid4())},
    )
    assert r3.status_code in (400, 422)


async def test_batch_without_base_rejected(client, super_token):
    """L4M33-S3-03：批量导入未指定术语集 400。"""
    kb = await create_kb_via_api(client, super_token, "S8批量无集")
    r = await client.post(
        f"/api/v1/kb/{kb['id']}/terms/batch",
        headers={"Authorization": f"Bearer {super_token}"},
        json={"items": [{"term": "x"}]},
    )
    assert r.status_code == 400


async def test_batch_over_limit(client, super_token, db_session):
    """L4M33-S3-04：批量超过 5000 条被拒。"""
    from app.core.exceptions import BusinessException
    from app.services.glossary import term_service

    kb = await create_kb_via_api(client, super_token, "S8批量上限")
    kb_id = uuid.UUID(kb["id"])
    base_id = await _mk_base(client, super_token, kb["id"], "上限集")
    items = [{"term": f"T{i}", "term_base_id": base_id} for i in range(5001)]
    try:
        await term_service.batch_import_terms(db_session, kb_id, uuid.UUID(base_id), None, items)
    except BusinessException as exc:
        assert "5000" in str(exc.message)
    else:
        raise AssertionError("应抛业务异常")
