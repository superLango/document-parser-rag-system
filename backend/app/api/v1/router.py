"""API v1 路由聚合。"""

from fastapi import APIRouter

from app.api.v1.endpoints import (
    api_keys,
    audit_logs,
    auth,
    dashboard,
    kb,
    kb_documents,
    kb_indexing,
    roles,
    system,
    users,
    workspaces,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(roles.router)
api_router.include_router(kb.router)
api_router.include_router(kb_documents.router)
api_router.include_router(kb_indexing.router)
api_router.include_router(workspaces.router)
api_router.include_router(api_keys.router)
api_router.include_router(audit_logs.router)
api_router.include_router(dashboard.router)
api_router.include_router(system.router)
