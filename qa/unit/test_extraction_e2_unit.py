"""L1 单元：E2 LLM 客户端与资源配置 Schema。"""

import httpx
import pytest
from app.schemas.resource import LLMResourceSave
from app.services.llm.llm_client import LLMError, OpenAICompatibleClient, mask_api_key
from pydantic import ValidationError


def _handler(payload: dict, status: int = 200, content: str = "ok"):
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        assert payload.get("response_format") == {"type": "json_object"} if payload.get("response_format") else True
        return httpx.Response(status, json={"choices": [{"message": {"content": content}}]})
    return handler


async def test_complete_json_mode():
    """L1E2-01：json_mode 正确传参并返回内容。"""
    seen = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        import json
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "{\"a\":1}"}}]})

    transport = httpx.MockTransport(handler)
    client = OpenAICompatibleClient("http://llm:8001/v1", "qwen", api_key="k", timeout=5, transport=transport)
    text = await client.complete([{"role": "user", "content": "hi"}], json_mode=True)
    assert text == "{\"a\":1}"
    assert seen["body"]["model"] == "qwen"
    assert seen["body"]["response_format"] == {"type": "json_object"}
    assert seen["body"]["messages"][0]["content"] == "hi"


async def test_complete_http_error_raises():
    """L1E2-02：HTTP 非 200 抛 LLMError。"""

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    transport = httpx.MockTransport(handler)
    client = OpenAICompatibleClient("http://llm:8001/v1", "qwen", transport=transport)
    with pytest.raises(LLMError, match="500"):
        await client.complete([{"role": "user", "content": "hi"}])


async def test_invalid_base_url_rejected():
    """L1E2-03：非法 base_url 被拒绝。"""
    from app.core.exceptions import BusinessException

    with pytest.raises(BusinessException):
        OpenAICompatibleClient("ftp://llm", "qwen")


async def test_mask_api_key():
    """L1E2-04：API Key 掩码。"""
    assert mask_api_key("") == ""
    assert mask_api_key("abcdef1234") == "****1234"
    assert mask_api_key("ab") == "****"


async def test_resource_schema_rejects_bad_base():
    """L1E2-05：LLMResourceSave 拒绝非 http(s) 地址。"""
    with pytest.raises(ValidationError):
        LLMResourceSave(api_base="ftp://x", model="m")
