import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from services.common import create_app

from .api import router, set_asset_registry, set_registry
from .assets import AssetRegistry
from .registry import RecipeRegistry

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    registry = RecipeRegistry()
    set_registry(registry)
    assets = AssetRegistry()
    set_asset_registry(assets)
    for issue in registry.governance() + assets.governance():
        logger.warning("version governance: %s", issue)
    yield


app = create_app("recipe-registry", lifespan=lifespan)
app.include_router(router)
