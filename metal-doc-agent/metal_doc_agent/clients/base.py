"""Shared HTTP helpers for model service clients."""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

FAILOVER_STATUS = {429, 500, 502, 503, 504}


class ModelServiceError(RuntimeError):
    """Raised when a model service is unreachable or returns an error."""

    def __init__(
        self,
        service: str,
        message: str,
        *,
        status_code: int | None = None,
        body: str | None = None,
    ) -> None:
        self.service = service
        self.status_code = status_code
        self.body = body
        detail = f"{service}: {message}"
        if status_code is not None:
            detail += f" (HTTP {status_code})"
        if body:
            detail += f": {body[:300]}"
        super().__init__(detail)


def is_failover_error(exc: BaseException) -> bool:
    """Only transport errors and temporary HTTP errors should switch targets."""

    if isinstance(exc, ModelServiceError):
        return exc.status_code is None or exc.status_code in FAILOVER_STATUS
    return isinstance(exc, httpx.HTTPError)


class FailoverEndpoints:
    """Primary/fallback endpoints with failover memory and recovery probing.

    All clients built for the same endpoint list share one instance, so a
    switch made by one document/job is reused by the next one in the same
    worker process. The primary is retried after ``probe_interval`` seconds.
    """

    _registry: dict[tuple[tuple[str, ...], float], "FailoverEndpoints"] = {}
    _registry_lock = threading.Lock()

    def __init__(
        self,
        primary: str,
        *fallbacks: str,
        probe_interval: float = 60.0,
    ) -> None:
        endpoints: list[str] = []
        for value in (primary, *fallbacks):
            url = (value or "").strip().rstrip("/")
            if url and url not in endpoints:
                endpoints.append(url)
        if not endpoints:
            raise ValueError("at least one model endpoint is required")
        self.endpoints = tuple(endpoints)
        self.primary = endpoints[0]
        self.probe_interval = max(0.0, float(probe_interval))
        self._active = self.primary
        self._failed_at = 0.0
        self._lock = threading.Lock()

    @classmethod
    def shared(
        cls,
        primary: str,
        *fallbacks: str,
        probe_interval: float = 60.0,
    ) -> "FailoverEndpoints":
        endpoints: list[str] = []
        for value in (primary, *fallbacks):
            url = (value or "").strip().rstrip("/")
            if url and url not in endpoints:
                endpoints.append(url)
        key = (tuple(endpoints), max(0.0, float(probe_interval)))
        with cls._registry_lock:
            instance = cls._registry.get(key)
            if instance is None:
                instance = cls(primary, *fallbacks, probe_interval=probe_interval)
                cls._registry[key] = instance
            return instance

    @property
    def active(self) -> str:
        with self._lock:
            return self._active

    def ordered(self) -> list[str]:
        with self._lock:
            if len(self.endpoints) == 1:
                return list(self.endpoints)
            if (
                self._active != self.primary
                and time.monotonic() - self._failed_at < self.probe_interval
            ):
                first = self._active
            else:
                first = self.primary
            return [first] + [url for url in self.endpoints if url != first]

    def record_success(self, url: str) -> None:
        with self._lock:
            if self._active != url and url == self.primary:
                logger.info("model endpoint recovered: %s", url)
            self._active = url
            if url == self.primary:
                self._failed_at = 0.0

    def record_failure(self, url: str) -> None:
        with self._lock:
            if len(self.endpoints) == 1 or url not in self.endpoints:
                return
            index = self.endpoints.index(url)
            if index + 1 < len(self.endpoints):
                target = self.endpoints[index + 1]
            else:
                target = self.endpoints[-1]
            if target != self._active:
                logger.warning(
                    "model endpoint %s failed; switching to %s", url, target
                )
            self._active = target
            self._failed_at = time.monotonic()


def http_timeout(total: float, *, connect: float = 5.0) -> httpx.Timeout:
    """Keep read/generation time generous but fail over quickly on connect."""

    return httpx.Timeout(total, connect=min(float(connect), float(total)))


def api_base(url: str) -> str:
    """Normalize an OpenAI-compatible base URL to end with /v1."""
    base = url.rstrip("/")
    return base if base.endswith("/v1") else f"{base}/v1"


def service_root(url: str) -> str:
    """Return the service root without a trailing /v1."""
    base = url.rstrip("/")
    return base[: -len("/v1")] if base.endswith("/v1") else base


def request_json(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    service: str,
    payload: dict[str, Any] | None = None,
    retries: int = 2,
) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            response = client.request(method, url, json=payload)
            if response.status_code in (429, 500, 502, 503, 504):
                raise ModelServiceError(
                    service,
                    "temporary service error",
                    status_code=response.status_code,
                    body=response.text,
                )
            if response.status_code >= 400:
                raise ModelServiceError(
                    service,
                    "request rejected",
                    status_code=response.status_code,
                    body=response.text,
                )
            return response.json()
        except (httpx.HTTPError, ModelServiceError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(0.5 * (attempt + 1))
                continue
            break
    if isinstance(last_error, ModelServiceError):
        raise last_error
    raise ModelServiceError(service, f"request failed: {last_error}") from last_error
