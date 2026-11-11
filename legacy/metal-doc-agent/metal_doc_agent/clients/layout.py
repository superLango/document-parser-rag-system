"""Client for the PP-DocLayoutV3 HTTP service."""

from __future__ import annotations

import base64
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from .base import (
    FailoverEndpoints,
    ModelServiceError,
    http_timeout,
    is_failover_error,
    request_json,
    service_root,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LayoutBlock:
    type: str
    bbox: tuple[float, float, float, float]
    order: int
    confidence: float
    structural: dict[str, Any] = field(default_factory=dict)


class LayoutClient:
    service = "layout"

    def __init__(
        self,
        base_url: str,
        *,
        fallback_url: str | None = None,
        fallback_urls: list[str] | tuple[str, ...] | None = None,
        failover_probe_seconds: float = 60.0,
        timeout: float = 180.0,
        retries: int = 1,
        token: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.root = service_root(base_url)
        fallbacks = [
            service_root(url)
            for url in ([fallback_url] if fallback_url else [])
            + list(fallback_urls or [])
            if url
        ]
        self._endpoints = FailoverEndpoints.shared(
            self.root,
            *fallbacks,
            probe_interval=failover_probe_seconds,
        )
        self.retries = retries
        headers = {"X-Layout-Token": token} if token else None
        self._client = client or httpx.Client(
            timeout=http_timeout(timeout),
            trust_env=False,
            headers=headers,
        )
        self._owns_client = client is None

    @property
    def active_url(self) -> str:
        return self._endpoints.active

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "LayoutClient":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def health(self) -> dict[str, Any]:
        error: ModelServiceError | None = None
        targets = self._endpoints.ordered()
        per_target_retries = self.retries if len(targets) == 1 else 0
        for root in targets:
            try:
                data = request_json(
                    self._client,
                    "GET",
                    f"{root}/health",
                    service=self.service,
                    retries=per_target_retries,
                )
                self._endpoints.record_success(root)
                return data
            except ModelServiceError as exc:
                if not is_failover_error(exc):
                    raise
                error = exc
                self._endpoints.record_failure(root)
                logger.warning("layout health failed on %s: %s", root, exc)
        raise error if error else ModelServiceError(self.service, "no layout target")

    def analyze(
        self,
        image_bytes: bytes,
        *,
        page_index: int = 1,
        dpi: int = 200,
        width: float | None = None,
        height: float | None = None,
    ) -> list[LayoutBlock]:
        payload: dict[str, Any] = {
            "page_index": page_index,
            "dpi": dpi,
            "image_base64": base64.b64encode(image_bytes).decode("ascii"),
        }
        if width is not None:
            payload["width"] = width
        if height is not None:
            payload["height"] = height

        data: dict[str, Any] | None = None
        error: ModelServiceError | None = None
        targets = self._endpoints.ordered()
        per_target_retries = self.retries if len(targets) == 1 else 0
        for root in targets:
            started = time.monotonic()
            try:
                data = request_json(
                    self._client,
                    "POST",
                    f"{root}/v1/layout",
                    service=self.service,
                    payload=payload,
                    retries=per_target_retries,
                )
                self._endpoints.record_success(root)
                elapsed = time.monotonic() - started
                if elapsed > 5.0:
                    logger.warning(
                        "slow layout page=%s target=%s elapsed=%.1fs",
                        page_index,
                        root,
                        elapsed,
                    )
                break
            except ModelServiceError as exc:
                if not is_failover_error(exc):
                    raise
                error = exc
                self._endpoints.record_failure(root)
                logger.warning(
                    "layout analyze failed on %s page=%s after %.1fs: %s",
                    root,
                    page_index,
                    time.monotonic() - started,
                    exc,
                )
        if data is None:
            raise error if error else ModelServiceError(self.service, "no layout target")
        blocks: list[LayoutBlock] = []
        for item in data.get("blocks", []):
            bbox = item.get("bbox") or [0.0, 0.0, 0.0, 0.0]
            if len(bbox) != 4:
                raise ModelServiceError(
                    self.service, f"invalid bbox: {bbox}", body=str(item)[:200]
                )
            blocks.append(
                LayoutBlock(
                    type=str(item.get("type", "text")),
                    bbox=tuple(float(value) for value in bbox),  # type: ignore[arg-type]
                    order=int(item.get("order", 0)),
                    confidence=float(item.get("confidence", 0.0)),
                    structural=item.get("structural") or {},
                )
            )
        return blocks
