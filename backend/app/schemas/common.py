"""通用 Schema 模块。

定义分页参数与统一响应体，供其他模块复用。
统一响应体遵循 API 契约规范：
    {"code": 0, "message": "success", "data": {...}, "trace_id": "uuid"}
"""

from typing import Any

from pydantic import BaseModel, field_validator


class PaginationParams(BaseModel):
    """分页查询参数。

    通过字段校验器约束 page 与 page_size 的取值范围，
    防止非法分页参数导致查询异常。

    Attributes:
        page: 当前页码，从 1 开始计数。
        page_size: 每页条数，取值范围 1-100。
    """

    page: int = 1
    page_size: int = 20

    @field_validator("page")
    @classmethod
    def validate_page(cls, v: int) -> int:
        """校验页码不小于 1。"""
        if v < 1:
            return 1
        return v

    @field_validator("page_size")
    @classmethod
    def validate_page_size(cls, v: int) -> int:
        """校验每页条数在 1-100 之间。"""
        if v < 1:
            return 1
        if v > 100:
            return 100
        return v


class ApiResponse(BaseModel):
    """统一响应体。

    所有 API 端点返回该结构，code=0 表示成功，
    非零表示业务错误（1xxxx 参数校验、2xxxx 鉴权、3xxxx 业务、5xxxx 系统）。

    Attributes:
        code: 业务状态码，0 表示成功。
        message: 描述信息。
        data: 业务数据载荷，类型不限。
        trace_id: 全链路追踪 ID，用于日志关联。
    """

    code: int = 0
    message: str = "success"
    data: Any = None
    trace_id: str = ""
