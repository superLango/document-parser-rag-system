import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from services.common import create_app
from services.shared.storage import build_store

from .api import router
from .config import settings
from .cross_standard_api import router as cross_standard_router
from .db import SessionLocal, init_db
from .dictionary.api import router as dictionary_router
from .feedback.api import router as feedback_router
from .integration_api import IntegrationError
from .integration_api import router as integration_router
from .workflow import get_store, resume_incomplete_runs, set_store

logger = logging.getLogger(__name__)

# uvicorn 只配置自己的 logger；不显式配置时编排侧的 warning/异常不会进容器日志。
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


async def _readiness() -> dict[str, str]:
    """就绪探针：DB、对象存储、配方注册任一不可用即 503。"""
    checks: dict[str, str] = {}
    try:
        async with SessionLocal() as session:
            await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:  # noqa: BLE001 - 探针只报告状态
        checks["database"] = "error"
    try:
        await get_store().ensure_ready()
        checks["object_store"] = "ok"
    except Exception:  # noqa: BLE001
        checks["object_store"] = "error"
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            response = await client.get(
                f"{settings.recipe_registry_url.rstrip('/')}/healthz"
            )
        checks["recipe_registry"] = "ok" if response.status_code == 200 else "error"
    except Exception:  # noqa: BLE001
        checks["recipe_registry"] = "error"
    status = "ready" if all(value == "ok" for value in checks.values()) else "not_ready"
    return {"status": status, **checks}


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    if settings.simulation_mode:
        logger.warning(
            "SIMULATION_MODE active: ocr=%s route=%s sandbox=%s review=%s; "
            "results are marked simulated and cannot be accepted",
            settings.ocr_use_fake,
            settings.route_use_fake,
            settings.sandbox_use_fake,
            settings.review_use_fake,
        )
    await init_db()
    store = build_store(settings.storage_config())
    await store.ensure_ready()
    set_store(store)
    await resume_incomplete_runs()
    yield


app = create_app("orchestration", lifespan=lifespan, readiness=_readiness)
app.include_router(router)
app.include_router(feedback_router)
app.include_router(dictionary_router)
app.include_router(cross_standard_router)
app.include_router(integration_router)

INTEGRATION_ERROR_CODES = {
    400: 10001,
    401: 20001,
    403: 20003,
    404: 30017,
    409: 30019,
    413: 10001,
    422: 10001,
    429: 10017,
}


def _integration_error(request: Request, status_code: int, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "code": INTEGRATION_ERROR_CODES.get(status_code, 50000),
            "message": message,
            "data": None,
            "trace_id": request.headers.get("x-request-id") or uuid.uuid4().hex,
        },
    )


@app.exception_handler(IntegrationError)
async def _integration_exception(request: Request, exc: IntegrationError) -> JSONResponse:
    return _integration_error(request, exc.status_code, exc.message)


@app.exception_handler(StarletteHTTPException)
async def _http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    if request.url.path.startswith("/internal/integration"):
        return _integration_error(request, exc.status_code, str(exc.detail))
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(RequestValidationError)
async def _validation_exception(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    if request.url.path.startswith("/internal/integration"):
        return _integration_error(request, 400, "参数校验失败")
    from fastapi.encoders import jsonable_encoder

    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(exc.errors())})
