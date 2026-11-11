"""Platform ASGI app composition and security boundary.

The platform port exposes only the platform API plus engine health/metrics.
Engine data endpoints (``/v1/jobs*``, ``/v1/recipes``, ``/v1/batches``) are
removed by default; if they must be exposed, every request needs
``X-Engine-Token``. The engine business dictionary route is always replaced by
the authenticated platform route.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from http import HTTPStatus
from typing import Any

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError
from starlette.exceptions import HTTPException as StarletteHTTPException

from metal_doc_agent.api import create_app as create_engine_app
from metal_doc_agent.settings import Settings

from .config import PlatformSettings
from .router import create_platform_router

ENGINE_PUBLIC_PATHS = {
    "/health",
    "/ready",
    "/metrics",
    "/openapi.json",
    "/docs",
    "/docs/oauth2-redirect",
    "/redoc",
}
ENGINE_GUARDED_PREFIXES = ("/v1/jobs", "/v1/recipes", "/v1/batches")
PLATFORM_DICTIONARY_PATH = "/v1/business-dictionary"
INTEGRATION_PREFIX = "/api/v1/integration"
INTEGRATION_ERROR_CODES = {
    400: 10001,
    401: 20001,
    403: 20003,
    404: 30017,
    409: 30019,
    413: 10001,
    422: 10001,
}
JOB_ID_RE = re.compile(r"/(?:tasks|jobs)/([A-Za-z0-9_-]{4,64})")
access_logger = logging.getLogger("hanson.access")
error_logger = logging.getLogger("hanson.error")

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
}
API_CSP = "default-src 'none'; frame-ancestors 'none'"


def restrict_engine_routes(app: Any, *, expose_engine: bool) -> None:
    """Drop engine data routes unless explicitly exposed with a token."""

    routes = []
    for route in app.router.routes:
        path = getattr(route, "path", "")
        if path == PLATFORM_DICTIONARY_PATH:
            # Always served by the authenticated platform route.
            continue
        if expose_engine or path in ENGINE_PUBLIC_PATHS:
            routes.append(route)
    app.router.routes = routes


def problem_response(
    request: Request, status_code: int, detail: Any, headers: dict[str, str] | None = None
) -> JSONResponse:
    """RFC 9457 problem details while keeping the legacy ``detail`` field."""

    try:
        title = HTTPStatus(status_code).phrase
    except ValueError:
        title = "Request failed"
    return JSONResponse(
        status_code=status_code,
        content={
            "type": "about:blank",
            "title": title,
            "status": status_code,
            "detail": detail,
            "instance": request.url.path,
        },
        media_type="application/problem+json",
        headers=headers,
    )


def integration_error_response(
    request: Request, status_code: int, detail: Any
) -> JSONResponse:
    """hansonDoc_RAG 一站式接口的旧响应信封（code/message/data/trace_id）。"""

    return JSONResponse(
        status_code=status_code,
        content={
            "code": INTEGRATION_ERROR_CODES.get(status_code, 50000),
            "message": detail if isinstance(detail, str) else "请求失败",
            "data": None if isinstance(detail, str) else detail,
            "trace_id": getattr(request.state, "request_id", "") or "",
        },
    )


def build_app(
    settings: PlatformSettings,
    engine_settings: Settings,
    *,
    engine_internal_token: str | None = None,
) -> Any:
    app = create_engine_app(engine_settings)
    restrict_engine_routes(app, expose_engine=bool(engine_internal_token))
    app.state.error_counts = {}
    platform_router = create_platform_router(settings, engine_settings, app=app)
    app.state.platform_router = platform_router
    app.include_router(platform_router)

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(  # noqa: ANN202
        request: Request, exc: StarletteHTTPException
    ):
        if request.url.path.startswith(INTEGRATION_PREFIX):
            return integration_error_response(request, exc.status_code, exc.detail)
        return problem_response(request, exc.status_code, exc.detail, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(  # noqa: ANN202
        request: Request, exc: RequestValidationError
    ):
        if request.url.path.startswith(INTEGRATION_PREFIX):
            return integration_error_response(request, 400, "参数校验失败")
        return problem_response(request, 422, jsonable_encoder(exc.errors()))

    @app.exception_handler(DBAPIError)
    async def database_exception_handler(  # noqa: ANN202
        request: Request, exc: DBAPIError
    ):
        return problem_response(request, 503, "database unavailable")

    if engine_internal_token:

        @app.middleware("http")
        async def engine_guard(request: Request, call_next):  # noqa: ANN001, ANN201
            if request.url.path.startswith(ENGINE_GUARDED_PREFIXES):
                if request.headers.get("X-Engine-Token") != engine_internal_token:
                    return JSONResponse(
                        status_code=401,
                        content={"detail": "engine token required"},
                    )
            return await call_next(request)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):  # noqa: ANN001, ANN201
        response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            # 嵌入式部署需要允许被其他系统 iframe 引用。
            if name == "X-Frame-Options" and settings.allow_embed:
                continue
            response.headers.setdefault(name, value)
        if settings.allow_embed:
            response.headers.setdefault(
                "Content-Security-Policy", "frame-ancestors *"
            )
        if request.url.path.startswith(("/v1/", "/platform/")):
            response.headers.setdefault("Content-Security-Policy", API_CSP)
        if request.url.path.startswith("/v1/auth"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.middleware("http")
    async def request_logging(request: Request, call_next):  # noqa: ANN001, ANN201
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
        request.state.request_id = request_id
        started = time.perf_counter()
        path = request.url.path
        match = JOB_ID_RE.search(path)
        base = {
            "event": "request",
            "request_id": request_id,
            "method": request.method,
            "path": path,
        }
        if match:
            base["job_id"] = match.group(1)
        try:
            response = await call_next(request)
        except Exception:
            if path.startswith(("/v1/", "/platform/", "/api/v1/")):
                error_logger.exception(
                    json.dumps(
                        {**base, "event": "error", "status": 500},
                        ensure_ascii=False,
                    )
                )
            raise
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        response.headers.setdefault("X-Request-ID", request_id)
        if path.startswith(("/v1/", "/platform/", "/api/v1/")):
            access_logger.info(
                json.dumps(
                    {
                        **base,
                        "status": response.status_code,
                        "duration_ms": duration_ms,
                    },
                    ensure_ascii=False,
                )
            )
            if response.status_code >= 400:
                prefix = "/".join(
                    [part for part in path.strip("/").split("/") if part][:2]
                )
                key = (response.status_code, prefix)
                app.state.error_counts[key] = (
                    app.state.error_counts.get(key, 0) + 1
                )
                error_logger.warning(
                    json.dumps(
                        {
                            **base,
                            "event": "error",
                            "status": response.status_code,
                            "route": prefix,
                        },
                        ensure_ascii=False,
                    )
                )
        return response

    return app
