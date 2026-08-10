"""结构化日志与 trace_id 链路追踪。"""

import logging
import uuid
from contextvars import ContextVar
from typing import Any

import structlog
from fastapi import Request, Response
from starlette.middleware.base import RequestResponseEndpoint

from app.core.config import settings

trace_id_ctx: ContextVar[str] = ContextVar("trace_id_ctx", default="")
TRACE_ID_HEADER: str = "X-Trace-Id"


def _inject_trace_id(_logger: Any, _method_name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    trace_id = trace_id_ctx.get()
    if trace_id:
        event_dict["trace_id"] = trace_id
    return event_dict


def configure_logging() -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            _inject_trace_id,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.DEBUG if settings.DEBUG else logging.INFO
        ),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


async def add_trace_id_middleware(
    request: Request, call_next: RequestResponseEndpoint
) -> Response:
    trace_id: str = request.headers.get(TRACE_ID_HEADER) or str(uuid.uuid4())
    token = trace_id_ctx.set(trace_id)
    try:
        response: Response = await call_next(request)
        response.headers[TRACE_ID_HEADER] = trace_id
        return response
    finally:
        trace_id_ctx.reset(token)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)


configure_logging()
