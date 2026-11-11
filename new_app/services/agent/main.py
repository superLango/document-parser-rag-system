from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from services.common import create_app

from .api import router, set_runtime
from .config import settings
from .runtime import AgentRuntime


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    runtime = AgentRuntime(settings)
    await runtime.start()
    set_runtime(runtime)
    try:
        yield
    finally:
        set_runtime(None)
        await runtime.close()


app = create_app("agent", lifespan=lifespan)
app.include_router(router)
