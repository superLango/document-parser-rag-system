from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from services.common import create_app
from services.shared.storage import build_store

from .api import router, set_service
from .config import settings
from .executor import build_executor
from .service import SandboxService


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    store = build_store(settings.storage_config())
    await store.ensure_ready()
    executor = build_executor(settings)
    set_service(SandboxService(settings, store, executor))
    try:
        yield
    finally:
        set_service(None)
        await executor.close()


app = create_app("sandbox", lifespan=lifespan)
app.include_router(router)
