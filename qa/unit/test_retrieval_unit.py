"""L1 单元测试：M30 检索服务（向量字面量/过滤/RRF）。"""

import uuid

from app.services.indexing.retrieval import (
    RetrievalService,
    SearchFilters,
    _filters_sql,
    _vector_literal,
)


def test_vector_literal_format():
    """L1M30-01：向量列表转为 pgvector 字面量。"""
    lit = _vector_literal([0.1, -0.25, 1.0])
    assert lit.startswith("[") and lit.endswith("]")
    assert "0.1" in lit and "-0.25" in lit


def test_filters_sql_empty():
    """L1M30-02：无过滤条件返回空 SQL。"""
    sql, params = _filters_sql(None)
    assert sql == "" and params == {}


def test_filters_sql_all():
    """L1M30-03：全部过滤条件组合。"""
    doc_id = uuid.uuid4()
    sql, params = _filters_sql(SearchFilters(document_id=doc_id, has_table=True, level=2))
    assert "document_id = :f_doc" in sql
    assert "has_table = :f_table" in sql
    assert "level = :f_level" in sql
    assert params["f_doc"] == doc_id and params["f_table"] is True and params["f_level"] == 2


def test_filters_sql_partial():
    """L1M30-04：仅文档过滤。"""
    doc_id = uuid.uuid4()
    sql, params = _filters_sql(SearchFilters(document_id=doc_id))
    assert "has_table" not in sql and "level" not in sql
    assert len(params) == 1


def test_rrf_fuse_ranks_dense_first():
    """L1M30-05：RRF 融合按排名加权，双路命中优先。"""
    dense = [
        ("a", 0.9, {"chunk_id": "a"}),
        ("b", 0.8, {"chunk_id": "b"}),
    ]
    keyword = [{"chunk_id": "b"}, {"chunk_id": "c"}]
    fused = RetrievalService._rrf_fuse(dense, keyword, top_k=3, rrf_k=60.0, dense_w=1.0, kw_w=1.2)
    cids = [cid for cid, _ in fused]
    assert cids[0] == "b"  # 双路命中得分最高
    assert set(cids) == {"a", "b", "c"}


def test_rrf_fuse_top_k_limit():
    """L1M30-06：RRF 结果受 top_k 限制。"""
    dense = [(f"c{i}", 0.5, {"chunk_id": f"c{i}"}) for i in range(10)]
    fused = RetrievalService._rrf_fuse(dense, [], top_k=4, rrf_k=60.0, dense_w=1.0, kw_w=1.2)
    assert len(fused) == 4


def test_rrf_fuse_single_source():
    """L1M30-07：仅词法命中也可进入结果。"""
    fused = RetrievalService._rrf_fuse([], [{"chunk_id": "k1"}], top_k=5, rrf_k=60.0, dense_w=1.0, kw_w=1.2)
    assert fused == [("k1", 1.2 / (60 + 1))]


def test_rrf_fuse_configurable_weights():
    """L1M30-08：RRF 权重由全局配置驱动（词法权重调高后词法命中分上升）。"""
    kw = [{"chunk_id": "k1"}]
    low = RetrievalService._rrf_fuse([], kw, top_k=5, rrf_k=60.0, dense_w=1.0, kw_w=1.2)
    high = RetrievalService._rrf_fuse([], kw, top_k=5, rrf_k=60.0, dense_w=1.0, kw_w=2.4)
    assert high[0][1] > low[0][1]
    assert high[0][1] == 2.4 / 61
