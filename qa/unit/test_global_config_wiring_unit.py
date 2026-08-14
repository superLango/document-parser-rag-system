"""L1 单元：全局配置接线（Query 术语集 group/精简/去重、语义重排）。"""

import uuid
from types import SimpleNamespace

from app.services.extraction import category_builder


async def test_build_query_terms_group_filter_and_refined(monkeypatch):
    """L1M34-13：Query 术语集 group_field 按类别过滤，主/精简上限与 dedupe 生效。"""
    tb = str(uuid.uuid4())
    rows = [
        {"extras": {"NAME": "A室温项目", "FEATURE": "室温拉伸"}},
        {"extras": {"NAME": "B高温项目", "FEATURE": "高温拉伸"}},
        {"extras": {"NAME": "C室温项目", "FEATURE": "室温拉伸"}},
    ]
    async def fake_load(db, kb_id, tb_id):
        return rows

    monkeypatch.setattr(category_builder, "load_term_base", fake_load)
    async def fake_refined(rows, field, limit, thr):
        return ["C室温项目"]

    monkeypatch.setattr(category_builder, "_build_refined_terms", fake_refined)

    target = SimpleNamespace(
        feature="室温拉伸",
        fixed_query="标准 检测",
        query_sources=[{
            "in_query": True, "term_base_id": tb, "value_field": "NAME",
            "group_field": "FEATURE", "query_main_limit": 30,
            "query_refined_limit": 2, "dedupe": True,
        }],
    )
    terms = await category_builder._build_query_terms(None, "kb", target, {}, 0.85)
    assert "标准" in terms and "检测" in terms
    assert "A室温项目" in terms
    assert "C室温项目" in terms
    assert "B高温项目" not in terms


async def test_build_refined_terms_semantic_dedupe(monkeypatch):
    """L1M34-14：精简查询按余弦阈值语义去重并受 refined_limit 截断。"""
    from app.services.embedding.embedding_service import embedding_service

    async def fake_embed(texts):
        vecs = {"a": [1.0, 0.0], "b": [0.0, 1.0], "c": [0.9, 0.1]}
        return [vecs[t] for t in texts]

    monkeypatch.setattr(embedding_service, "embed", fake_embed)
    rows = [
        {"extras": {"NAME": "a"}},
        {"extras": {"NAME": "a"}},
        {"extras": {"NAME": "b"}},
        {"extras": {"NAME": "c"}},
    ]
    kept = await category_builder._build_refined_terms(rows, "NAME", limit=2, threshold=0.9)
    # a 保留；重复 a 跳过；b 保留（与 a 正交）；c 与 a 相似 ≥0.9 视为重复
    assert kept == ["a", "b"]


async def test_semantic_reranker_orders_by_similarity(monkeypatch):
    """L1M30-09：SemanticReranker 按 BGE-M3 余弦相似度重排并截断 top_n。"""
    from types import SimpleNamespace as NS

    from app.services.embedding.embedding_service import embedding_service
    from app.services.indexing.reranker import SemanticReranker

    async def fake_embed(texts):
        vec = {"q": [1.0, 0.0], "远": [0.0, 1.0], "近": [0.99, 0.01]}
        return [vec.get(t, [0.5, 0.5]) for t in texts]

    monkeypatch.setattr(embedding_service, "embed", fake_embed)
    hits = [NS(content="近"), NS(content="远")]
    reranked = await SemanticReranker().rerank("q", hits, top_k=1)
    assert reranked == [hits[0]]
