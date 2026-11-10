"""Extractor factory."""

from __future__ import annotations

from ..settings import Settings
from .base import Extractor
from .mock import MockExtractor
from .qwen import QwenExtractor


def build_extractor(settings: Settings) -> Extractor:
    backend = settings.extractor_backend
    if backend == "mock":
        return MockExtractor()
    if backend == "qwen":
        return QwenExtractor(settings)
    raise ValueError(f"unknown extractor backend: {backend}")
