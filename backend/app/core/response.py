"""统一响应体与全局异常处理器。"""

import logging
from contextvars import ContextVar
from typing import Any, Generic, TypeVar

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core.exceptions import AppException, ErrorCode

logger = logging.getLogger(__name__)
T = TypeVar("T")

trace_id_var: ContextVar[str] = ContextVar("trace_id", default="")


def get_current_trace_id() -> str:
    return trace_id_var.get()


class ResponseBase(BaseModel):
    code: int
    message: str
    data: Any = None
    trace_id: str


class PaginatedData(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


def success(data: Any = None, message: str = "success") -> dict:
    return {
        "code": 0,
        "message": message,
        "data": data,
        "trace_id": get_current_trace_id(),
    }


def error(code: int, message: str, data: Any = None) -> dict:
    return {
        "code": code,
        "message": message,
        "data": data,
        "trace_id": get_current_trace_id(),
    }


def paginated(items: list, total: int, page: int, page_size: int) -> dict:
    return success(data=PaginatedData(items=items, total=total, page=page, page_size=page_size).model_dump())


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppException)
    async def _handle_app_exception(request: Request, exc: AppException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.http_status,
            content=error(code=exc.code, message=exc.message, data=exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_exception(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content=error(
                code=ErrorCode.VALIDATION_ERROR,
                message="参数校验失败",
                data={"errors": jsonable_encoder(exc.errors())},
            ),
        )

    @app.exception_handler(Exception)
    async def _handle_generic_exception(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(
            "未捕获的异常: path=%s method=%s trace_id=%s",
            request.url.path,
            request.method,
            get_current_trace_id(),
        )
        return JSONResponse(
            status_code=500,
            content=error(code=ErrorCode.SYSTEM_INTERNAL_ERROR, message="服务器内部错误"),
        )
