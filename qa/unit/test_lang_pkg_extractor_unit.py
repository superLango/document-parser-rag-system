"""L1 单元：LangExtract 原包适配器（配置传递 / 示例 / output_schema / 解析）。"""

from types import SimpleNamespace

from app.services.extraction import lang_pkg_extractor
from app.services.extraction.extraction_models import ExtractionTarget


class _FakeResult:
    def __init__(self, extractions):
        self.extractions = extractions


async def test_pkg_adapter_passes_config_and_parses(monkeypatch):
    """L1M34-15：原包适配器消费全部 LangExtract 参数并解析结果。"""
    captured = {}

    def fake_lx_extract(text, **kwargs):
        captured["text"] = text
        captured["kwargs"] = kwargs
        return _FakeResult([{"项目名称": "抗拉强度(Rm)", "单位": "MPa"}])

    monkeypatch.setattr(lang_pkg_extractor, "lx_extract", fake_lx_extract)
    cfg = SimpleNamespace(prompt_templates=[{
        "schema_template_id": "t1",
        "categories": [{"category_id": "c1", "user_prompt": "[任务]:${feature}\n[文档]:${context}", "system_prompt": "sys"}],
    }])
    target = ExtractionTarget(
        feature="室温拉伸", category_id="c1", template_id="t1",
        fields=[
            {"name": "项目名称", "type": "string", "required": True, "example": "抗拉强度(Rm)"},
            {"name": "单位", "type": "string", "required": True, "example": "MPa"},
        ],
        schema={"type": "array", "properties": {"项目名称": {"type": "string"}, "单位": {"type": "string"}}},
    )
    ep = {
        "format_type": "JSON", "fence_output": True, "max_examples": 3,
        "passes": 2, "context_window_chars": 28000, "max_char_buffer": 40000,
        "temperature": 0.0, "max_tokens": 4096, "enable_thinking": False,
        "concurrency": {"within_category": 2},
    }
    endpoint = {"api_base": "http://127.0.0.1:9988/v1", "model": "Qwen3.6-35B-A3B-FP8", "api_key": ""}
    records = await lang_pkg_extractor.extract_category_pkg(
        kb_id="kb", cfg=cfg, target=target, context="上下文", engine_params=ep, llm_endpoint=endpoint,
    )
    assert records == [{"项目名称": "抗拉强度(Rm)", "单位": "MPa"}]
    kw = captured["kwargs"]
    assert kw["extraction_passes"] == 2
    # 分段抽取：不再使用包内窗口，由外层按 batch_chars 切分
    assert kw["context_window_chars"] is None
    assert kw["max_char_buffer"] == len("上下文")
    assert kw["max_workers"] == 2
    # output_schema（XGrammar）与 fence_output 互斥：有 schema 时自动关闭围栏
    assert kw["fence_output"] is False
    assert len(kw["examples"]) == 2  # 1 条完整正例 + 1 条拆条示例
    assert len(kw["examples"][1].extractions) == 2  # 拆条示例含两条记录
    assert "室温拉伸" in kw["output_schema"]["properties"]["extractions"]["items"]["properties"]
    assert "室温拉伸_attributes" in kw["output_schema"]["properties"]["extractions"]["items"]["properties"]
    assert "[任务]" in kw["prompt_description"]
    assert kw["prompt_validation_level"].value == "off"


async def test_pkg_adapter_requires_endpoint(monkeypatch):
    """L1M34-16：未配置 LLM 端点时明确报错。"""
    import pytest
    from app.core.exceptions import BusinessException

    cfg = SimpleNamespace(prompt_templates=[])
    target = ExtractionTarget(feature="f", category_id="c1", template_id="t1", fields=[], schema={})
    with pytest.raises(BusinessException, match="LLM 端点"):
        await lang_pkg_extractor.extract_category_pkg(
            kb_id="kb", cfg=cfg, target=target, context="x", engine_params={}, llm_endpoint={},
        )



async def test_pkg_adapter_keeps_fence_without_schema(monkeypatch):
    """L1M34-17：无 output_schema 时 fence_output 保持配置值。"""
    captured = {}

    def fake_lx_extract(text, **kwargs):
        captured["kwargs"] = kwargs
        return _FakeResult([])

    monkeypatch.setattr(lang_pkg_extractor, "lx_extract", fake_lx_extract)
    cfg = SimpleNamespace(prompt_templates=[{
        "schema_template_id": "t1",
        "categories": [{"category_id": "c1", "user_prompt": "[文档]:${context}", "system_prompt": "sys"}],
    }])
    target = ExtractionTarget(feature="f", category_id="c1", template_id="t1", fields=[], schema={})
    await lang_pkg_extractor.extract_category_pkg(
        kb_id="kb", cfg=cfg, target=target, context="x",
        engine_params={"fence_output": True, "passes": 1, "max_examples": 0, "concurrency": {"within_category": 1}},
        llm_endpoint={"api_base": "http://127.0.0.1:9988/v1", "model": "m", "api_key": ""},
    )
    assert captured["kwargs"]["fence_output"] is True


async def test_pkg_adapter_splits_long_context(monkeypatch):
    """L1M34-20：上下文超过 batch_chars 时拆段多次抽取，结果合并去重。"""
    calls = []

    def fake_lx_extract(text, **kwargs):
        calls.append(text)
        return _FakeResult([{"项目名称": f"项-{len(calls)}"}])

    monkeypatch.setattr(lang_pkg_extractor, "lx_extract", fake_lx_extract)
    cfg = SimpleNamespace(prompt_templates=[{
        "schema_template_id": "t1",
        "categories": [{"category_id": "c1", "user_prompt": "[任务]:${feature}\n[文档]:${context}", "system_prompt": "sys"}],
    }])
    target = ExtractionTarget(feature="室温拉伸", category_id="c1", template_id="t1",
                              fields=[{"name": "项目名称", "type": "string", "example": "抗拉强度(Rm)"}],
                              schema={"type": "array", "properties": {"项目名称": {"type": "string"}}})
    ep = {
        "format_type": "JSON", "fence_output": False, "max_examples": 0, "passes": 1,
        "max_tokens": 8192, "timeout": 60, "concurrency": {"within_category": 1},
        "batch": {"batch_chars": 100, "overlap": 20},
    }
    context = "A" * 300
    records = await lang_pkg_extractor.extract_category_pkg(
        kb_id="kb", cfg=cfg, target=target, context=context, engine_params=ep,
        llm_endpoint={"api_base": "http://127.0.0.1:9988/v1", "model": "m", "api_key": ""},
    )
    assert len(calls) > 1
    # 全部片段拼接后包含原上下文（不截断）
    assert "".join(calls) == context
    assert len(records) == len(calls)
