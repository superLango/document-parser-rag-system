"""Compatibility entry point for ``uvicorn main:app --app-dir apps/api``.

The composed app lives in :mod:`hanson_api.main`; containers and K8s use
``uvicorn hanson_api.main:app`` directly.
"""

from __future__ import annotations

from hanson_api.main import app  # noqa: F401

__all__ = ["app"]
