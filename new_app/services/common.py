import inspect
import os
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from hanson_obs import inc, observe, render_prometheus

SERVICE_VERSION = "0.0.0"
# P2-06：设置后所有服务要求 Bearer token；为空时保持本地/内网免鉴权。
API_AUTH_TOKEN = os.getenv("API_AUTH_TOKEN", "")
PUBLIC_PATHS = {"/healthz", "/readyz", "/metrics"}

ReadinessCheck = Callable[[], "dict[str, Any] | Awaitable[dict[str, Any]]"]


def create_app(
    service_name: str,
    version: str = SERVICE_VERSION,
    lifespan: Any | None = None,
    readiness: ReadinessCheck | None = None,
) -> FastAPI:
    app = FastAPI(title=f"Hanson {service_name}", version=version, lifespan=lifespan)

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        if API_AUTH_TOKEN and request.url.path not in PUBLIC_PATHS:
            expected = f"Bearer {API_AUTH_TOKEN}"
            if request.headers.get("authorization", "") != expected:
                return JSONResponse(status_code=401, content={"detail": "unauthorized"})
        return await call_next(request)

    @app.middleware("http")
    async def metrics_middleware(request: Request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        elapsed = time.perf_counter() - started
        route = request.scope.get("route")
        path = getattr(route, "path", None) or request.url.path
        inc(
            "hanson_http_requests_total",
            method=request.method,
            path=path,
            status=str(response.status_code),
        )
        observe(
            "hanson_http_request_duration_seconds",
            elapsed,
            method=request.method,
            path=path,
        )
        response.headers.setdefault("x-content-type-options", "nosniff")
        response.headers.setdefault("x-frame-options", "DENY")
        response.headers.setdefault("referrer-policy", "no-referrer")
        return response

    @app.get("/metrics")
    def metrics() -> PlainTextResponse:
        """P2-05：Prometheus 文本格式指标（进程内计数）。"""
        return PlainTextResponse(
            render_prometheus(), media_type="text/plain; version=0.0.4"
        )

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        """进程存活探针：不访问任何依赖。"""
        return {"status": "ok", "service": service_name, "version": version}

    @app.get("/readyz")
    async def readyz() -> Any:
        """就绪探针：依赖不可用时返回 503，避免流量进入。"""
        if readiness is None:
            return {"status": "ready", "service": service_name, "version": version}
        try:
            detail = readiness()
            if inspect.isawaitable(detail):
                detail = await detail
        except Exception as exc:  # noqa: BLE001 - 探针需要吞掉具体异常并报告 503
            return JSONResponse(
                status_code=503,
                content={
                    "status": "not_ready",
                    "service": service_name,
                    "version": version,
                    "error": str(exc)[:200],
                },
            )
        checks = detail if isinstance(detail, dict) else {}
        status = str(checks.pop("status", "ready"))
        body = {"status": status, "service": service_name, "version": version, **checks}
        if status != "ready":
            return JSONResponse(status_code=503, content=body)
        return body

    return app


@asynccontextmanager
async def empty_lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
