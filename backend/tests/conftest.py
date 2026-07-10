"""pytest 测试公共配置模块。

提供全局 fixtures：
- db_session：基于内存 SQLite 的异步数据库会话（通过依赖注入覆盖 get_db）
- client：覆盖了 get_db 和 get_current_active_user 依赖的 TestClient
- auth_headers：携带有效 JWT 的认证请求头

测试中通过 mock 控制数据库与存储服务行为，不依赖外部服务。
"""

import uuid
from datetime import datetime
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import get_current_active_user
from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app


@pytest.fixture
def db_session():
    """创建测试用内存 SQLite 异步会话。

    使用 create_async_engine 创建内存 SQLite 引擎，构建异步会话。
    通过依赖注入覆盖 get_db，使端点使用测试会话。
    实际数据库操作在各测试中通过 mock 控制，不产生真实连接。
    """
    # 创建内存 SQLite 异步引擎（不实际连接，测试中通过 mock 控制）
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    session = session_factory()
    yield session


@pytest.fixture
def client(db_session):
    """创建测试客户端，覆盖数据库与认证依赖。

    将 get_db 依赖替换为返回测试会话的异步生成器，
    将 get_current_active_user 替换为返回模拟用户的函数，
    使所有端点使用统一的测试会话与模拟用户。
    """
    async def override_get_db():
        yield db_session

    # 构造模拟已认证用户
    mock_user = MagicMock()
    mock_user.id = uuid.uuid4()
    mock_user.username = "testuser"
    mock_user.email = "test@example.com"
    mock_user.is_active = True
    mock_user.created_at = datetime.now()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_active_user] = lambda: mock_user

    with TestClient(app) as c:
        yield c

    # 清理依赖覆盖，避免影响后续测试
    app.dependency_overrides.clear()


@pytest.fixture
def auth_headers():
    """返回携带有效 JWT 的认证请求头。

    使用应用配置的 SECRET_KEY 签发真实 JWT，
    用于需要 Bearer Token 鉴权的端点。
    """
    token = create_access_token(data={"sub": "testuser"})
    return {"Authorization": f"Bearer {token}"}
