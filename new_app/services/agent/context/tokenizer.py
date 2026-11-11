"""Token counting: exact vLLM tokenizer with a conservative local fallback."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Protocol

import httpx
from hanson_contracts import ModelMessage

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_TOKEN_RE = re.compile(r"[A-Za-z0-9_./%≥≤+\-]+|[^\sA-Za-z0-9]")


class TokenizerUnavailable(RuntimeError):
    pass


class Tokenizer(Protocol):
    name: str

    async def count(self, text: str) -> int: ...

    async def count_messages(self, messages: Sequence[ModelMessage]) -> int: ...


class HeuristicTokenizer:
    """CJK-aware fallback; not character-only, but still an estimate."""

    name = "heuristic"

    async def count(self, text: str) -> int:
        value = text or ""
        cjk = len(_CJK_RE.findall(value))
        ascii_text = _CJK_RE.sub(" ", value)
        tokens = cjk
        for match in _TOKEN_RE.findall(ascii_text):
            # BPE-style estimate: long ASCII runs are split into ~4-char pieces.
            tokens += max(1, (len(match) + 3) // 4)
        return max(1, tokens)

    async def count_messages(self, messages: Sequence[ModelMessage]) -> int:
        total = 0
        for message in messages:
            total += await self.count(message.content) + 4
        return total


class RemoteTokenizer:
    """Exact tokenizer served by vLLM's /tokenize endpoint."""

    name = "remote"

    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        timeout_seconds: float = 10.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        base = base_url.strip().rstrip("/")
        self._root = base[: -len("/v1")] if base.endswith("/v1") else base
        self.model = model
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._owns_client = client is None
        self._cache: dict[str, int] = {}

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def count(self, text: str) -> int:
        value = text or ""
        cached = self._cache.get(value)
        if cached is not None:
            return cached
        try:
            response = await self._client.post(
                f"{self._root}/tokenize",
                json={"model": self.model, "prompt": value},
            )
        except httpx.HTTPError as exc:
            raise TokenizerUnavailable(str(exc)) from exc
        if response.status_code != 200:
            raise TokenizerUnavailable(f"tokenize HTTP {response.status_code}")
        payload = response.json()
        count = payload.get("count")
        if not isinstance(count, int):
            tokens = payload.get("tokens")
            if not isinstance(tokens, list):
                raise TokenizerUnavailable("tokenize response has no count/tokens")
            count = len(tokens)
        if len(self._cache) > 4096:
            self._cache.clear()
        self._cache[value] = count
        return count

    async def count_messages(self, messages: Sequence[ModelMessage]) -> int:
        total = 0
        for message in messages:
            total += await self.count(message.content) + 4
        return total


class FallbackTokenizer:
    """Use the remote tokenizer when available; record when degraded."""

    name = "remote+heuristic"

    def __init__(self, remote: Tokenizer | None, fallback: Tokenizer | None = None) -> None:
        self.remote = remote
        self.fallback = fallback or HeuristicTokenizer()
        self.degraded = remote is None

    async def count(self, text: str) -> int:
        if self.remote is None:
            return await self.fallback.count(text)
        try:
            return await self.remote.count(text)
        except TokenizerUnavailable:
            self.degraded = True
            return await self.fallback.count(text)

    async def count_messages(self, messages: Sequence[ModelMessage]) -> int:
        if self.remote is None:
            return await self.fallback.count_messages(messages)
        total = 0
        for message in messages:
            total += await self.count(message.content) + 4
        return total

    async def close(self) -> None:
        close = getattr(self.remote, "close", None)
        if close is not None:
            await close()


def build_tokenizer(
    mode: str,
    base_url: str = "",
    model: str = "",
) -> FallbackTokenizer:
    if mode == "remote" and base_url:
        return FallbackTokenizer(RemoteTokenizer(base_url, model))
    return FallbackTokenizer(None)
