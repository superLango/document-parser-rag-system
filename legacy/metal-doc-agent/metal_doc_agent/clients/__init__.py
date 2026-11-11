"""Model service clients and builders."""

from __future__ import annotations

from ..settings import Settings
from .base import ModelServiceError
from .layout import LayoutBlock, LayoutClient
from .openai import (
    GLM_OCR_PROMPTS,
    GlmOcrClient,
    OpenAICompatibleClient,
    QwenClient,
)

__all__ = [
    "GLM_OCR_PROMPTS",
    "GlmOcrClient",
    "LayoutBlock",
    "LayoutClient",
    "ModelServiceError",
    "OpenAICompatibleClient",
    "QwenClient",
    "build_glm_client",
    "build_layout_client",
    "build_qwen_client",
]


def _require(url: str | None, name: str) -> str:
    if not url:
        raise ModelServiceError(name, f"{name} base URL is not configured")
    return url


def build_glm_client(settings: Settings) -> GlmOcrClient:
    return GlmOcrClient(
        _require(settings.glm_ocr_base_url, "glm-ocr"),
        settings.glm_ocr_model,
        fallback_base_url=settings.glm_ocr_fallback_base_url,
        failover_probe_seconds=settings.model_failover_probe_seconds,
        max_edge=settings.glm_ocr_max_edge,
        min_edge=settings.glm_ocr_min_edge,
        max_tokens=settings.glm_ocr_max_tokens,
        stream=settings.glm_ocr_stream,
        api_key=settings.api_key,
        timeout=settings.glm_ocr_timeout,
        retries=settings.model_retries,
    )


def build_qwen_client(settings: Settings) -> QwenClient:
    return QwenClient(
        _require(settings.qwen_base_url, "qwen"),
        settings.qwen_model,
        fallback_base_url=settings.qwen_fallback_base_url,
        failover_probe_seconds=settings.model_failover_probe_seconds,
        enable_thinking=settings.qwen_enable_thinking,
        max_tokens=settings.qwen_max_tokens,
        stream=settings.qwen_stream,
        api_key=settings.api_key,
        timeout=settings.request_timeout,
        retries=settings.model_retries,
    )


def build_layout_client(settings: Settings) -> LayoutClient:
    return LayoutClient(
        _require(settings.layout_service_url, "layout"),
        fallback_url=settings.layout_service_fallback_url,
        fallback_urls=settings.layout_service_fallback_urls,
        failover_probe_seconds=settings.model_failover_probe_seconds,
        timeout=settings.layout_timeout_seconds,
        retries=settings.model_retries,
        token=settings.layout_service_token,
    )
