"""FastAPI 应用入口模块。

本模块定义了 Document Parser API 的主应用实例，包含：
- FastAPI 应用创建与元信息配置
- CORS 中间件配置（开发环境允许所有来源）
- 健康检查端点
- API 路由注册（Phase 1 将启用）

启动方式：
    python -m app.main
    或
    uvicorn app.main:app --reload
"""

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Phase 1 将在此处导入 API 路由
# from app.api.v1.api import api_router

app = FastAPI(
    title="Document Parser API",
    version="1.0.0",
    description="文档解析与 RAG 系统后端 API",
)

# 配置 CORS 中间件（开发环境允许所有来源）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["health"])
async def health_check() -> dict[str, str]:
    """健康检查端点。

    用于监控与负载均衡探针，确认服务可用性。

    Returns:
        dict[str, str]: 包含服务状态的字典，例如 {"status": "ok"}。
    """
    return {"status": "ok"}


# TODO: Phase 1 将启用 API 路由
# app.include_router(api_router, prefix="/api/v1")


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
