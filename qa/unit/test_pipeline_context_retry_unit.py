"""L1 单元：页码排序上下文 + 0 条自动重排重试（正式流程适配）。"""

from types import SimpleNamespace

import pytest

from app.services.extraction import context_assembler, pipeline
from app.services.extraction.extraction_models import CategoryResult, ExtractionTarget


def _hits() -> list[dict]:
    return [
        {"chunk_id": "c1", "source_pages": [2], "content": "BBB", "has_table": False, "rerank_score": 0.9},
        {"chunk_id": "c2", "source_pages": [1], "content": "AAA", "has_table": True, "rerank_score": 0.1},
        {"chunk_id": "c3", "source_pages": [3], "content": "CCC", "has_table": False, "rerank_score": 0.5},
    ]


async def test_assemble_page_order_sorted_and_tagged():
    """L1P01：页码排序按 source_pages 升序，表格/正文带标签。"""
    text = context_assembler.assemble_page_order(_hits(), top_k=3)
    assert text.index("AAA") < text.index("BBB") < text.index("CCC")
    assert "[表格][第 1 页]" in text
    assert "[正文][第 2 页]" in text


async def test_assemble_page_order_top_k():
    """L1P02：top_k 截断生效。"""
    text = context_assembler.assemble_page_order(_hits(), top_k=2)
    assert "CCC" not in text


async def test_category_result_retried_field():
    """L1P03：CategoryResult 序列化含 retried/retry（未重试时不输出）。"""
    plain = CategoryResult(feature="化学成分", records=[{"a": 1}]).to_dict()
    assert "retried" not in plain
    retried = CategoryResult(
        feature="热处理制度", records=[{"b": 2}], retried=True,
        retry={"mode": "rerank", "records": 3, "context_chars": 100},
    ).to_dict()
    assert retried["retried"] is True
    assert retried["retry"]["mode"] == "rerank"


def _target(hits: list[dict]) -> ExtractionTarget:
    return ExtractionTarget(
        feature="热处理制度",
        category_id="c1",
        template_id="t1",
        extraction_strategy="always",
        hits=hits,
        schema={"type": "array", "properties": {}},
    )


def _cfg() -> SimpleNamespace:
    return SimpleNamespace(rule_groups=[], global_config={}, kb_id="kb1")


async def test_pipeline_retry_rerank_on_empty(monkeypatch):
    """L1P04：主排序（页码）0 条 → 自动重排再抽并采用重排结果。"""
    calls: list[str] = []

    async def fake_extract(cfg, target, context, client, engine_params, engine="BaseExtract"):
        calls.append(context)
        if len(calls) == 1:
            return []  # 第一轮（页码）空
        return [{"材料牌号": "13Cr13Mo"}]  # 第二轮（重排）有数据

    monkeypatch.setattr(pipeline.llm_extractor, "extract_category", fake_extract)
    target = _target(_hits())
    result = await pipeline._extract_single(
        session=None, cfg=_cfg(), target=target, client=object(), engine="BaseExtract",
        engine_params={}, retrieval_cfg={},
        context_cfg={"sort_mode": "page", "retry_rerank_on_empty": True},
        script_timeout=10, doc_id="doc1",
    )
    assert isinstance(result, CategoryResult)
    assert result.retried is True
    assert result.retry == {"mode": "rerank", "records": 1, "context_chars": len(calls[1])}
    assert result.records == [{"材料牌号": "13Cr13Mo"}]
    assert len(calls) == 2
    # 第一轮是页码排序（带 [正文]/[表格] 前缀），第二轮是重排（无 kind 前缀）
    assert "[正文]" in calls[0]
    assert "[正文]" not in calls[1]


async def test_pipeline_no_retry_when_disabled(monkeypatch):
    """L1P05：retry_rerank_on_empty=False 时 0 条不重试。"""
    calls: list[str] = []

    async def fake_extract(cfg, target, context, client, engine_params, engine="BaseExtract"):
        calls.append(context)
        return []

    monkeypatch.setattr(pipeline.llm_extractor, "extract_category", fake_extract)
    target = _target(_hits())
    result = await pipeline._extract_single(
        session=None, cfg=_cfg(), target=target, client=object(), engine="BaseExtract",
        engine_params={}, retrieval_cfg={},
        context_cfg={"sort_mode": "page", "retry_rerank_on_empty": False},
        script_timeout=10, doc_id="doc1",
    )
    assert result.retried is False
    assert result.records == []
    assert len(calls) == 1


async def test_pipeline_sort_mode_rerank_no_double(monkeypatch):
    """L1P06：sort_mode=rerank 时主排序即重排，0 条不重复重排。"""
    calls: list[str] = []

    async def fake_extract(cfg, target, context, client, engine_params, engine="BaseExtract"):
        calls.append(context)
        return []

    monkeypatch.setattr(pipeline.llm_extractor, "extract_category", fake_extract)
    target = _target(_hits())
    result = await pipeline._extract_single(
        session=None, cfg=_cfg(), target=target, client=object(), engine="BaseExtract",
        engine_params={}, retrieval_cfg={},
        context_cfg={"sort_mode": "rerank", "retry_rerank_on_empty": True},
        script_timeout=10, doc_id="doc1",
    )
    assert result.retried is False
    assert len(calls) == 1


async def test_pipeline_both_rounds_empty(monkeypatch):
    """L1P07：两轮都空时标记 retried 但保持空结果。"""
    calls: list[str] = []

    async def fake_extract(cfg, target, context, client, engine_params, engine="BaseExtract"):
        calls.append(context)
        return []

    monkeypatch.setattr(pipeline.llm_extractor, "extract_category", fake_extract)
    target = _target(_hits())
    result = await pipeline._extract_single(
        session=None, cfg=_cfg(), target=target, client=object(), engine="BaseExtract",
        engine_params={}, retrieval_cfg={},
        context_cfg={"sort_mode": "page", "retry_rerank_on_empty": True},
        script_timeout=10, doc_id="doc1",
    )
    assert result.retried is True
    assert result.records == []
    assert result.retry == {"mode": "rerank", "records": 0, "context_chars": len(calls[1])}
    assert len(calls) == 2
