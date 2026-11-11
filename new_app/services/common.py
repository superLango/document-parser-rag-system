from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

SERVICE_VERSION = "0.0.0"


def create_app(
    service_name: str,
    version: str = SERVICE_VERSION,
    lifespan: Any | None = None,
) -> FastAPI:
    app = FastAPI(title=f"Hanson {service_name}", version=version, lifespan=lifespan)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok", "service": service_name, "version": version}

    @app.get("/readyz")
    def readyz() -> dict[str, str]:
        return {"status": "ready", "service": service_name, "version": version}

    return app


@asynccontextmanager
async def empty_lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
