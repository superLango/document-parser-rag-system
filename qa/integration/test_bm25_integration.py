"""L2 集成 + L3 功能：M29 BM25 统计与查询（真实索引链路）。"""

import asyncio
import json
import time
import uuid

from sqlalchemy import select, text as sa_text

from app.models.indexing import KbBm25Stats
from qa.fixtures.indexing_helpers import create_document_row, create_kb_via_api


def _layout_for(text_blocks: list[dict]) -> dict:
    """每个文本块独立为一个标题章节，保证分块为多个子块。"""
    children = []
    blocks = []
    order = 0
    for i, tb in enumerate(text_blocks):
        title = tb.get("title", f"{i + 1} 章节")
        children.append(
            {
                "type": "title", "content": title, "level": 1,
                "page": i, "order": order, "children": [
                    {"type": "text", "content": tb["content"], "level": 0,
                     "page": i, "order": order + 1, "children": []},
                ],
            }
        )
        blocks.append(
            {"type": "title", "bbox": [50, 50 + i * 80, 500, 80 + i * 80],
             "page_index": i, "order": order, "confidence": 0.95,
             "content": title, "source": "ocr"}
        )
        blocks.append(
            {"type": "text", "bbox": [50, 90 + i * 80, 500, 130 + i * 80],
             "page_index": i, "order": order + 1, "confidence": 0.9,
             "content": tb["content"], "source": "ocr"}
        )
        order += 2
    return {
        "schema_version": "1.2",
        "producer": "parsekit",
        "layout_engine": "ppdoclayoutv3",
        "classification": "ocr",
        "page_count": len(text_blocks),
        "pages": [{"page_index": i, "width": 595, "height": 842,
                   "path": f"pages/page-{i:04d}.png", "blocks": [blocks[i]]}
                  for i in range(len(text_blocks))],
        "rebuild": {"enabled": True,
                    "document_tree": {"type": "root", "children": children}},
    }


async def _seed_and_index(client, super_token, db, kb_id, name, text_blocks):
    from app.services import storage

    layout = _layout_for(text_blocks)
    key = f"kb-{uuid.UUID(kb_id).hex}/ocr/bm25/{name}/layout.json"
    storage.put_object(key, json.dumps(layout, ensure_ascii=False).encode("utf-8"), "application/json")
    doc_id = await create_document_row(db, uuid.UUID(kb_id), filename=f"{name}.pdf", layout_path=key)
    resp = await client.post(
        f"/api/v1/kb/{kb_id}/documents/{doc_id}/index",
        headers={"Authorization": f"Bearer {super_token}"},
    )
    assert resp.status_code == 200, resp.text
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        r = await client.get(
            f"/api/v1/kb/{kb_id}/documents/{doc_id}",
            headers={"Authorization": f"Bearer {super_token}"},
        )
        if r.json()["data"]["index_status"] == "indexed":
            return doc_id
        await asyncio.sleep(0.4)
    raise AssertionError("索引等待超时")


async def test_index_updates_bm25_stats_and_scores(client, super_token, db_session):
    """L2M29-01：索引后 stats 更新，查询按词法相关性排序。"""
    from app.services.indexing.bm25 import kb_bm25_service

    kb = await create_kb_via_api(client, super_token, "S5统计")
    kb_id = kb["id"]
    await _seed_and_index(
        client, super_token, db_session, kb_id, "mech",
        [
            {"content": "抗拉强度按 GB/T 228.1 执行，规定值 715。"},
            {"content": "化学成分 C 含量不大于 0.060。"},
        ],
    )
    stats = (
        await db_session.execute(
            select(KbBm25Stats).where(KbBm25Stats.kb_id == uuid.UUID(kb_id))
        )
    ).scalar_one()
    assert stats.payload["n_docs"] == 2
    assert stats.payload["total_len"] >= 10
    assert "抗拉强度" in stats.payload["doc_freq"]

    hits = await kb_bm25_service.score_query(db_session, uuid.UUID(kb_id), "抗拉强度 715", top_k=5)
    assert hits
    assert hits[0]["chunk_id"].endswith("_p0_0")  # 含抗拉强度的块排第一
    assert "抗拉强度" in hits[0]["content"]

    hits2 = await kb_bm25_service.score_query(db_session, uuid.UUID(kb_id), "化学成分 0.060")
    assert hits2 and hits2[0]["chunk_id"].endswith("_p1_0")


async def test_reindex_stats_stable(client, super_token, db_session):
    """L3M29-02：重索引后 BM25 统计不漂移。"""
    from app.services.indexing.bm25 import kb_bm25_service

    kb = await create_kb_via_api(client, super_token, "S5幂等")
    kb_id = kb["id"]
    doc_id = await _seed_and_index(
        client, super_token, db_session, kb_id, "stable",
        [{"content": "力学性能 拉伸 伸长率 25。"}],
    )
    stats1 = (
        await db_session.execute(
            select(KbBm25Stats).where(KbBm25Stats.kb_id == uuid.UUID(kb_id))
        )
    ).scalar_one()
    n1 = stats1.payload["n_docs"]

    # 重索引
    resp = await client.post(
        f"/api/v1/kb/{kb_id}/documents/{doc_id}/index",
        headers={"Authorization": f"Bearer {super_token}"},
    )
    assert resp.status_code == 200, resp.text
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        r = await client.get(
            f"/api/v1/kb/{kb_id}/documents/{doc_id}",
            headers={"Authorization": f"Bearer {super_token}"},
        )
        if r.json()["data"]["index_status"] == "indexed":
            break
        await asyncio.sleep(0.4)
    stats2 = (
        await db_session.execute(
            select(KbBm25Stats).where(KbBm25Stats.kb_id == uuid.UUID(kb_id))
        )
    ).scalar_one()
    assert stats2.payload["n_docs"] == n1
    assert stats2.payload["total_len"] == stats1.payload["total_len"]


async def test_delete_document_rolls_back_stats(client, super_token, db_session):
    """L3M29-03：删除文档后块清理且 BM25 统计回退。"""
    from app.services import document_service
    from app.services.indexing.bm25 import kb_bm25_service

    kb = await create_kb_via_api(client, super_token, "S5删除")
    kb_id = kb["id"]
    doc_id = await _seed_and_index(
        client, super_token, db_session, kb_id, "del",
        [{"content": "冲击试验 吸收能量 27J。"}],
    )
    stats = (
        await db_session.execute(
            select(KbBm25Stats).where(KbBm25Stats.kb_id == uuid.UUID(kb_id))
        )
    ).scalar_one()
    assert stats.payload["n_docs"] == 1

    await document_service.delete_document(db_session, uuid.UUID(kb_id), doc_id)
    stats2 = (
        await db_session.execute(
            select(KbBm25Stats).where(KbBm25Stats.kb_id == uuid.UUID(kb_id))
        )
    ).scalar_one()
    assert stats2.payload["n_docs"] == 0
    hits = await kb_bm25_service.score_query(db_session, uuid.UUID(kb_id), "冲击试验")
    assert hits == []
