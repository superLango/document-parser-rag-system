from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from services.common import create_app

from .api import router
from .db import init_db
from .storage import build_store
from .workflow import resume_incomplete_runs, set_store


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    await init_db()
    store = build_store()
    await store.ensure_ready()
    set_store(store)
    await resume_incomplete_runs()
    yield


app = create_app("orchestration", lifespan=lifespan)
app.include_router(router)
