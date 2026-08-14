"""LLM 客户端（OpenAI 兼容：vLLM/Ollama/兼容网关）。"""

from __future__ import annotations

from urllib.parse import urlparse

import httpx

from app.core.exceptions import BusinessException


class LLMError(Exception):
    """LLM 调用异常（超时/HTTP/解析）。"""


class OpenAICompatibleClient:
    """OpenAI 兼容 chat/completions 客户端。

    用法（E3 抽取流水线）：
        client = await get_llm_client_from_resource(db, kb_id)
        text = await client.complete(messages, json_mode=True, temperature=0.0)
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "",
        timeout: int = 300,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        parsed = urlparse(base_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise BusinessException(message=f"LLM 服务地址无效：{base_url}")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self._transport = transport

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def complete(
        self,
        messages: list[dict],
        *,
        json_mode: bool = False,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        timeout: int | None = None,
        top_p: float | None = None,
        top_k: int | None = None,
        enable_thinking: bool | None = None,
    ) -> str:
        payload: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens:
            payload["max_tokens"] = int(max_tokens)
        if top_p is not None:
            payload["top_p"] = float(top_p)
        if top_k is not None:
            payload["top_k"] = int(top_k)
        if enable_thinking:
            payload["chat_template_kwargs"] = {"enable_thinking": True}
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        try:
            async with httpx.AsyncClient(timeout=timeout or self.timeout, transport=self._transport) as client:
                resp = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=self._headers(),
                    json=payload,
                )
        except httpx.HTTPError as exc:
            raise LLMError(f"LLM 请求失败：{exc}") from exc
        if resp.status_code != 200:
            raise LLMError(
                f"LLM 调用失败（{resp.status_code}）：{(resp.text or '')[:300]}"
            )
        try:
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError) as exc:
            raise LLMError(f"LLM 响应格式异常：{exc}") from exc

    async def ping(self) -> None:
        """连通性测试：GET /models 或 /v1/models。"""
        try:
            async with httpx.AsyncClient(timeout=min(self.timeout, 15), transport=self._transport) as client:
                resp = await client.get(f"{self.base_url}/models", headers=self._headers())
        except httpx.HTTPError as exc:
            raise LLMError(f"LLM 连接失败：{exc}") from exc
        if resp.status_code >= 400:
            raise LLMError(f"LLM 服务异常（{resp.status_code}）：{(resp.text or '')[:200]}")


def mask_api_key(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 4:
        return "****"
    return f"****{key[-4:]}"
