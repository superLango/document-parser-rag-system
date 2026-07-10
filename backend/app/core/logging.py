"""结构化日志模块。

本模块基于 structlog 提供结构化日志能力，并集成分布式链路追踪 ID（trace_id）：

- 使用 JSON 格式输出日志，便于 ELK / Loki 等日志平台采集与检索
- 通过 contextvar 在整个异步调用链中传播 trace_id
- 提供 FastAPI 中间件，自动从请求头读取或生成 trace_id，并写入响应头
- 提供 get_logger() 工厂函数，返回绑定了 trace_id 的 logger

trace_id 规范：
    优先读取请求头 X-Trace-Id；若缺失则生成 UUID v4。
    该 ID 贯穿日志与响应体，便于全链路排障（见 docs/API_CONTRACT.md）。

使用方式：
    from app.core.logging import get_logger

    logger = get_logger(__name__)
    logger.info("document_parsed", doc_id=123)
"""

import logging
import uuid
from contextvars import ContextVar
from typing import Any

import structlog
from fastapi import Request, Response
from starlette.middleware.base import RequestResponseEndpoint

from app.core.config import settings

# trace_id 上下文变量，跨 async 任务传播
trace_id_ctx: ContextVar[str] = ContextVar("trace_id_ctx", default="")

# 请求头中 trace_id 的字段名（与 API 契约文档保持一致）
TRACE_ID_HEADER: str = "X-Trace-Id"


def _inject_trace_id(
    _logger: Any, _method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """structlog 处理器：将 contextvar 中的 trace_id 注入日志事件字典。

    Args:
        _logger: 当前 logger 实例（未使用）。
        _method_name: 调用的日志方法名（未使用）。
        event_dict: 当前日志事件的字典。

    Returns:
        dict[str, Any]: 注入 trace_id 后的事件字典。
    """
    trace_id = trace_id_ctx.get()
    if trace_id:
        event_dict["trace_id"] = trace_id
    return event_dict


def configure_logging() -> None:
    """初始化并配置 structlog。

    配置的处理器链：
        1. merge_contextvars       - 合并 structlog 上下文变量
        2. add_log_level           - 添加 level 字段
        3. TimeStamper(fmt="iso") - 添加 ISO 8601 时间戳
        4. _inject_trace_id        - 注入 trace_id 字段
        5. JSONRenderer            - 序列化为 JSON 字符串

    该函数应在应用启动时调用一次。
    """
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
    """FastAPI 中间件：注入并传播 trace_id。

    处理流程：
        1. 从请求头 X-Trace-Id 读取 trace_id，缺失则生成 UUID v4
        2. 将 trace_id 写入 contextvar，供下游异步代码读取
        3. 处理请求并获取响应
        4. 将 trace_id 写入响应头 X-Trace-Id
        5. 重置 contextvar，避免污染后续请求

    Args:
        request: 当前 FastAPI 请求对象。
        call_next: 下一个 ASGI 中间件或路由处理器。

    Returns:
        Response: 携带 X-Trace-Id 响应头的 Response 对象。
    """
    # 读取或生成 trace_id
    trace_id: str = request.headers.get(TRACE_ID_HEADER) or str(uuid.uuid4())

    # 写入 contextvar，使日志处理器能够读取
    token = trace_id_ctx.set(trace_id)

    try:
        # 调用下游处理逻辑
        response: Response = await call_next(request)
        # 在响应头中回写 trace_id，便于客户端关联
        response.headers[TRACE_ID_HEADER] = trace_id
        return response
    finally:
        # 重置 contextvar，防止泄漏到其他请求
        trace_id_ctx.reset(token)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """返回绑定了当前 trace_id 的 structlog logger。

    该 logger 通过 contextvar 自动获取当前请求的 trace_id，
    因此在异步上下文中使用时无需手动传递 trace_id。

    Args:
        name: logger 名称，通常传入 __name__。

    Returns:
        structlog.stdlib.BoundLogger: 已绑定 trace_id 的日志记录器。
    """
    return structlog.get_logger(name)


# 在模块导入时完成一次性配置，简化使用方调用
configure_logging()
