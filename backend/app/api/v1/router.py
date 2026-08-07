"""API v1 路由聚合模块。

将各资源端点的子路由聚合为统一的 ``api_router``，
供 ``app.main`` 在应用级别挂载到 ``/api/v1`` 前缀下。

使用方式：
    from app.api.v1.router import api_router

    app.include_router(api_router)
"""

from fastapi import APIRouter

from app.api.v1.endpoints.audit_logs import router as audit_logs_router
from app.api.v1.endpoints.auth import router as auth_router
from app.api.v1.endpoints.kb_backup import router as kb_backup_router
from app.api.v1.endpoints.dashboard import router as dashboard_router
from app.api.v1.endpoints.extraction import router as extraction_router
from app.api.v1.endpoints.extraction_config import router as extraction_config_router
from app.api.v1.endpoints.kb_config import router as kb_config_router
from app.api.v1.endpoints.kb_documents import router as kb_documents_router
from app.api.v1.endpoints.kb_extraction import router as kb_extraction_router
from app.api.v1.endpoints.kb_graph import router as kb_graph_router
from app.api.v1.endpoints.kb_qa import router as kb_qa_router
from app.api.v1.endpoints.kb_qa_history import router as kb_qa_history_router
from app.api.v1.endpoints.kb_search import router as kb_search_router
from app.api.v1.endpoints.kb_tasks import router as kb_tasks_router
from app.api.v1.endpoints.kb_terms import router as kb_terms_router
from app.api.v1.endpoints.kb_term_bases import router as kb_term_bases_router
from app.api.v1.endpoints.kbs import router as kbs_router
from app.api.v1.endpoints.notifications import router as notifications_router
from app.api.v1.endpoints.public_extraction import router as public_extraction_router
from app.api.v1.endpoints.schema_templates import router as schema_templates_router
from app.api.v1.endpoints.system import router as system_router
from app.api.v1.endpoints.tasks import router as tasks_router
from app.api.v1.endpoints.users import router as users_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(users_router)
api_router.include_router(audit_logs_router)
api_router.include_router(system_router)
api_router.include_router(notifications_router)
api_router.include_router(dashboard_router)
api_router.include_router(extraction_router)
api_router.include_router(extraction_config_router)
# kb_config_router 必须在 kbs_router 之前注册：
# /kbs/templates 与 /kbs/{kb_id} 路径参数竞争，先注册先匹配
api_router.include_router(kb_config_router)
api_router.include_router(kbs_router)
api_router.include_router(kb_documents_router)
api_router.include_router(kb_tasks_router)
api_router.include_router(kb_extraction_router)
api_router.include_router(kb_term_bases_router)
api_router.include_router(kb_terms_router)
api_router.include_router(kb_graph_router)
api_router.include_router(kb_qa_router)
api_router.include_router(kb_qa_history_router)
api_router.include_router(kb_search_router)
api_router.include_router(kb_backup_router)
api_router.include_router(schema_templates_router)
api_router.include_router(tasks_router)
api_router.include_router(public_extraction_router)
