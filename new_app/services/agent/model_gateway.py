"""OpenAI-compatible model gateway with debounced failover and JSON repair."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx
from hanson_contracts import ModelMessage, ModelResponse

logger = logging.getLogger(__name__)

FAILOVER_STATUS = {408, 425, 429, 500, 502, 503, 504}
JSON_REPAIR_PROMPT = (
    "You repair invalid JSON. Return only one JSON value that conforms to the "
    "requested schema. Do not add markdown fences or explanations."
)


class ModelGatewayError(RuntimeError):
    pass


class ModelUnavailable(ModelGatewayError):
    def __init__(self, message: str) -> None:
        super().__init__(message)


class ModelRequestError(ModelGatewayError):
    def __init__(self, message: str, status_code: int | None = None, body: str = "") -> None:
        self.status_code = status_code
        self.body = body
        super().__init__(message)


class ModelOutputInvalid(ModelGatewayError):
    pass


@dataclass(frozen=True)
class ModelEndpoint:
    name: str
    base_url: str

    @property
    def api_url(self) -> str:
        base = self.base_url.strip().rstrip("/")
        return base if base.endswith("/v1") else f"{base}/v1"


@dataclass
class EndpointState:
    failures: int = 0
    failure_started: float | None = None
    down_until: float = 0.0
    last_error: str = ""
    last_success: float = 0.0

    def available(self, now: float) -> bool:
        return now >= self.down_until


@dataclass(frozen=True)
class ModelGatewayConfig:
    model: str
    endpoints: tuple[ModelEndpoint, ...]
    failover_seconds: float = 10.0
    cooldown_seconds: float = 30.0
    timeout_seconds: float = 300.0
    connect_timeout_seconds: float = 5.0
    max_tokens: int = 4096
    temperature: float = 0.0
    api_key: str = ""
    max_context_tokens: int = 65536
    json_mode: bool = True
    enable_thinking: bool = False


@dataclass
class GatewayStatus:
    name: str
    url: str
    active: bool
    available: bool
    failures: int
    last_error: str = ""
    down_until: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "url": self.url,
            "active": self.active,
            "available": self.available,
            "failures": self.failures,
            "last_error": self.last_error,
            "down_until": self.down_until,
        }


def parse_json_value(text: str) -> Any:
    """Parse JSON, tolerating markdown fences and surrounding prose."""
    value = (text or "").strip()
    if not value:
        raise ModelOutputInvalid("empty model output")
    if value.startswith("```"):
        lines = value.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        value = "\n".join(lines).strip()
    try:
        return json.loads(value)
    except ValueError:
        decoder = json.JSONDecoder()
        for index, char in enumerate(value):
            if char not in "{[":
                continue
            try:
                parsed, _ = decoder.raw_decode(value[index:])
                return parsed
            except ValueError:
                continue
    raise ModelOutputInvalid("model output is not valid JSON")


class ModelGateway:
    def __init__(
        self,
        config: ModelGatewayConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        clock=time.monotonic,
    ) -> None:
        if not config.endpoints:
            raise ValueError("at least one model endpoint is required")
        self.config = config
        self._clock = clock
        self._states = {endpoint.name: EndpointState() for endpoint in config.endpoints}
        self._active = config.endpoints[0].name
        self._active_since = clock()
        self._client = httpx.AsyncClient(
            transport=transport,
            timeout=httpx.Timeout(
                config.timeout_seconds,
                connect=config.connect_timeout_seconds,
            ),
        )

    async def close(self) -> None:
        await self._client.aclose()

    # -- endpoint state ---------------------------------------------------
    @property
    def active_endpoint(self) -> ModelEndpoint:
        return self._endpoint(self._active)

    def _endpoint(self, name: str) -> ModelEndpoint:
        for endpoint in self.config.endpoints:
            if endpoint.name == name:
                return endpoint
        raise KeyError(name)

    def ordered_endpoints(self, now: float | None = None) -> list[ModelEndpoint]:
        now = self._clock() if now is None else now
        primary = self.config.endpoints[0]
        active = self._endpoint(self._active)
        if (
            active.name != primary.name
            and self._states[primary.name].available(now)
            and now - self._active_since >= self.config.cooldown_seconds
        ):
            candidates = [primary, active]
        else:
            candidates = [active]
        candidates += [
            endpoint
            for endpoint in self.config.endpoints
            if endpoint.name not in {item.name for item in candidates}
        ]
        return candidates

    def _mark_failure(self, endpoint: ModelEndpoint, now: float, error: str) -> bool:
        state = self._states[endpoint.name]
        state.failures += 1
        state.last_error = error[:500]
        if state.failure_started is None:
            state.failure_started = now
        if now - state.failure_started >= self.config.failover_seconds:
            state.down_until = now + self.config.cooldown_seconds
            return True
        return False

    def _mark_success(self, endpoint: ModelEndpoint, now: float) -> None:
        state = self._states[endpoint.name]
        state.failures = 0
        state.failure_started = None
        state.down_until = 0.0
        state.last_error = ""
        state.last_success = now
        primary = self.config.endpoints[0].name
        # A short blip must not move the active endpoint to a fallback.
        if endpoint.name == primary or not self._states[self._active].available(now):
            self._active = endpoint.name
            self._active_since = now

    def _advance_active(self, now: float) -> None:
        candidates = [
            endpoint
            for endpoint in self.config.endpoints
            if endpoint.name != self._active and self._states[endpoint.name].available(now)
        ]
        if candidates:
            self._active = candidates[0].name
            self._active_since = now

    def status(self) -> list[GatewayStatus]:
        now = self._clock()
        return [
            GatewayStatus(
                name=endpoint.name,
                url=endpoint.api_url,
                active=endpoint.name == self._active,
                available=self._states[endpoint.name].available(now),
                failures=self._states[endpoint.name].failures,
                last_error=self._states[endpoint.name].last_error,
                down_until=self._states[endpoint.name].down_until,
            )
            for endpoint in self.config.endpoints
        ]

    async def probe(
        self,
        *,
        timeout_seconds: float = 2.0,
        down_seconds: float | None = None,
    ) -> list[dict[str, Any]]:
        """Check /models and the configured model name; update endpoint health."""
        now = self._clock()
        down_for = self.config.cooldown_seconds if down_seconds is None else down_seconds
        healthy: list[ModelEndpoint] = []
        entries: list[dict[str, Any]] = []
        headers = (
            {"Authorization": f"Bearer {self.config.api_key}"}
            if self.config.api_key
            else {}
        )
        for endpoint in self.config.endpoints:
            state = self._states[endpoint.name]
            models: list[str] = []
            error = ""
            try:
                response = await self._client.get(
                    f"{endpoint.api_url}/models",
                    headers=headers,
                    timeout=timeout_seconds,
                )
                if response.status_code == 200:
                    try:
                        payload = response.json()
                        models = [
                            str(item.get("id"))
                            for item in payload.get("data", [])
                            if isinstance(item, dict)
                        ]
                    except ValueError:
                        error = "invalid models payload"
                else:
                    error = f"HTTP {response.status_code}"
            except httpx.HTTPError as exc:
                error = str(exc)[:500]
            if not error and self.config.model not in models:
                error = f"model {self.config.model!r} not in {models}"
            if error:
                state.down_until = now + down_for
                if state.failure_started is None:
                    state.failure_started = now
                state.last_error = error
                entries.append(
                    {
                        "name": endpoint.name,
                        "url": endpoint.api_url,
                        "ok": False,
                        "models": models,
                        "error": error,
                    }
                )
                continue
            state.failures = 0
            state.failure_started = None
            state.down_until = 0.0
            state.last_error = ""
            healthy.append(endpoint)
            entries.append(
                {
                    "name": endpoint.name,
                    "url": endpoint.api_url,
                    "ok": True,
                    "models": models,
                    "error": "",
                }
            )
        if healthy:
            self._active = healthy[0].name
            self._active_since = now
        return entries

    async def probe_loop(self, interval_seconds: float = 60.0) -> None:
        while True:
            try:
                await self.probe(down_seconds=interval_seconds + 10)
            except Exception:  # noqa: BLE001 - background probe must not die
                logger.exception("model endpoint probe failed")
            await asyncio.sleep(interval_seconds)

    # -- requests ---------------------------------------------------------
    async def chat(
        self,
        messages: list[ModelMessage],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
        json_mode: bool | None = None,
    ) -> ModelResponse:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": [message.model_dump() for message in messages],
            "temperature": self.config.temperature if temperature is None else temperature,
            "max_tokens": max_tokens or self.config.max_tokens,
            "stream": False,
        }
        if json_mode is None:
            json_mode = self.config.json_mode
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if self.config.enable_thinking is not None:
            payload["chat_template_kwargs"] = {
                "enable_thinking": bool(self.config.enable_thinking)
            }
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"

        last_error = ""
        for endpoint in self.ordered_endpoints():
            started = time.monotonic()
            try:
                data = await self._post(endpoint, payload, headers)
            except ModelRequestError as exc:
                # 4xx request errors are not endpoint failures.
                if exc.status_code == 400 and (
                    "response_format" in exc.body or "chat_template_kwargs" in exc.body
                ):
                    payload.pop("response_format", None)
                    payload.pop("chat_template_kwargs", None)
                    try:
                        data = await self._post(endpoint, payload, headers)
                    except ModelUnavailable as retry_exc:
                        last_error = str(retry_exc)
                        now = self._clock()
                        if self._mark_failure(endpoint, now, last_error):
                            self._advance_active(now)
                        continue
                else:
                    raise
            except (httpx.HTTPError, ModelUnavailable) as exc:
                last_error = str(exc)
                now = self._clock()
                if self._mark_failure(endpoint, now, last_error):
                    self._advance_active(now)
                continue
            now = self._clock()
            self._mark_success(endpoint, now)
            usage = data.get("usage") if isinstance(data, dict) else {}
            usage = usage if isinstance(usage, dict) else {}
            try:
                content = str(data["choices"][0]["message"]["content"])
            except (KeyError, IndexError, TypeError) as exc:
                raise ModelOutputInvalid(f"unexpected model response: {exc}") from exc
            return ModelResponse(
                content=content,
                prompt_tokens=int(usage.get("prompt_tokens") or 0),
                completion_tokens=int(usage.get("completion_tokens") or 0),
                total_tokens=int(usage.get("total_tokens") or 0),
                endpoint=endpoint.name,
                model=self.config.model,
                latency_ms=int((time.monotonic() - started) * 1000),
            )
        raise ModelUnavailable(f"all model endpoints failed: {last_error}")

    async def _post(
        self,
        endpoint: ModelEndpoint,
        payload: dict[str, Any],
        headers: dict[str, str],
    ) -> dict[str, Any]:
        try:
            response = await self._client.post(
                f"{endpoint.api_url}/chat/completions",
                json=payload,
                headers=headers,
            )
        except httpx.HTTPError as exc:
            raise ModelUnavailable(f"{endpoint.name}: {exc}") from exc
        if response.status_code in FAILOVER_STATUS:
            raise ModelUnavailable(
                f"{endpoint.name}: temporary HTTP {response.status_code}"
            )
        if response.status_code >= 400:
            raise ModelRequestError(
                f"{endpoint.name}: HTTP {response.status_code}",
                status_code=response.status_code,
                body=response.text[:500],
            )
        try:
            return response.json()
        except ValueError as exc:
            raise ModelOutputInvalid(f"{endpoint.name}: response is not JSON") from exc

    async def chat_json(
        self,
        messages: list[ModelMessage],
        *,
        max_tokens: int | None = None,
        repair: bool = True,
    ) -> tuple[Any, ModelResponse]:
        response = await self.chat(messages, max_tokens=max_tokens, json_mode=True)
        try:
            return parse_json_value(response.content), response
        except ModelOutputInvalid:
            if not repair:
                raise
        repair_messages = [
            ModelMessage(role="system", content=JSON_REPAIR_PROMPT),
            ModelMessage(
                role="user",
                content=(
                    "Repair the following model output into valid JSON. "
                    "Keep all fields and values.\n\n"
                    f"{response.content[:12000]}"
                ),
            ),
        ]
        repaired = await self.chat(repair_messages, max_tokens=max_tokens, json_mode=True)
        repaired = repaired.model_copy(
            update={
                "prompt_tokens": response.prompt_tokens + repaired.prompt_tokens,
                "completion_tokens": response.completion_tokens + repaired.completion_tokens,
                "total_tokens": response.total_tokens + repaired.total_tokens,
            }
        )
        try:
            return parse_json_value(repaired.content), repaired
        except ModelOutputInvalid as exc:
            raise ModelOutputInvalid(
                f"JSON repair failed: {exc}; raw={repaired.content[:500]}"
            ) from exc

    async def health(self) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for endpoint in self.config.endpoints:
            try:
                response = await self._client.get(
                    f"{endpoint.api_url}/models",
                    headers={"Authorization": f"Bearer {self.config.api_key}"}
                    if self.config.api_key
                    else {},
                )
                ok = response.status_code == 200
                detail = ""
                if ok:
                    try:
                        detail = str([item.get("id") for item in response.json().get("data", [])])
                    except ValueError:
                        detail = "invalid models payload"
                else:
                    detail = f"HTTP {response.status_code}"
            except httpx.HTTPError as exc:
                ok = False
                detail = str(exc)
            results.append(
                {
                    "name": endpoint.name,
                    "url": endpoint.api_url,
                    "ok": ok,
                    "detail": detail,
                }
            )
        return results
