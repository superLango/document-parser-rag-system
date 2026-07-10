"""统一响应模型与辅助函数模块。

本模块依据 `docs/API_CONTRACT.md` 第 1 节定义的统一响应体结构，提供：

- `ResponseBase`：统一响应体模型，包含 ``code`` / ``message`` / ``data`` /
  ``trace_id`` 四个字段。
- `PaginatedData`：泛型分页数据模型，作为列表类接口 ``data`` 字段的载荷结构。
- `success` / `error` / `paginated` 三个辅助函数，快速构造符合契约的响应字典。
- `trace_id_var`：基于 `contextvars.ContextVar` 的链路追踪 ID 上下文变量，
  配合 `get_current_trace_id` 在任意层级获取当前请求的 trace_id。
- `register_exception_handlers`：向 FastAPI 应用注册全局异常处理器，将
  `AppException`、`RequestValidationError` 以及未捕获的 `Exception` 统一转换为
  契约规定的响应体格式。

使用方式：
    from app.core.response import success, error, register_exception_handlers

    @app.get("/items")
    async def list_items():
        return success(data={"items": []})

    register_exception_handlers(app)
"""

import logging
from contextvars import ContextVar
from typing import Any, Generic, TypeVar

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core.exceptions import (
    AppException,
    ErrorCode,
)

logger = logging.getLogger(__name__)

# 泛型类型变量，用于 PaginatedData 的元素类型约束
T = TypeVar("T")

# 链路追踪 ID 上下文变量，由请求中间件在请求起始处设置。
# 默认为空字符串，未经过中间件时返回空串而非 None，便于直接拼接到响应体。
trace_id_var: ContextVar[str] = ContextVar("trace_id", default="")


def get_current_trace_id() -> str:
    """获取当前请求上下文中的 trace_id。

    trace_id 由请求中间件（Phase 1 后续将引入）在请求开始时通过
    ``trace_id_var.set(...)`` 写入。本函数可在任意层级安全调用，
    若上下文未设置则返回空字符串。

    Returns:
        str: 当前请求的 trace_id，未设置时为 ""。
    """
    return trace_id_var.get()


class ResponseBase(BaseModel):
    """统一响应体模型。

    对应 `docs/API_CONTRACT.md` 第 1 节定义的响应结构：

    Attributes:
        code: 业务状态码，0 表示成功，非 0 表示业务错误。
        message: 人类可读的状态描述，成功为 "success"。
        data: 业务数据载荷，失败时可为 None。
        trace_id: 分布式链路追踪 ID（UUID v4），用于全链路日志关联。
    """

    code: int
    message: str
    data: Any = None
    trace_id: str


class PaginatedData(BaseModel, Generic[T]):
    """分页数据模型。

    对应 `docs/API_CONTRACT.md` 第 3 节定义的分页结构，作为列表类接口
    ``data`` 字段的统一载荷。

    Attributes:
        items: 当前页数据条目列表。
        total: 符合条件的总记录数。
        page: 当前页码，从 1 开始。
        page_size: 每页条数。
    """

    items: list[T]
    total: int
    page: int
    page_size: int


def success(data: Any = None, message: str = "success") -> dict:
    """构造成功响应字典。

    Args:
        data: 业务数据载荷，默认为 None。
        message: 状态描述，默认为 "success"。

    Returns:
        dict: 形如 ``{"code": 0, "message": ..., "data": ..., "trace_id": ...}``
            的字典，可直接作为接口返回值。
    """
    return {
        "code": 0,
        "message": message,
        "data": data,
        "trace_id": get_current_trace_id(),
    }


def error(code: int, message: str, data: Any = None) -> dict:
    """构造错误响应字典。

    Args:
        code: 业务错误码（非 0），建议使用 `ErrorCode` 枚举值。
        message: 错误描述。
        data: 可选的附加详情，默认为 None。

    Returns:
        dict: 形如 ``{"code": ..., "message": ..., "data": ..., "trace_id": ...}``
            的字典，可直接作为接口返回值或异常处理器响应体。
    """
    return {
        "code": code,
        "message": message,
        "data": data,
        "trace_id": get_current_trace_id(),
    }


def paginated(items: list, total: int, page: int, page_size: int) -> dict:
    """构造分页成功响应字典。

    将列表数据包装为 `PaginatedData` 结构后放入成功响应的 ``data`` 字段。

    Args:
        items: 当前页数据条目列表。
        total: 符合条件的总记录数。
        page: 当前页码，从 1 开始。
        page_size: 每页条数。

    Returns:
        dict: 形如 ``{"code": 0, "message": "success",
            "data": {"items": ..., "total": ..., "page": ..., "page_size": ...},
            "trace_id": ...}`` 的字典。
    """
    paginated_data = PaginatedData(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )
    return success(data=paginated_data.model_dump())


def register_exception_handlers(app: FastAPI) -> None:
    """向 FastAPI 应用注册全局异常处理器。

    将以下三类异常统一转换为 `docs/API_CONTRACT.md` 规定的响应体格式：

    - `AppException`（及其子类）：按异常自身携带的 ``code`` / ``message`` /
      ``http_status`` 转换，``details`` 放入 ``data`` 字段。
    - `RequestValidationError`：FastAPI 请求参数校验失败，统一映射为
      HTTP 400 与错误码 `ErrorCode.VALIDATION_ERROR`，校验错误详情放入
      ``data`` 字段。
    - 任意未捕获的 `Exception`：兜底处理为 HTTP 500 与错误码
      `ErrorCode.SYSTEM_INTERNAL_ERROR`，详细堆栈记录在服务端日志中，
      不向前端暴露内部错误细节。

    Args:
        app: FastAPI 应用实例。
    """

    @app.exception_handler(AppException)
    async def _handle_app_exception(
        request: Request, exc: AppException
    ) -> JSONResponse:
        """处理应用自定义异常，按其携带的 HTTP 状态码与错误码返回。"""
        return JSONResponse(
            status_code=exc.http_status,
            content=error(
                code=exc.code,
                message=exc.message,
                data=exc.details,
            ),
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_exception(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """处理 FastAPI 请求参数校验异常，统一返回 HTTP 400。"""
        return JSONResponse(
            status_code=400,
            content=error(
                code=ErrorCode.VALIDATION_ERROR,
                message="参数校验失败",
                data={"errors": jsonable_encoder(exc.errors())},
            ),
        )

    @app.exception_handler(Exception)
    async def _handle_generic_exception(
        request: Request, exc: Exception
    ) -> JSONResponse:
        """兜底处理未捕获异常，返回 HTTP 500 并记录服务端日志。"""
        logger.exception(
            "未捕获的异常: path=%s method=%s trace_id=%s",
            request.url.path,
            request.method,
            get_current_trace_id(),
        )
        return JSONResponse(
            status_code=500,
            content=error(
                code=ErrorCode.SYSTEM_INTERNAL_ERROR,
                message="服务器内部错误",
            ),
        )
