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
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from prometheus_fastapi_instrumentator import Instrumentator
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.deps import limiter
from app.api.v1.router import api_router
from app.core.config import settings
from app.core.database import engine
from app.core.logging import add_trace_id_middleware, get_logger
from app.core.response import register_exception_handlers

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理（P1-3 优雅关闭）。

    startup：记录启动日志。
    shutdown：优雅关闭数据库连接池，等待进行中的查询完成，
    避免进程被杀时进行中的请求/任务中断。
    """
    logger.info("应用启动", app_name="HansonDOC RAG", env=settings.APP_ENV)
    yield
    logger.info("应用关闭中，释放资源...")
    try:
        await engine.dispose()
        logger.info("数据库连接池已关闭")
    except Exception as exc:  # noqa: BLE001
        logger.warning("数据库连接池关闭异常", error=str(exc))


app = FastAPI(
    title="Document Parser API",
    version="1.0.0",
    description="文档解析与 RAG 系统后端 API",
    lifespan=lifespan,
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

# 配置 CORS 中间件：从 settings.CORS_ORIGINS 解析（逗号分隔），
# "*" 表示开发环境允许所有来源；生产环境应严格限定为前端域名。
# 注意：allow_credentials=True 时 CORS 规范不允许 "*"，需展开为具体来源。
_cors_raw = settings.CORS_ORIGINS.strip()
if _cors_raw == "*" or not _cors_raw:
    _cors_origins = ["*"]
    _cors_credentials = False  # "*" + credentials 不合规，强制关闭
else:
    _cors_origins = [o.strip() for o in _cors_raw.split(",") if o.strip()]
    _cors_credentials = True

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=_cors_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

# GZip 压缩中间件（P1-4）：压缩大响应体（抽取结果/搜索结果/导出数据），
# minimum_size=1024 避免压缩小响应。SSE 响应通过 Content-Encoding: identity 头跳过。
app.add_middleware(GZipMiddleware, minimum_size=1024)

# API 版本管理中间件（P3-10）：添加 X-API-Version 头 + 弃用端点标记
from app.middleware.api_version import ApiVersionMiddleware  # noqa: E402

app.add_middleware(ApiVersionMiddleware)

# 注册 trace_id 链路追踪中间件，自动从请求头读取或生成 trace_id
app.add_middleware(BaseHTTPMiddleware, dispatch=add_trace_id_middleware)

# 注册管理端 IP 白名单中间件（/api/v1/admin/* 路径强制 IP 校验）
from app.middleware.ip_whitelist import IpWhitelistMiddleware  # noqa: E402

app.add_middleware(IpWhitelistMiddleware)

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
