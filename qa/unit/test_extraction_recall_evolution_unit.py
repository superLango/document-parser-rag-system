"""L1 单元：9.5 类别召回演进（第二版统计 / 第三版 strict/loose/off + 词法兜底）。"""

import uuid
from types import SimpleNamespace

import pytest
from app.services.extraction import category_builder
from app.services.extraction.extraction_resolver import ExtractionDomainConfig
from app.services.indexing.retrieval import SearchResult
from pydantic import ValidationError


def _cfg(mode: str, threshold: float = 0.5, keyword_min: int = 1) -> ExtractionDomainConfig:
    tb1 = str(uuid.uuid4())
    tb2 = str(uuid.uuid4())
    return ExtractionDomainConfig(
        kb_id=str(uuid.uuid4()),
        global_config={
            "retrieval": {
                "top_k": 10,
                "default_confidence_threshold": threshold,
                "category_recall": {"mode": mode, "top_k": 5, "per_dim_top_k": 10},
                "hybrid": {"keyword_min_hits": keyword_min},
            }
        },
        schema_templates=[{
            "id": "t1", "name": "T", "is_active": True,
            "categories": [
                {
                    "id": "c1", "name": "标准信息", "return_type": "object",
                    "extraction_strategy": "always", "fixed_query": "标准", "fields": [],
                    "name_source": "manual", "query_sources": [], "is_active": True,
                },
                {
                    "id": "c2", "name": "", "return_type": "array",
                    "extraction_strategy": "auto", "fixed_query": "",
                    "name_source": "term_base", "name_term_base_id": tb1,
                    "name_term_field": "NAME", "query_sources": [
                        {"label": "检测项目", "term_base_id": tb2, "value_field": "NAME", "in_query": True},
                    ],
                    "fields": [], "is_active": True,
                },
            ],
        }],
        term_bases=[{"id": tb1, "name": "项目大类"}, {"id": tb2, "name": "检测项目"}],
    )


async def _search_mock(query: str, **kwargs):
    if query == "室温拉伸":
        return [SearchResult(chunk_id="c1", document_id="d", content="x", score=0.95, keyword_matched=True)]
    if query == "高温拉伸":
        kw = kwargs.get("kw", False)
        return [SearchResult(chunk_id="c2", document_id="d", content="y", score=0.2, keyword_matched=kw)]
    return []


async def _run(monkeypatch, mode, threshold=0.5, keyword_min=1, kw_hit=False):
    async def fake_search(db, kb_id, query, top_k=None, filters=None, per_dim_top_k=None, retrieval_config=None):
        return await _search_mock(query, kw=kw_hit)

    monkeypatch.setattr(category_builder, "retrieval_service", SimpleNamespace(search=fake_search))
    def fake_distinct(rows, field, limit=200):
        # 展开使用 EXPAND_LIMIT(200)，Query 术语集使用 query_main_limit(默认30)
        return ["室温拉伸", "高温拉伸"] if limit >= 200 else []

    monkeypatch.setattr(category_builder, "distinct_field_values", fake_distinct)
    async def fake_load_term_base(db, kb_id, tb_id):
        return []

    monkeypatch.setattr(category_builder, "load_term_base", fake_load_term_base)
    kept, skipped, schemas = await category_builder.build(_cfg(mode, threshold, keyword_min), None, kb_id=str(uuid.uuid4()), document_id=uuid.uuid4())
    return kept, skipped, schemas


async def test_loose_mode_zero_hit_skip(monkeypatch):
    """L1M34-09：宽松模式=零命中剔除，阈值仅记录。"""
    kept, skipped, _ = await _run(monkeypatch, "loose")
    features = {t.feature for t in kept}
    assert features == {"室温拉伸", "高温拉伸"}
    assert len(skipped) == 1
    assert skipped[0].feature == "标准信息"
    assert "零命中" in skipped[0].reason
    assert skipped[0].score == 0.0
    by_feature = {t.feature: t for t in kept}
    assert by_feature["室温拉伸"].hit_score == 0.95
    assert by_feature["高温拉伸"].hit_count == 1


async def test_strict_mode_threshold_skip_and_keyword_fallback(monkeypatch):
    """L1M34-10：严格模式按阈值剔除；词法命中达标则兜底保留。"""
    kept, skipped, _ = await _run(monkeypatch, "strict", threshold=0.5, keyword_min=1, kw_hit=False)
    assert {t.feature for t in kept} == {"室温拉伸"}
    assert len(skipped) == 2
    low = next(s for s in skipped if s.feature == "高温拉伸")
    assert "置信度低于阈值" in low.reason
    assert low.score == 0.2

    # 词法兜底：keyword_matched=True 且达到 keyword_min_hits → 保留
    kept2, skipped2, _ = await _run(monkeypatch, "strict", threshold=0.5, keyword_min=1, kw_hit=True)
    assert {t.feature for t in kept2} == {"室温拉伸", "高温拉伸"}
    assert all(s.feature == "标准信息" for s in skipped2)


async def test_off_mode_all_categories_participate(monkeypatch):
    """L1M34-11：关闭模式=零命中类别也参与（空上下文），不做召回过滤。"""
    kept, skipped, schemas = await _run(monkeypatch, "off")
    assert len(skipped) == 0
    features = {t.feature for t in kept}
    assert features == {"标准信息", "室温拉伸", "高温拉伸"}
    std = next(t for t in kept if t.feature == "标准信息")
    assert std.hits == [] and std.schema == {"type": "object", "properties": {}}
    assert "标准信息" in schemas["categories"]


async def test_invalid_mode_rejected_by_schema(monkeypatch):
    """L1M34-12：非法召回模式被 Pydantic 拒绝。"""
    from app.schemas.extraction import GlobalConfigContent

    with pytest.raises(ValidationError):
        GlobalConfigContent(retrieval={"category_recall": {"mode": "bogus"}})
