"""共享测试夹具：测试库环境、ASGI 客户端、登录助手。"""

import os

# 必须在导入 app 之前设置，确保 engine/AsyncSessionLocal 指向测试库
os.environ["DATABASE_URL"] = "postgresql+asyncpg://postgres@localhost:5432/hanson_doc_rag_test"
os.environ["POSTGRES_DB"] = "hanson_doc_rag_test"
os.environ["DEBUG"] = "false"
os.environ["AUTO_CREATE_ADMIN"] = "true"
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "admin123"
os.environ["ALLOW_REGISTRATION"] = "true"
os.environ["SECRET_KEY"] = "qa_test_secret_key_at_least_32_chars_123456"
os.environ["ACCESS_TOKEN_EXPIRE_MINUTES"] = "60"
os.environ["STORAGE_DRIVER"] = "local"
os.environ["LOCAL_STORAGE_DIR"] = "/tmp/hansondoc_phase1_test"
os.environ["TASK_EXECUTOR"] = "sync"
os.environ["PARSEKIT_LAYOUT_ENGINE"] = "rule"
os.environ["PARSEKIT_OCR_ENABLED"] = "false"

import uuid

import httpx
import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal, engine
from app.main import app
from app.models.user import User
from app.services.bootstrap import ensure_initial_admin, ensure_rbac_seed


@pytest.fixture(scope="session", autouse=True)
async def prepare_test_db():
    """初始化测试库：初始管理员 + RBAC 种子；关闭限流便于并发/暴力测试。"""
    await ensure_initial_admin()
    await ensure_rbac_seed()
    app.state.limiter.enabled = False
    yield
    await engine.dispose()


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


@pytest.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        yield session


async def api_login(
    client: httpx.AsyncClient, username: str = "admin", password: str = "admin123"
) -> str:
    resp = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["access_token"]


async def db_get_user_by_username(db, username: str) -> User | None:
    return (
        await db.execute(select(User).where(User.username == username))
    ).scalar_one_or_none()


@pytest.fixture
async def super_token(client):
    return await api_login(client, "admin", "admin123")


@pytest.fixture
async def member_user(client, super_token, request):
    """创建一个 member 用户并返回 (token, username, password)。"""
    base = getattr(request, "param", "member_qa")
    username = f"{base}_{uuid.uuid4().hex[:8]}"
    password = "Test@1234"
    resp = await client.post(
        "/api/v1/users",
        headers={"Authorization": f"Bearer {super_token}"},
        json={
            "username": username,
            "password": password,
            "full_name": "QA 成员",
            "role_codes": ["member"],
        },
    )
    assert resp.status_code == 200, resp.text
    token = await api_login(client, username, password)
    return token, username, password
