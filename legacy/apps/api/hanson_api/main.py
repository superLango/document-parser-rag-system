"""Composed platform + engine ASGI entry point.

``uvicorn hanson_api.main:app`` is the canonical entry point for containers,
K8s and local runs. ``apps/api/main.py`` stays as a thin compatibility shim for
``uvicorn main:app --app-dir apps/api``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from .config import ENGINE_ROOT, PlatformSettings

ENGINE = Path(os.environ.get("HANSON_ENGINE_ROOT") or ENGINE_ROOT)
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from metal_doc_agent.logging_setup import configure_logging  # noqa: E402
from metal_doc_agent.settings import Settings  # noqa: E402

from .app import build_app  # noqa: E402
from .startup import validate_startup  # noqa: E402

configure_logging()
settings = PlatformSettings.from_env()
engine_settings = Settings.from_env()
validate_startup(settings, engine_settings)

app = build_app(
    settings,
    engine_settings,
    engine_internal_token=os.environ.get("ENGINE_INTERNAL_TOKEN"),
)
