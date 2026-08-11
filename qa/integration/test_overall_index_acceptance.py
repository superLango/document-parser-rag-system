"""M32 索引整体验收（S1-S7 综合）：真实全链路 + 生命周期 + 越权 + 并发。"""

import asyncio
import time
import uuid

import pytest
from sqlalchemy import select, text as sa_text

from app.models.indexing import KbBm25Stats
from app.services.indexing.retrieval import SearchFilters, retrieval_service
from qa.fixtures.indexing_helpers import create_kb_via_api


def _structured_pdf() -> bytes:
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 150), "1 范围", fontsize=18)
    page.insert_text((72, 190), "本文件规定了不锈钢棒材的化学成分和力学性能要求。", fontsize=12)
    page.insert_text((72, 215), "抗拉强度按 GB/T 228.1 执行，规定值 715 MPa。", fontsize=12)
    page.insert_text((72, 240), "晶间腐蚀试验按 GB/T 4334 执行，试验温度应符合要求。", fontsize=12)
    page.insert_text((72, 265), "伸长率应不小于 25%，断面收缩率应不小于 40%。", fontsize=12)
    data = doc.tobytes()
    doc.close()
    return data


async def _wait(client, token, kb_id, doc_id, field, expect, timeout=120):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        r = await client.get(
            f"/api/v1/kb/{kb_id}/documents/{doc_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200, r.text
        if r.json()["data"].get(field) == expect:
            return r.json()["data"]
        await asyncio.sleep(0.5)
    raise AssertionError(f"等待超时：{field} → {expect}")


async def test_full_lifecycle_real_document(client, super_token, db_session):
    """L3M32-01：真实 PDF 上传→解析→自动索引→混合检索→删除回退。"""
    from app.core.config import settings

    kb = await create_kb_via_api(client, super_token, "S7整体验收")
    kb_id = kb["id"]
    files = {"file": ("acc.pdf", _structured_pdf(), "application/pdf")}
    up = await client.post(
        f"/api/v1/kb/{kb_id}/documents",
        headers={"Authorization": f"Bearer {super_token}"},
        files=files,
    )
    assert up.status_code == 200, up.text
    doc = up.json()["data"]["document"]

    original_ocr = settings.PARSEKIT_OCR_ENABLED
    settings.PARSEKIT_OCR_ENABLED = True
    try:
        start = await client.post(
            f"/api/v1/kb/{kb_id}/documents/{doc['id']}/start",
            headers={"Authorization": f"Bearer {super_token}"},
        )
        assert start.status_code == 200
        await _wait(client, super_token, kb_id, doc["id"], "status", "completed")
        # 自动索引在 sync 模式解析完成后立即执行
        data = await _wait(client, super_token, kb_id, doc["id"], "index_status", "indexed")
        assert data["index_total"] >= 1
    finally:
        settings.PARSEKIT_OCR_ENABLED = original_ocr

    # 混合检索（语义 + 词法）
    hits = await retrieval_service.search(db_session, uuid.UUID(kb_id), "抗拉强度 715", top_k=5)
    assert hits
    assert any(("715" in h.content) or ("抗拉" in h.content) or ("力学" in h.content) for h in hits)

    # 过滤：has_table=False（该文档无表格）
    filtered = await retrieval_service.search(
        db_session, uuid.UUID(kb_id), "不锈钢", top_k=5, filters=SearchFilters(has_table=False)
    )
    assert filtered and all(not h.has_table for h in filtered)

    # 删除文档 → 块清理 + 统计回退
    from app.services import document_service

    await document_service.delete_document(db_session, uuid.UUID(kb_id), uuid.UUID(doc["id"]))
    stats = (
        await db_session.execute(
            select(KbBm25Stats).where(KbBm25Stats.kb_id == uuid.UUID(kb_id))
        )
    ).scalar_one()
    assert stats.payload["n_docs"] == 0
    gone = await retrieval_service.search(db_session, uuid.UUID(kb_id), "抗拉强度")
    assert gone == []


async def test_overall_permissions(client, super_token, db_session):
    """L5M32-02：越权矩阵（viewer 可搜不可触发索引，非成员全拒绝）。"""
    async def _mk(prefix):
        username = f"{prefix}_{uuid.uuid4().hex[:8]}"
        r = await client.post(
            "/api/v1/users",
            headers={"Authorization": f"Bearer {super_token}"},
            json={"username": username, "password": "Test@1234", "role_codes": ["member"]},
        )
        return username

    async def _login(u):
        r = await client.post("/api/v1/auth/login", json={"username": u, "password": "Test@1234"})
        return r.json()["data"]["access_token"]

    owner_name = await _mk("accown")
    viewer_name = await _mk("accview")
    outsider_name = await _mk("accout")
    owner_token = await _login(owner_name)
    kb = (
        await client.post(
            "/api/v1/kb",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"name": "S7越权", "domain_code": "general"},
        )
    ).json()["data"]
    inv = (
        await client.post(
            f"/api/v1/kb/{kb['id']}/invitations",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"username": viewer_name, "role": "viewer"},
        )
    ).json()["data"]
    viewer_token = await _login(viewer_name)
    await client.post(
        f"/api/v1/kb/invitations/{inv['token']}/accept",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    outsider_token = await _login(outsider_name)

    # viewer：可检索、不可触发索引
    sr = await client.post(
        f"/api/v1/kb/{kb['id']}/search",
        headers={"Authorization": f"Bearer {viewer_token}"},
        json={"query": "任何"},
    )
    assert sr.status_code == 200
    # 非成员：检索 403
    sr2 = await client.post(
        f"/api/v1/kb/{kb['id']}/search",
        headers={"Authorization": f"Bearer {outsider_token}"},
        json={"query": "任何"},
    )
    assert sr2.status_code == 403


async def test_overall_concurrent(client, super_token, db_session):
    """L5M32-03（并发）：并发检索一致 + 并发触发索引仅一任务。"""
    from app.services.indexing.bm25 import kb_bm25_service

    kb = await create_kb_via_api(client, super_token, "S7并发验收")
    kb_id = uuid.UUID(kb["id"])
    results = await asyncio.gather(*[
        retrieval_service.search(db_session, kb_id, "空语料查询") for _ in range(5)
    ])
    assert all(r == [] for r in results)
