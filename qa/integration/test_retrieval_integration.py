"""L2 集成 + L3 功能：M30 混合检索（双向量 + BM25 + RRF + 过滤）。"""

import asyncio
import json
import time
import uuid

from app.services.indexing.retrieval import SearchFilters, retrieval_service
from qa.fixtures.indexing_helpers import create_document_row, create_kb_via_api


def _doc_layout(sections: list[dict]) -> dict:
    """sections: [{title, content, table_html?}] 独立章节。"""
    children = []
    blocks = []
    order = 0
    for i, sec in enumerate(sections):
        children.append({
            "type": "title", "content": sec["title"], "level": 1,
            "page": i, "order": order, "children": [
                {"type": "text", "content": sec["content"], "level": 0,
                 "page": i, "order": order + 1, "children": []},
            ],
        })
        blocks.append({"type": "title", "bbox": [50, 50 + i * 80, 500, 80 + i * 80],
                       "page_index": i, "order": order, "confidence": 0.95,
                       "content": sec["title"], "source": "ocr"})
        blocks.append({"type": "text", "bbox": [50, 90 + i * 80, 500, 130 + i * 80],
                       "page_index": i, "order": order + 1, "confidence": 0.9,
                       "content": sec["content"], "source": "ocr"})
        if sec.get("table_html"):
            table_node = {"type": "table", "content": sec["table_html"], "level": 0,
                          "page": i, "order": order + 2, "children": []}
            children[-1]["children"].append(table_node)
            blocks.append({"type": "table", "bbox": [50, 140 + i * 80, 500, 260 + i * 80],
                           "page_index": i, "order": order + 2, "confidence": 0.8,
                           "content": sec["table_html"], "source": "ocr"})
        order += 3
    return {
        "schema_version": "1.2", "producer": "parsekit",
        "layout_engine": "ppdoclayoutv3", "classification": "ocr",
        "page_count": len(sections),
        "pages": [{"page_index": i, "width": 595, "height": 842,
                   "path": f"pages/page-{i:04d}.png",
                   "blocks": [b for b in blocks if b["page_index"] == i]}
                  for i in range(len(sections))],
        "rebuild": {"enabled": True,
                    "document_tree": {"type": "root", "children": children}},
    }


async def _index_doc(client, super_token, db, kb_id, name, layout):
    from app.services import storage

    kb_uuid = kb_id if isinstance(kb_id, uuid.UUID) else uuid.UUID(kb_id)
    key = f"kb-{kb_uuid.hex}/ocr/retr/{name}/layout.json"
    storage.put_object(key, json.dumps(layout, ensure_ascii=False).encode("utf-8"), "application/json")
    doc_id = await create_document_row(db, kb_uuid, filename=f"{name}.pdf", layout_path=key)
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


async def _seed_two_docs(client, super_token, db_session, kb_id):
    table_html = (
        "<table><tr><th rowspan='2'>GB/T 序号</th><th colspan='2'>规定非比例延伸强度</th></tr>"
        "<tr><th>不小于</th><th>不大于</th></tr>"
        "<tr><td>67</td><td>440</td><td>715</td></tr></table>"
    )
    d1 = await _index_doc(
        client, super_token, db_session, kb_id, "mech",
        _doc_layout([
            {"title": "1 范围", "content": "本文件规定了不锈钢棒材的化学成分与力学性能要求。"},
            {"title": "2 力学性能", "content": "抗拉强度按 GB/T 228.1 执行，规定值 715。",
             "table_html": table_html},
        ]),
    )
    d2 = await _index_doc(
        client, super_token, db_session, kb_id, "corrosion",
        _doc_layout([
            {"title": "3 耐蚀性", "content": "晶间腐蚀试验按 GB/T 4334 执行。"},
        ]),
    )
    return d1, d2


async def test_hybrid_search_semantic_and_keyword(client, super_token, db_session):
    """L2M30-01：语义查询与词法查询均命中相关块。"""
    kb = await create_kb_via_api(client, super_token, "S6混合")
    kb_id = uuid.UUID(kb["id"])
    await _seed_two_docs(client, super_token, db_session, kb_id)

    hits = await retrieval_service.search(db_session, kb_id, "抗拉强度要求", top_k=5)
    assert hits
    assert any("抗拉强度" in h.content for h in hits)

    hits2 = await retrieval_service.search(db_session, kb_id, "晶间腐蚀 GB/T 4334", top_k=5)
    assert hits2
    assert "晶间腐蚀" in hits2[0].content


async def test_search_filters(client, super_token, db_session):
    """L3M30-02：过滤条件（has_table/document_id）生效。"""
    kb = await create_kb_via_api(client, super_token, "S6过滤")
    kb_id = uuid.UUID(kb["id"])
    d1, d2 = await _seed_two_docs(client, super_token, db_session, kb_id)

    table_hits = await retrieval_service.search(
        db_session, kb_id, "不锈钢", top_k=10,
        filters=SearchFilters(has_table=True),
    )
    assert table_hits
    assert all(h.has_table for h in table_hits)

    doc_hits = await retrieval_service.search(
        db_session, kb_id, "试验", top_k=10,
        filters=SearchFilters(document_id=d2),
    )
    assert doc_hits
    assert all(h.document_id == str(d2) for h in doc_hits)


async def test_search_api_and_rerank_passthrough(client, super_token, db_session):
    """L3M30-03：搜索 API 返回结构完整，rerank 直通。"""
    kb = await create_kb_via_api(client, super_token, "S6API")
    kb_id = kb["id"]
    await _seed_two_docs(client, super_token, db_session, kb_id)
    resp = await client.post(
        f"/api/v1/kb/{kb_id}/search",
        headers={"Authorization": f"Bearer {super_token}"},
        json={"query": "化学成分 力学性能", "top_k": 5},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["query"] == "化学成分 力学性能"
    assert data["total"] >= 1
    item = data["items"][0]
    for field in ("chunk_id", "document_id", "content", "hierarchy_path",
                  "title", "source_pages", "has_table", "score"):
        assert field in item
