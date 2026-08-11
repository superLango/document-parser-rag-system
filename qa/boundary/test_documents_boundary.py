"""L4 边界异常：Phase 1 文档任务骨架（M17）。"""

import asyncio
import uuid


async def _unique(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


async def _kb(client, super_token, name="边界文档库"):
    resp = await client.post(
        "/api/v1/kb",
        headers={"Authorization": f"Bearer {super_token}"},
        json={"name": name, "domain_code": "general"},
    )
    return resp.json()["data"]


async def test_invalid_uuid_and_missing_document(client, super_token):
    kb = await _kb(client, super_token)
    h = {"Authorization": f"Bearer {super_token}"}
    assert (
        await client.get(f"/api/v1/kb/{kb['id']}/documents/not-a-uuid", headers=h)
    ).status_code == 400
    assert (
        await client.get(
            f"/api/v1/kb/{kb['id']}/documents/{uuid.uuid4()}", headers=h
        )
    ).status_code == 400
    assert (
        await client.delete(
            f"/api/v1/kb/{kb['id']}/documents/{uuid.uuid4()}", headers=h
        )
    ).status_code == 400
    assert (
        await client.get(
            f"/api/v1/kb/{kb['id']}/documents?page=0", headers=h
        )
    ).status_code == 400
    assert (
        await client.get(
            f"/api/v1/kb/{kb['id']}/documents?page_size=101", headers=h
        )
    ).status_code == 400


async def test_concurrent_uploads_all_succeed(client, super_token):
    """并发用例：同一 KB 并发上传 5 份文档全部成功，task_id 唯一。"""
    kb = await _kb(client, super_token)
    h = {"Authorization": f"Bearer {super_token}"}

    async def _upload(i):
        return await client.post(
            f"/api/v1/kb/{kb['id']}/documents",
            headers=h,
            files={"file": (f"c{i}.pdf", f"%PDF {i}".encode(), "application/pdf")},
        )

    results = await asyncio.gather(*[_upload(i) for i in range(5)])
    assert all(r.status_code == 200 for r in results)
    task_ids = [r.json()["data"]["task"]["task_id"] for r in results]
    assert len(set(task_ids)) == 5


async def test_keyword_filter(client, super_token):
    kb = await _kb(client, super_token)
    h = {"Authorization": f"Bearer {super_token}"}
    await client.post(
        f"/api/v1/kb/{kb['id']}/documents",
        headers=h,
        files={"file": ("alpha.pdf", b"%PDF a", "application/pdf")},
    )
    await client.post(
        f"/api/v1/kb/{kb['id']}/documents",
        headers=h,
        files={"file": ("beta.pdf", b"%PDF b", "application/pdf")},
    )
    resp = await client.get(
        f"/api/v1/kb/{kb['id']}/documents?keyword=alpha", headers=h
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["total"] == 1
    assert resp.json()["data"]["items"][0]["filename"] == "alpha.pdf"


async def test_original_invalid_and_missing(client, super_token, db_session):
    """L4：original 端点非法 UUID、文档不存在、对象缺失均返回 400。"""
    from sqlalchemy import text as sa_text

    kb = await _kb(client, super_token)
    h = {"Authorization": f"Bearer {super_token}"}
    assert (
        await client.get(
            f"/api/v1/kb/{kb['id']}/documents/not-a-uuid/original", headers=h
        )
    ).status_code == 400
    assert (
        await client.get(
            f"/api/v1/kb/{kb['id']}/documents/{uuid.uuid4()}/original", headers=h
        )
    ).status_code == 400

    up = await client.post(
        f"/api/v1/kb/{kb['id']}/documents",
        headers=h,
        files={"file": ("missing.pdf", b"%PDF missing", "application/pdf")},
    )
    assert up.status_code == 200
    doc_id = up.json()["data"]["document"]["id"]
    await db_session.execute(
        sa_text(
            "UPDATE documents SET object_key = 'kb-x/originals/not-exist.pdf' WHERE id = :doc_id"
        ),
        {"doc_id": uuid.UUID(doc_id)},
    )
    await db_session.commit()
    resp = await client.get(
        f"/api/v1/kb/{kb['id']}/documents/{doc_id}/original", headers=h
    )
    assert resp.status_code == 400
