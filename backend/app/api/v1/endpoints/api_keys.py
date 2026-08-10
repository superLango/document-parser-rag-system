"""P2 端点：API Key 管理。"""

import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user
from app.core.database import get_db
from app.core.response import success
from app.middleware.audit_log import audit_action
from app.models.user import User
from app.schemas.api_key import ApiKeyCreate
from app.services import workspace_service

router = APIRouter(prefix="/api-keys", tags=["API Key"])


@router.get("")
async def list_api_keys(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    return success(data=await workspace_service.list_api_keys(db, current_user))


@router.post("")
@audit_action(action="api_key.create", resource_type="api_key")
async def create_api_key(
    body: ApiKeyCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    data, secret = await workspace_service.create_api_key(
        db, current_user, body.name, body.scopes, body.expires_at
    )
    data["secret"] = secret
    return success(
        data=data,
        message="API Key 已创建，请立即保存密钥（仅此一次展示）",
    )


@router.delete("/{key_id}")
@audit_action(action="api_key.revoke", resource_type="api_key")
async def revoke_api_key(
    key_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    await workspace_service.revoke_api_key(db, current_user, key_id)
    return success(message="API Key 已撤销")
