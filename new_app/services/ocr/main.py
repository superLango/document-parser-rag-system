import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from services.common import create_app
from services.shared.storage import build_store

from .api import router
from .config import settings
from .service import get_store, set_store

logging.basicConfig(level=logging.WARNING)
logging.getLogger("services.ocr").setLevel(logging.INFO)


async def _probe(url: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            await client.get(url)
        return "ok"
    except Exception:  # noqa: BLE001 - 探针只报告状态
        return "error"


async def _readiness() -> dict[str, str]:
    """就绪探针：对象存储与已配置的模型端点可达。"""
    checks: dict[str, str] = {}
    try:
        await get_store().ensure_ready()
        checks["object_store"] = "ok"
    except Exception:  # noqa: BLE001
        checks["object_store"] = "error"
    for name, url in (
        ("layout_model", settings.layout_base_url),
        ("glm_model", settings.glm_ocr_base_url),
    ):
        checks[name] = await _probe(url) if url else "not_configured"
    status = "ready" if "error" not in checks.values() else "not_ready"
    return {"status": status, **checks}


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    store = build_store(settings.storage_config())
    await store.ensure_ready()
    set_store(store)
    yield


app = create_app("ocr", lifespan=lifespan, readiness=_readiness)
app.include_router(router)
