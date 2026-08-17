"""L1 单元：抽取引擎（BaseExtract / LangExtract）配置消费与行为。"""

from types import SimpleNamespace

from app.services.extraction import llm_extractor
from app.services.extraction.extraction_models import ExtractionTarget
from app.services.extraction.llm_extractor import input_char_budget


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


def test_input_char_budget():
    """L1E3-13：输入预算随输出 max_tokens 收缩，并保底。"""
    assert input_char_budget(8192) < input_char_budget(4096)
    assert input_char_budget(40000) >= 2000
    assert input_char_budget(32768) < 55000 * 1.5
