from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from services.common import create_app

from .api import router, set_registry
from .registry import RecipeRegistry


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    set_registry(RecipeRegistry())
    yield


app = create_app("recipe-registry", lifespan=lifespan)
app.include_router(router)
