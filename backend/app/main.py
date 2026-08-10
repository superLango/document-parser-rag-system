"""HansonDOC RAG（重构版）FastAPI 应用入口。"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
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
from app.middleware.ip_whitelist import IpWhitelistMiddleware
from app.services.bootstrap import ensure_initial_admin, ensure_rbac_seed

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "应用启动",
        app_name=settings.APP_NAME,
        env=settings.APP_ENV,
        version=settings.VERSION,
        database=settings.POSTGRES_DB,
    )
    await ensure_initial_admin()
    await ensure_rbac_seed()
    yield
    try:
        await engine.dispose()
        logger.info("数据库连接池已关闭")
    except Exception as exc:
        logger.warning("数据库连接池关闭异常", error=str(exc))


app = FastAPI(
    title="HansonDOC RAG API",
    version=settings.VERSION,
    description="HansonDOC RAG（重构版）后端 API",
    lifespan=lifespan,
)

# CORS
_cors_raw = settings.CORS_ORIGINS.strip()
if _cors_raw == "*" or not _cors_raw:
    _cors_origins = ["*"]
    _cors_credentials = False
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
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(BaseHTTPMiddleware, dispatch=add_trace_id_middleware)
app.add_middleware(IpWhitelistMiddleware)

# 限流
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# 统一异常响应
register_exception_handlers(app)

# 路由
app.include_router(api_router, prefix="/api/v1")


@app.get("/", tags=["root"])
async def root() -> dict[str, str]:
    return {"name": "HansonDOC RAG API", "version": settings.VERSION, "docs": "/docs"}


@app.get("/health", tags=["health"])
async def health_check() -> dict[str, str]:
    return {"status": "ok"}
