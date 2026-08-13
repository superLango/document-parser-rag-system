"""L1 单元：E3 解析/上下文/Prompt 渲染。"""

from types import SimpleNamespace

import pytest
from app.services.extraction import context_assembler, llm_extractor, prompt_renderer
from app.services.extraction.extraction_models import ExtractionTarget
from app.services.llm.llm_client import LLMError


async def test_parse_records_fence_and_forms():
    """L1E3-01：围栏数组/对象含 records/非法 JSON。"""
    assert await _parse("```json\n[{\"a\":1}]\n```") == [{"a": 1}]
    assert await _parse('{"records": [{"a": 1}]}') == [{"a": 1}]
    assert await _parse('{"a": 1}') == [{"a": 1}]
    with pytest.raises(LLMError):
        await _parse("not json")


async def _parse(text: str) -> list[dict]:
    return llm_extractor.parse_records(text, {})


async def test_missing_required_fields():
    """L1E3-02：必填字段缺失检测。"""
    schema = {"type": "array", "properties": {"a": {"required": True}, "b": {"required": True}}}
    missing = llm_extractor.missing_required_fields([{"a": "x"}], schema)
    assert missing == ["b"]


async def test_context_assembler_truncate():
    """L1E3-03：上下文按 token 预算截断。"""
    hits = [{"source_pages": [1], "content": "A" * 1000}, {"source_pages": [2], "content": "B" * 1000}]
    text = context_assembler.assemble(hits, top_k=2, max_tokens=100, chars_per_token=1.5)
    assert len(text) <= 150 + 30
    assert "内容截断" in text or len(text) < 300


async def test_prompt_renderer_substitutions():
    """L1E3-04：${feature}/字段/术语集占位符替换。"""
    cfg = SimpleNamespace(prompt_templates=[{
        "schema_template_id": "t1",
        "categories": [{"category_id": "c1", "user_prompt": "${feature} ${f1} ${材料库.standard_name}"}],
        "system_prompt": "sys",
    }])
    target = ExtractionTarget(
        feature="室温拉伸", category_id="c1", template_id="t1",
        fields=[{"name": "f1", "type": "string", "required": True}],
        query_terms=["抗拉强度"],
        schema={"type": "array", "properties": {}},
        term_data={"材料库": [{"standard_name": "拉伸强度"}]},
    )
    system, user = prompt_renderer.render_category(cfg, target, "ctx")
    assert system == "sys"
    assert "室温拉伸" in user and "f1" in user and "[拉伸强度]" in user
