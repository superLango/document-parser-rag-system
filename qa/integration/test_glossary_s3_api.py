"""L2/L3：M33-S3 术语 API 全链路。"""

import uuid

from qa.fixtures.indexing_helpers import create_kb_via_api


async def _mk_base(client, super_token, kb_id, name="S3术语集"):
    r = await client.post(
        f"/api/v1/kb/{kb_id}/term-bases",
        headers={"Authorization": f"Bearer {super_token}"},
        json={"name": name, "source_type": "manual"},
    )
    assert r.status_code == 200, r.text
    return r.json()["data"]["id"]


async def test_term_full_flow(client, super_token, db_session):
    """L3M33-S3-01：术语创建→列表过滤→详情→更新→审核→删除→导出。"""
    kb = await create_kb_via_api(client, super_token, "S8术语全流程")
    kb_id = kb["id"]
    h = {"Authorization": f"Bearer {super_token}"}
    base_id = await _mk_base(client, super_token, kb_id)

    # 创建（active）
    created = await client.post(
        f"/api/v1/kb/{kb_id}/terms",
        headers=h,
        json={"term": "抗拉强度", "term_base_id": base_id,
              "standard_name": "抗拉强度", "category": "力学性能",
              "synonyms": ["Rm"]},
    )
    assert created.status_code == 200, created.text
    term_id = created.json()["data"]["id"]

    # 列表 + 关键词/分类过滤
    listed = await client.get(
        f"/api/v1/kb/{kb_id}/terms?keyword=抗拉",
        headers=h,
    )
    assert listed.json()["data"]["total"] == 1
    by_cat = await client.get(
        f"/api/v1/kb/{kb_id}/terms?category=力学性能",
        headers=h,
    )
    assert by_cat.json()["data"]["total"] == 1

    # 详情
    detail = await client.get(f"/api/v1/kb/{kb_id}/terms/{term_id}", headers=h)
    assert detail.json()["data"]["term_name"] == "抗拉强度"

    # 更新
    updated = await client.put(
        f"/api/v1/kb/{kb_id}/terms/{term_id}",
        headers=h,
        json={"definition": "材料抵抗拉伸断裂的能力", "aliases": ["TS"]},
    )
    assert updated.json()["data"]["definition"].startswith("材料抵抗")

    # 审核（pending → approve）
    pend = await client.post(
        f"/api/v1/kb/{kb_id}/terms",
        headers=h,
        json={"term": "待审词", "term_base_id": base_id, "status_hint": "pending"},
    )
    # 手动创建始终 active，这里通过直接更新状态模拟外部同步 pending
    from sqlalchemy import text as sa_text

    await db_session.execute(
        sa_text("update terms set status='pending' where id=:id").bindparams(id=uuid.UUID(pend.json()["data"]["id"]))
    )
    await db_session.commit()
    reviewed = await client.put(
        f"/api/v1/kb/{kb_id}/terms/{pend.json()['data']['id']}/review",
        headers=h,
        json={"action": "approve"},
    )
    assert reviewed.json()["data"]["status"] == "active"

    # 分类列表
    cats = await client.get(f"/api/v1/kb/{kb_id}/terms/categories", headers=h)
    assert "力学性能" in cats.json()["data"]["categories"]

    # 导出
    exported = await client.get(f"/api/v1/kb/{kb_id}/terms/export", headers=h)
    assert exported.status_code == 200
    assert "抗拉强度" in exported.text

    # 删除
    deleted = await client.delete(f"/api/v1/kb/{kb_id}/terms/{term_id}", headers=h)
    assert deleted.status_code == 200
    gone = await client.get(f"/api/v1/kb/{kb_id}/terms/{term_id}", headers=h)
    assert gone.status_code == 400


async def test_batch_import(client, super_token, db_session):
    """L3M33-S3-02：批量导入（幂等，批内同名去重）。"""
    kb = await create_kb_via_api(client, super_token, "S8批量")
    kb_id = kb["id"]
    h = {"Authorization": f"Bearer {super_token}"}
    base_id = await _mk_base(client, super_token, kb_id, "批量集")
    items = [
        {"term": "T1", "term_base_id": base_id, "category": "A"},
        {"term": "T1", "term_base_id": base_id, "definition": "补充"},  # 批内同名
        {"term": "T2", "term_base_id": base_id},
    ]
    r = await client.post(f"/api/v1/kb/{kb_id}/terms/batch", headers=h, json={"items": items})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["imported"] == 2

    # 再导入相同批次 → 幂等不新增
    r2 = await client.post(f"/api/v1/kb/{kb_id}/terms/batch", headers=h, json={"items": items})
    assert r2.json()["data"]["imported"] == 2
    total = (await client.get(f"/api/v1/kb/{kb_id}/terms", headers=h)).json()["data"]["total"]
    assert total == 2
