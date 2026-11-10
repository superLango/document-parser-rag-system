"""OpenAI-compatible clients for GLM-OCR and Qwen extraction."""

from __future__ import annotations

import base64
import io
import json
import logging
import threading
import time
from typing import Any

import httpx

from .base import (
    FailoverEndpoints,
    ModelServiceError,
    api_base,
    http_timeout,
    is_failover_error,
    request_json,
)

logger = logging.getLogger(__name__)

GLM_OCR_PROMPTS = {
    "title": "请完整识别图片中的标题文字，直接输出标题文本，不要输出任何解释。",
    "text": "请完整识别图片中的正文文字，保留原有段落和换行，直接输出 Markdown 文本，不要输出任何解释。",
    "table": "请将图片中的表格完整识别并转换为 HTML <table> 格式输出，保留所有行列内容，不要输出解释。",
    "formula": "请将图片中的公式识别并转换为 LaTeX 公式输出，不要输出解释。",
    "image_caption": "请识别图片中的图注文字，直接输出文本，不要输出解释。",
    "table_caption": "请识别图片中的表注文字，直接输出文本，不要输出解释。",
    "footnote": "请识别图片中的脚注文字，直接输出文本，不要输出解释。",
    "aside_text": "请识别图片中的旁注文字，直接输出文本，不要输出解释。",
}


class OpenAICompatibleClient:
    """Minimal OpenAI-compatible chat client with retries and health check."""

    service = "openai-compatible"

    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        fallback_base_url: str | None = None,
        failover_probe_seconds: float = 60.0,
        api_key: str | None = None,
        timeout: float = 120.0,
        retries: int = 2,
        client: httpx.Client | None = None,
    ) -> None:
        self._endpoints = FailoverEndpoints.shared(
            api_base(base_url),
            *(
                [api_base(fallback_base_url)]
                if fallback_base_url
                else []
            ),
            probe_interval=failover_probe_seconds,
        )
        self.model = model
        self.api_key = api_key
        self.retries = retries
        self._client = client or httpx.Client(
            timeout=http_timeout(timeout), trust_env=False
        )
        self._owns_client = client is None
        self.usage: dict[str, int] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }
        self.last_usage: dict[str, int] = {}
        self.calls = 0
        self._usage_lock = threading.Lock()

    @property
    def base_url(self) -> str:
        return self._endpoints.active

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "OpenAICompatibleClient":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def health(self) -> list[str]:
        data = self._request_json("GET", "/models")
        return [str(item.get("id")) for item in data.get("data", [])]

    def _request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        targets = self._endpoints.ordered()
        per_target_retries = self.retries if len(targets) == 1 else 0
        last_error: Exception | None = None
        for base in targets:
            try:
                data = request_json(
                    self._client,
                    method,
                    f"{base}{path}",
                    service=self.service,
                    payload=payload,
                    retries=per_target_retries,
                )
                self._endpoints.record_success(base)
                return data
            except ModelServiceError as exc:
                if not is_failover_error(exc):
                    raise
                last_error = exc
                self._endpoints.record_failure(base)
                logger.warning("%s request failed on %s: %s", self.service, base, exc)
        if isinstance(last_error, ModelServiceError):
            raise last_error
        raise ModelServiceError(self.service, "no model endpoint configured")

    def chat_stream(
        self,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        extra: dict[str, Any] | None = None,
    ) -> str:
        """Stream a chat completion and return the concatenated content.

        Streaming keeps bytes flowing during long generations; some NAT paths
        drop idle connections whose response only starts after tens of seconds.
        """
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if extra:
            payload.update(extra)
        targets = self._endpoints.ordered()
        per_target_retries = self.retries if len(targets) == 1 else 0
        last_error: Exception | None = None
        for base in targets:
            for attempt in range(per_target_retries + 1):
                try:
                    text = self._stream_once(payload, base)
                    self._endpoints.record_success(base)
                    return text
                except (httpx.HTTPError, ModelServiceError) as exc:
                    if not is_failover_error(exc):
                        raise
                    last_error = exc
                    if attempt < per_target_retries:
                        time.sleep(0.5 * (attempt + 1))
            self._endpoints.record_failure(base)
            logger.warning("%s stream failed on %s: %s", self.service, base, last_error)
        if isinstance(last_error, ModelServiceError):
            raise last_error
        raise ModelServiceError(
            self.service, f"stream failed: {last_error}"
        ) from last_error

    def _stream_once(self, payload: dict[str, Any], base_url: str) -> str:
        parts: list[str] = []
        usage: dict[str, Any] | None = None
        with self._client.stream(
            "POST",
            f"{base_url}/chat/completions",
            json=payload,
            headers=self._headers(),
        ) as response:
            if response.status_code >= 400:
                raise ModelServiceError(
                    self.service,
                    "temporary service error"
                    if response.status_code in (429, 500, 502, 503, 504)
                    else "request rejected",
                    status_code=response.status_code,
                    body=response.read().decode("utf-8", "replace")[:300],
                )
            for line in response.iter_lines():
                line = line.strip()
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    body = json.loads(data)
                except json.JSONDecodeError as exc:
                    raise ModelServiceError(
                        self.service, f"invalid stream chunk: {exc}", body=data[:200]
                    ) from exc
                if isinstance(body.get("usage"), dict):
                    usage = body["usage"]
                for choice in body.get("choices", []):
                    delta = choice.get("delta") or {}
                    content = delta.get("content")
                    if content:
                        parts.append(str(content))
        if usage:
            self._record_usage({"usage": usage})
        return "".join(parts)

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        json_mode: bool = False,
        enable_thinking: bool | None = None,
        extra: dict[str, Any] | None = None,
    ) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if enable_thinking is not None:
            payload["chat_template_kwargs"] = {
                "enable_thinking": bool(enable_thinking)
            }
        if extra:
            payload.update(extra)
        data = self._request_json("POST", "/chat/completions", payload)
        self._record_usage(data)
        try:
            return str(data["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelServiceError(
                self.service, f"unexpected response shape: {exc}", body=str(data)[:300]
            ) from exc

    def _record_usage(self, data: dict[str, Any]) -> None:
        """Accumulate OpenAI ``usage`` so jobs can account tokens per task."""
        usage = data.get("usage")
        if not isinstance(usage, dict):
            return
        recorded: dict[str, int] = {}
        with self._usage_lock:
            for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                value = usage.get(key)
                if isinstance(value, (int, float)):
                    recorded[key] = int(value)
                    self.usage[key] += int(value)
            if recorded:
                self.last_usage = recorded
                self.calls += 1


class GlmOcrClient(OpenAICompatibleClient):
    """GLM-OCR block client using the OpenAI-compatible vLLM endpoint."""

    service = "glm-ocr"

    def __init__(
        self,
        base_url: str,
        model: str = "GLM-OCR",
        *,
        fallback_base_url: str | None = None,
        failover_probe_seconds: float = 60.0,
        max_edge: int = 2048,
        min_edge: int = 32,
        max_tokens: int = 4096,
        stream: bool = True,
        api_key: str | None = None,
        timeout: float = 120.0,
        retries: int = 2,
        client: httpx.Client | None = None,
    ) -> None:
        super().__init__(
            base_url,
            model,
            fallback_base_url=fallback_base_url,
            failover_probe_seconds=failover_probe_seconds,
            api_key=api_key,
            timeout=timeout,
            retries=retries,
            client=client,
        )
        self.max_edge = max_edge
        self.min_edge = min_edge
        self.max_tokens = max_tokens
        self.stream = stream

    def _prepare_image(self, image_bytes: bytes) -> str:
        try:
            from PIL import Image
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise ModelServiceError(
                self.service, "Pillow is required to resize OCR images"
            ) from exc
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        width, height = image.size
        longest = max(width, height)
        if longest > self.max_edge:
            scale = self.max_edge / longest
            new_size = (
                max(self.min_edge, int(width * scale)),
                max(self.min_edge, int(height * scale)),
            )
            image = image.resize(new_size, Image.LANCZOS)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        return f"data:image/png;base64,{encoded}"

    def ocr_image(
        self,
        image_bytes: bytes,
        block_type: str = "text",
        *,
        prompt: str | None = None,
        max_tokens: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> str:
        text = prompt or GLM_OCR_PROMPTS.get(block_type, GLM_OCR_PROMPTS["text"])
        data_url = self._prepare_image(image_bytes)
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_url}},
                    {"type": "text", "text": text},
                ],
            }
        ]
        if self.stream:
            return self.chat_stream(
                messages,
                max_tokens=max_tokens or self.max_tokens,
                temperature=0.0,
                extra=extra,
            )
        return self.chat(
            messages,
            max_tokens=max_tokens or self.max_tokens,
            temperature=0.0,
            extra=extra,
        )


class QwenClient(OpenAICompatibleClient):
    """Qwen3.5-9B client; thinking is disabled by default for extraction."""

    service = "qwen"

    def __init__(
        self,
        base_url: str,
        model: str = "Qwen3.5-9B",
        *,
        fallback_base_url: str | None = None,
        failover_probe_seconds: float = 60.0,
        enable_thinking: bool = False,
        max_tokens: int = 4096,
        stream: bool = True,
        api_key: str | None = None,
        timeout: float = 120.0,
        retries: int = 2,
        client: httpx.Client | None = None,
    ) -> None:
        super().__init__(
            base_url,
            model,
            fallback_base_url=fallback_base_url,
            failover_probe_seconds=failover_probe_seconds,
            api_key=api_key,
            timeout=timeout,
            retries=retries,
            client=client,
        )
        self.enable_thinking = enable_thinking
        self.max_tokens = max_tokens
        self.stream = stream

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int | None = None,
        temperature: float = 0.0,
        json_mode: bool = False,
        enable_thinking: bool | None = None,
        extra: dict[str, Any] | None = None,
    ) -> str:
        thinking = self.enable_thinking if enable_thinking is None else enable_thinking
        if self.stream:
            overrides: dict[str, Any] = {
                "chat_template_kwargs": {"enable_thinking": bool(thinking)}
            }
            if json_mode:
                overrides["response_format"] = {"type": "json_object"}
            if extra:
                overrides.update(extra)
            return super().chat_stream(
                messages,
                max_tokens=max_tokens or self.max_tokens,
                temperature=temperature,
                extra=overrides,
            )
        return super().chat(
            messages,
            max_tokens=max_tokens or self.max_tokens,
            temperature=temperature,
            json_mode=json_mode,
            enable_thinking=thinking,
            extra=extra,
        )
