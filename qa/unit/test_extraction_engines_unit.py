"""L1 单元：抽取引擎（BaseExtract / LangExtract）配置消费与行为。"""

from types import SimpleNamespace

from app.services.extraction import llm_extractor
from app.services.extraction.extraction_models import ExtractionTarget
from app.services.extraction.llm_extractor import input_char_budget
from app.services.extraction_config_service import DEFAULT_GLOBAL_CONFIG


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
        "enable_thinking": True, "max_tokens": 1000, "json_mode": True,
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



def test_split_context_no_loss():
    """L1E3-14：上下文切分不丢失内容，且每段不超过输入预算。"""
    ctx = "中文内容" * 300
    segs = llm_extractor.split_context(ctx, 200, 30, 500)
    assert "".join(segs) == ctx
    assert all(len(s) <= 500 for s in segs)

async def test_base_extract_json_mode_default_off():
    """L1E3-17：BaseExtract 默认不启用 json_object（对齐脚本验证路线）。"""
    client = CaptureLLM()
    ep = {"max_tokens": 1000}
    await llm_extractor.extract_category(_cfg(), _target(), "上下文", client, ep, engine="BaseExtract")
    assert client.calls[0]["json_mode"] is False


async def test_base_extract_whole_context_single_call():
    """L1E3-16：长上下文整段拼入 Prompt 一次给模型（不截断、不分段）。"""
    client = CaptureLLM()
    ep = {
        "temperature": 0.0, "max_tokens": 100000,
        "batch": {"single_threshold": 100000, "batch_chars": 6000, "context_truncate": 60000},
    }
    # 超过旧阈值 8000 字符，验证仍单次调用且内容完整
    ctx = "化学成分表内容。" * 2000  # 约 14000 字符
    await llm_extractor.extract_category(_cfg(), _target(), ctx, client, ep, engine="BaseExtract")
    assert len(client.calls) == 1, "长上下文应整段一次调用，不应分段"
    user_msg = client.calls[0]["messages"][1]["content"]
    assert ctx in user_msg, "上下文应完整拼接，不得截断"


def test_default_engine_is_base_extract():
    """L1E3-15：默认引擎为自研 BaseExtract，参数对齐验证值（100000/1800/并发32）。"""
    assert DEFAULT_GLOBAL_CONFIG["llm"]["engine"] == "BaseExtract"
    base = DEFAULT_GLOBAL_CONFIG["llm"]["engines"]["BaseExtract"]
    assert base["max_tokens"] == 100000
    assert base["timeout"] == 1800
    assert base["enable_thinking"] is False
    assert base["concurrency"]["max_concurrency"] == 32
    assert base["concurrency"]["cross_category"] == 32
    # LangExtractPkg 保留可切换
    assert "LangExtractPkg" in DEFAULT_GLOBAL_CONFIG["llm"]["engines"]
