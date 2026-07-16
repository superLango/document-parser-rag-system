"""FastAPI 应用入口模块。

本模块定义了 Document Parser API 的主应用实例，包含：
- FastAPI 应用创建与元信息配置
- Prometheus 指标集成（/metrics 端点，供 Prometheus 抓取）
- CORS 中间件配置（开发环境允许所有来源）
- trace_id 链路追踪中间件
- 全局异常处理器注册
- 健康检查与根信息端点
- API v1 路由注册

启动方式：
    python -m app.main
    或
    uvicorn app.main:app --reload
"""

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.deps import limiter
from app.api.v1.router import api_router
from app.core.logging import add_trace_id_middleware
from app.core.response import register_exception_handlers

app = FastAPI(
    title="Document Parser API",
    version="1.0.0",
    description="文档解析与 RAG 系统后端 API",
)

# ---------------------------------------------------------------
# Prometheus 指标集成
# 暴露 /metrics 端点供 Prometheus 抓取，记录 HTTP 请求量/延迟/进行中数等指标。
# 通过 ENABLE_METRICS 环境变量控制是否启用，避免测试环境受影响。
# excluded_handlers 排除 /metrics 自身，防止自引用污染数据。
# ---------------------------------------------------------------
Instrumentator(
    should_group_status_codes=True,
    should_ignore_untemplated=True,
    should_respect_env_var=True,
    should_instrument_requests_inprogress=True,
    excluded_handlers=["/metrics"],
    env_var_name="ENABLE_METRICS",
    inprogress_name="fastapi_inprogress",
    inprogress_labels=True,
).instrument(app).expose(app, endpoint="/metrics", include_render=False)

# 配置 CORS 中间件（开发环境允许所有来源）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册 trace_id 链路追踪中间件，自动从请求头读取或生成 trace_id
app.add_middleware(BaseHTTPMiddleware, dispatch=add_trace_id_middleware)

# 注册 slowapi 限流器
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# 注册全局异常处理器，统一响应体格式
register_exception_handlers(app)

# 注册 API v1 路由
app.include_router(api_router, prefix="/api/v1")


@app.get("/", tags=["root"])
async def root() -> dict[str, str]:
    """根端点，返回 API 基本信息。

    Returns:
        dict[str, str]: 包含服务名称、版本与文档地址的字典。
    """
    return {"name": "Document Parser API", "version": "1.0.0", "docs": "/docs"}


@app.get("/health", tags=["health"])
async def health_check() -> dict[str, str]:
    """健康检查端点。

    用于监控与负载均衡探针，确认服务可用性。

    Returns:
        dict[str, str]: 包含服务状态的字典，例如 {"status": "ok"}。
    """
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
