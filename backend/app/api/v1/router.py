"""API v1 路由聚合模块。

将各资源端点（auth、documents 等）的子路由聚合为统一的 ``api_router``，
供 ``app.main`` 在应用级别挂载到 ``/api/v1`` 前缀下。

使用方式：
    from app.api.v1.router import api_router

    app.include_router(api_router)
"""

from fastapi import APIRouter

from app.api.v1.endpoints.auth import router as auth_router
from app.api.v1.endpoints.documents import router as documents_router
from app.api.v1.endpoints.knowledge_base import router as kb_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(documents_router)
api_router.include_router(kb_router)
