"""L1 单元：抽取引擎（BaseExtract / LangExtract）配置消费与行为。"""

from types import SimpleNamespace

from app.services.extraction import llm_extractor
from app.services.extraction.extraction_models import ExtractionTarget


class CaptureLLM:
    """捕获 complete 的 messages 与 kwargs，返回固定 JSON。"""

    def __init__(self, payload: str = '[{"a": 1}]'):
        self.payload = payload
        self.calls: list[dict] = []

    async def complete(self, messages, **kwargs):
        self.calls.append({"messages": messages, **kwargs})
        return self.payload


def _cfg():
    return SimpleNamespace(prompt_templates=[{
        "schema_template_id": "t1",
        "categories": [{"category_id": "c1", "user_prompt": "[文档内容]:${context}", "system_prompt": "sys"}],
    }])


def _target(fields=None):
    return ExtractionTarget(
        feature="室温拉伸", category_id="c1", template_id="t1",
        fields=fields or [{"name": "a", "type": "string", "example": "x"}],
        schema={"type": "array", "properties": {"a": {"type": "string"}}},
    )


async def test_base_extract_consumes_llm_params():
    """L1E3-10：BaseExtract 消费 top_p/top_k/timeout/enable_thinking/batch。"""
    client = CaptureLLM()
    ep = {
        "temperature": 0.2, "top_p": 0.9, "top_k": 5, "timeout": 123,
        "enable_thinking": True, "max_tokens": 1000,
        "batch": {"single_threshold": 8000, "batch_chars": 6000, "overlap": 500, "context_truncate": 32000},
    }
    records = await llm_extractor.extract_category(_cfg(), _target(), "上下文内容", client, ep, engine="BaseExtract")
    assert records == [{"a": 1}]
    call = client.calls[0]
    assert call["temperature"] == 0.2
    assert call["top_p"] == 0.9
    assert call["top_k"] == 5
    assert call["timeout"] == 123
    assert call["enable_thinking"] is True
    assert call["max_tokens"] == 1000
    assert call["json_mode"] is True


async def test_lang_extract_multi_pass_windows_and_params():
    """L1E3-11：LangExtract 消费 passes/窗口/few-shot/围栏/类别内并发。"""
    client = CaptureLLM()
    target = _target([
        {"name": "项目名称", "type": "string", "example": "抗拉强度(Rm)"},
        {"name": "单位", "type": "string", "example": "MPa"},
    ])
    ep = {
        "temperature": 0.0, "max_tokens": 200, "timeout": 60,
        "format_type": "JSON", "fence_output": True, "max_examples": 3,
        "passes": 2, "context_window_chars": 100, "max_char_buffer": 500,
        "batch": {"overlap": 20},
        "concurrency": {"within_category": 2},
    }
    context = "A" * 300
    windows = llm_extractor._split_windows(context, 100, 20, 500)
    records = await llm_extractor.extract_category(_cfg(), target, context, client, ep, engine="LangExtract")
    assert len(client.calls) == 2 * len(windows)  # passes × windows
    assert len(records) == 1  # 重复输出去重
    all_users = "".join(c["messages"][1]["content"] for c in client.calls)
    assert "抗拉强度(Rm)" in all_users      # few-shot 示例注入
    assert "围栏" in all_users              # fence_output 说明
    assert "[已抽取记录]" in all_users       # pass≥2 注入已抽记录
    assert client.calls[0]["json_mode"] is True


async def test_lang_extract_yaml_and_fence():
    """L1E3-12：LangExtract YAML 输出 + 围栏剥离。"""
    client = CaptureLLM("```yaml\n- 项目名称: 抗拉强度(Rm)\n  单位: MPa\n```")
    ep = {
        "max_tokens": 200, "format_type": "YAML", "fence_output": True,
        "max_examples": 0, "passes": 1, "context_window_chars": 1000,
        "max_char_buffer": 2000, "batch": {"overlap": 0},
        "concurrency": {"within_category": 1},
    }
    target = _target([
        {"name": "项目名称", "type": "string", "example": "抗拉强度(Rm)"},
        {"name": "单位", "type": "string", "example": "MPa"},
    ])
    records = await llm_extractor.extract_category(_cfg(), target, "短上下文", client, ep, engine="LangExtract")
    assert records == [{"项目名称": "抗拉强度(Rm)", "单位": "MPa"}]
    assert client.calls[0]["json_mode"] is False
    assert "YAML" in client.calls[0]["messages"][1]["content"]
