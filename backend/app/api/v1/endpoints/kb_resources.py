# ruff: noqa: B008 - FastAPI Depends 默认参数为框架标准写法
"""KB 资源与配置端点（E2：LLM 服务）。"""

import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import activate_kb_context, require_not_pending
from app.api.v1.endpoints.kb_documents import _require_editor
from app.core.database import get_db
from app.core.response import success
from app.middleware.audit_log import audit_action
from app.models.user import User
from app.schemas.resource import LLMResourceSave
from app.services import kb_resource_service, kb_service

router = APIRouter(prefix="/kb/{kb_id}/resources", tags=["知识库-资源与配置"])


async def _kb_access(
    kb_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_pending),
) -> dict:
    data = await kb_service.get_kb(db, current_user, kb_id)
    await activate_kb_context(db, kb_id, current_user)
    return data


@router.get("/llm")
async def get_llm_resource(
    kb_id: uuid.UUID, request: Request,
    db: AsyncSession = Depends(get_db), current_user: User = Depends(require_not_pending),
) -> dict:
    await _kb_access(kb_id, db=db, current_user=current_user)
    return success(data=await kb_resource_service.get_llm_resource(db, kb_id))


@router.put("/llm")
@audit_action(action="resource.llm.save", resource_type="resource_llm")
async def save_llm_resource(
    kb_id: uuid.UUID, payload: LLMResourceSave, request: Request,
    db: AsyncSession = Depends(get_db), current_user: User = Depends(require_not_pending),
) -> dict:
    kb = await _kb_access(kb_id, db=db, current_user=current_user)
    _require_editor(kb)
    data = await kb_resource_service.save_llm_resource(db, kb_id, payload.model_dump())
    return success(data=data, message="LLM 服务配置已保存")


@router.post("/llm/test")
@audit_action(action="resource.llm.test", resource_type="resource_llm")
async def test_llm_resource(
    kb_id: uuid.UUID, payload: LLMResourceSave, request: Request,
    db: AsyncSession = Depends(get_db), current_user: User = Depends(require_not_pending),
) -> dict:
    kb = await _kb_access(kb_id, db=db, current_user=current_user)
    _require_editor(kb)
    data = await kb_resource_service.test_llm_resource(db, kb_id, payload.model_dump())
    return success(data=data)
