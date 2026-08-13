"""L4 边界：E2 资源配置非法值/未启用/Key 不泄露。"""

import uuid

import pytest
from app.core.exceptions import BusinessException
from app.services import kb_resource_service
from sqlalchemy import text as sa_text

from qa.fixtures.indexing_helpers import create_kb_via_api

H = "Authorization"


async def test_llm_resource_invalid_base_rejected(client, super_token):
    """L4E2-01：非法 api_base 返回 400。"""
    kb = await create_kb_via_api(client, super_token, "E2非法")
    r = await client.put(f"/api/v1/kb/{kb['id']}/resources/llm", headers={H: f"Bearer {super_token}"}, json={
        "enabled": True, "api_base": "ftp://x", "model": "m", "timeout": 300,
    })
    assert r.status_code == 400


async def test_build_client_requires_enabled(client, super_token, db_session):
    """L4E2-02：未启用/缺模型时 build_llm_client 报错。"""
    kb = await create_kb_via_api(client, super_token, "E2构建")
    await db_session.execute(sa_text("SELECT set_config('app.is_superuser', 'true', true)"))
    with pytest.raises(BusinessException, match="未启用"):
        await kb_resource_service.build_llm_client(db_session, uuid.UUID(kb["id"]))
    await kb_resource_service.save_llm_resource(db_session, uuid.UUID(kb["id"]), {
        "enabled": True, "api_base": "http://127.0.0.1:8001/v1", "model": "", "timeout": 300,
    })
    with pytest.raises(BusinessException, match="未配置"):
        await kb_resource_service.build_llm_client(db_session, uuid.UUID(kb["id"]))
