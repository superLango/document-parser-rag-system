from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from services.common import create_app

from .api import router, set_service
from .config import settings
from .service import ReviewService


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    set_service(ReviewService(settings))
    try:
        yield
    finally:
        set_service(None)


app = create_app("review", lifespan=lifespan)
app.include_router(router)
